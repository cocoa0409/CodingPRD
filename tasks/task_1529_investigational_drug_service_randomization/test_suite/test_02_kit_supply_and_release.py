"""Kit shipment, receipt, release, and the study-state release gate
(PRD §3.2, §3.3)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId,
    create_study, create_site, create_lot, create_shipment_payload,
    create_staff_member, transition_site, setup_pharmacy, transition_study,
    receive_kit_in_range, release_kit_to_available, get_kit, ship_kits,
)
from test_helpers import TEST_USERS, make_pharmacist_headers

SPONSOR = TEST_USERS["sponsor_admin_headers"]


def test_shipment_creates_kits_in_initial_in_transit_state():
    """PRD §3.2: "The server creates one kit per entry of `kit_numbers`, each
    beginning in `IN_TRANSIT` at the destination site with `units_received` set
    to `units_per_kit`".

    Design: Corner/state_machines/shipment_creates_kits_in_initial_in_transit_state
    """
    study = create_study(protocol_number="P-SM-3", phase="PHASE_I",
                       blinding_model="OPEN_LABEL", max_dose_per_visit_mg=100)
    site = create_site(study["id"])
    lot = create_lot(study["id"], lot_number="LOT-SM-3")
    resp = api_client.create_shipment(
        create_shipment_payload(lot["id"], site["id"], ["K-IT"]), SPONSOR)
    data = validate_success(resp, expected_status=201)
    assert data[0]["status"] == "IN_TRANSIT"


def test_duplicate_kit_number_in_shipment_is_all_or_nothing():
    """PRD §3.2: "if any entry of `kit_numbers` duplicates an existing kit
    number in that study — or duplicates another entry within the same payload —
    the entire shipment is rejected with `ERR_DUPLICATE_KIT_NUMBER` and no kits
    are created."

    Design: Corner/validations/duplicate_kit_number_in_shipment_is_all_or_nothing
    """
    study = create_study(protocol_number="P-VAL-4", phase="PHASE_I",
                       blinding_model="OPEN_LABEL", max_dose_per_visit_mg=100)
    site = create_site(study["id"])
    lot = create_lot(study["id"], lot_number="LOT-VAL-4")
    resp = api_client.create_shipment(
        create_shipment_payload(lot["id"], site["id"], ["K-DUP", "K-DUP", "K-OK"]),
        SPONSOR)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_KIT_NUMBER.value, expected_status=409)
    data, meta = validate_paginated(api_client.list_kits(SPONSOR, params={"lot_id": lot["id"]}))
    assert meta["total_count"] == 0, f"all-or-nothing: expected 0 kits, got {meta['total_count']}"


def test_kit_release_from_available_returns_kit_not_releasable():
    """PRD §3.3: "Release is the pharmacist's disposition of a
    receipt-quarantined kit into dispenseable stock, moving it
    `QUARANTINED_RECEIPT` → `AVAILABLE`. Attempting to release a kit in any
    other state is rejected with `ERR_KIT_NOT_RELEASABLE`."

    Design: Corner/state_machines/kit_release_from_available_returns_kit_not_releasable
    """
    world = setup_pharmacy(protocol_number="P-SM-1", kit_numbers=("K-RL",),
                           pharmacist_license="L-SM-1")
    kit = world["kits"][0]
    assert kit["status"] == "AVAILABLE"
    resp = api_client.release_kit(kit["id"], world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_KIT_NOT_RELEASABLE.value, expected_status=409)
    assert get_kit(kit["id"])["status"] == "AVAILABLE"


def test_receive_with_out_of_range_temp_routes_to_excursion_quarantine():
    """PRD §3.3: "If it falls outside the range, the kit instead moves to
    `QUARANTINED_EXCURSION`: the receipt reading opens or extends an open
    excursion for the site exactly as §3.4 describes, the kit's
    `pre_quarantine_status` is recorded as `QUARANTINED_RECEIPT`".

    Design: Corner/endpoints/receive_with_out_of_range_temp_routes_to_excursion_quarantine
    """
    study = create_study(protocol_number="P-EP-3")
    site = create_site(study["id"])
    pharmacist = create_staff_member(site["id"], license_number="L-EP-3")
    lot = create_lot(study["id"], lot_number="LOT-EP-3")
    kit = ship_kits(lot["id"], site["id"], ["K-OR"])[0]
    resp = api_client.receive_kit(kit["id"], {"storage_temp_celsius": 9.0},
                                  make_pharmacist_headers(pharmacist["id"]))
    data = validate_success(resp)
    assert data["status"] == "QUARANTINED_EXCURSION"
    excursion_id = data["excursion_id"]
    assert excursion_id, "out-of-range receipt must link an excursion"
    excursion = get_success_data(api_client.get_temperature_excursion(excursion_id, SPONSOR))
    assert excursion["status"] == "OPEN"
    assert excursion["site_id"] == site["id"]


def _world_with_quarantined_receipt_kit_and_suspended_study():
    """Kit received in range (QUARANTINED_RECEIPT), then the study is manually
    suspended before release."""
    world = setup_pharmacy(protocol_number="P-XEN-1", kit_numbers=("K-R",),
                           pharmacist_license="L-XEN-1", activate_site=True)
    # Re-ship a fresh kit and receive it in range so it sits QUARANTINED_RECEIPT.
    kit = ship_kits(world["lot"]["id"], world["site"]["id"], ["K-R2"])[0]
    receive_kit_in_range(kit["id"], world["pharmacist"]["id"])
    transition_study(world["study"]["id"], "SUSPENDED")
    return world, kit


def test_kit_release_blocked_when_study_suspended_error():
    """PRD §3.3: "the lot's study must be `ACTIVE`, else `ERR_STUDY_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/kit_release_blocked_when_study_suspended
    """
    world, kit = _world_with_quarantined_receipt_kit_and_suspended_study()
    resp = api_client.release_kit(kit["id"], world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_STUDY_NOT_ACTIVE.value, expected_status=409)
    assert get_kit(kit["id"])["status"] == "QUARANTINED_RECEIPT"


def test_kit_release_blocked_when_study_suspended_cascades_site_on_hold():
    """PRD §3.1: "either path moves it `ACTIVE` → `SUSPENDED` and cascades every
    `ACTIVE` site of the study to `ON_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/kit_release_blocked_when_study_suspended
    """
    world, kit = _world_with_quarantined_receipt_kit_and_suspended_study()
    site = get_success_data(api_client.get_site(world["site"]["id"], SPONSOR))
    assert site["status"] == "ON_HOLD", "manual suspension must cascade ACTIVE sites to ON_HOLD"
    # The release still fails while the study is suspended.
    resp = api_client.release_kit(kit["id"], world["pharmacist_headers"])
    validate_error(resp, ApiErrorId.ERR_STUDY_NOT_ACTIVE.value, expected_status=409)
