"""Landowners, seed zones, seed lots, and the quarantine/release cycle."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    is_valid_uuid, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_landowner, create_seed_zone, create_seed_lot, create_crop_batch,
    sow_batch, setup_graded_batch,
    create_seed_zone_payload,
)

NM = TEST_USERS["nursery_manager_headers"]
CO = TEST_USERS["contract_officer_headers"]


def test_landowner_create_defaults_applied(api, contract_officer_headers):
    """PRD §3.1: "The `cost_share_eligible` flag records whether the landowner
    may enroll in cost-share programs and defaults to true when omitted."

    Design: Corner/entities/landowner_create_defaults_applied
    """
    res = api.create_landowner(
        {"legal_name": "Owner A", "contact_email": "a@x.com", "tax_id": "T-A"}, CO
    )
    created = validate_success(res, 201)
    assert created["cost_share_eligible"] is True, (
        f"omitted cost_share_eligible must default to true, got {created['cost_share_eligible']!r}"
    )

    read = validate_success(api.get_landowner(created["id"], CO), 200)
    assert read["legal_name"] == "Owner A"
    assert read["id"] == created["id"]


def test_seed_zone_band_midpoint_computed(api):
    """PRD §3.1: "From the two bounds the server derives `band_midpoint_ft`, the
    arithmetic midpoint of the band." and "the lower bound must be at least zero
    and strictly below the upper bound — an unordered pair is rejected with
    `ERR_WINDOW_INVERTED`"

    Design: Corner/entities/seed_zone_band_midpoint_computed
    """
    zone = create_seed_zone(zone_min=1000, zone_max=2000)
    assert zone["band_midpoint_ft"] == 1500, (
        f"midpoint of [1000, 2000] must be 1500, got {zone['band_midpoint_ft']!r}"
    )

    res = api.create_seed_zone(
        create_seed_zone_payload(zone_code="Z-2", min_elevation_ft=3000, max_elevation_ft=2000),
        NM,
    )
    validate_error(res, ApiErrorId.ERR_WINDOW_INVERTED)


def test_seed_lot_remaining_grams_reconciles_after_sow(api):
    """PRD §3.1: "The server maintains `remaining_grams` as the lot's original
    mass less the sown grams of every crop batch of that lot, whatever status
    those batches are in."

    Design: Corner/entities/seed_lot_remaining_grams_reconciles_after_sow
    """
    zone = create_seed_zone()
    lot = create_seed_lot(zone["id"], quantity_grams=500, germination_pct=0.85)
    batch = create_crop_batch(lot["id"], lot["version"])
    sow_batch(batch["id"], 300)

    lot_after = get_success_data(api.get_seed_lot(lot["id"], NM))
    assert lot_after["remaining_grams"] == 200, (
        f"500 g lot less a 300 g sow must leave 200, got {lot_after['remaining_grams']}"
    )


def test_entity_not_found_returns_404(api, contract_officer_headers):
    """PRD §2.6: "Existence: path parameters and body references resolve to
    existing resources, validated left to right — otherwise `ERR_NOT_FOUND`
    (404)."

    Design: Corner/entities/entity_not_found_returns_404
    """
    res = api.get_crew("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", CO)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_order_with_bogus_zone_fk_returns_404(api):
    """PRD §2.6: "Existence: path parameters and body references resolve to
    existing resources, validated left to right — otherwise `ERR_NOT_FOUND`
    (404)."

    Design: Corner/entities/order_with_bogus_zone_fk_returns_404
    """
    from test_helpers import make_landowner_headers
    lo = create_landowner(legal_name="Owner F", contact_email="f@x.com", tax_id="T-F")
    res = api.create_seedling_order(
        {
            "landowner_id": lo["id"],
            "destination_zone_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
            "species": "DOUGLAS_FIR",
            "quantity": 100,
            "requested_ship_date": "2027-04-05",
        },
        make_landowner_headers(lo["id"]),
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_lot_depleted_auto_transition_on_full_sow(api):
    """PRD §3.1: "whenever a successful sow debit brings `remaining_grams` to
    exactly zero, the lot moves automatically to `DEPLETED`, its terminal
    state." and PRD §3.2: "Recording the sow moves the batch from `PLANNED` to
    `SOWN` and requires the lot to be `AVAILABLE`"

    Design: Corner/state_machines/lot_depleted_auto_transition_on_full_sow
    """
    zone = create_seed_zone()
    lot = create_seed_lot(zone["id"], quantity_grams=500, germination_pct=0.85)
    b1 = create_crop_batch(lot["id"], lot["version"])
    sow_batch(b1["id"], 500)

    lot_after = get_success_data(api.get_seed_lot(lot["id"], NM))
    assert lot_after["status"] == "DEPLETED", (
        f"lot must auto-transition to DEPLETED at remaining_grams 0, got {lot_after['status']}"
    )
    assert lot_after["remaining_grams"] == 0

    b2 = create_crop_batch(lot["id"], lot_after["version"])
    res = api.sow_crop_batch(
        b2["id"], {"actual_sow_date": "2026-09-02", "sown_grams": 1}, NM
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_sow_rejected_while_lot_quarantined(api):
    """PRD §3.1: "while a lot is `QUARANTINED`, every attempt to sow against it,
    to allocate stock grown from it, or to ship that stock is rejected with
    `ERR_LOT_QUARANTINED`."

    Design: Difficulty/non_linear_state_machine/seed_lot_quarantine_release_cycle
    """
    zone = create_seed_zone()
    lot = create_seed_lot(zone["id"], quantity_grams=500, germination_pct=0.85)
    quarantined = get_success_data(api.quarantine_seed_lot(lot["id"], NM))
    assert quarantined["status"] == "QUARANTINED"

    batch = create_crop_batch(lot["id"], quarantined["version"])
    res = api.sow_crop_batch(
        batch["id"], {"actual_sow_date": "2026-09-01", "sown_grams": 300}, NM
    )
    validate_error(res, ApiErrorId.ERR_LOT_QUARANTINED)


def test_quarantine_release_cycle_recomputes_projection(api):
    """PRD §3.1: "Release from quarantine requires a passing retest: the release
    carries `retest_germination_pct`, which must be greater than zero and at
    most one, overwrites the lot's `germination_pct`, and recomputes
    `projected_plantable` on every crop batch of the lot still in `PLANNED`. The
    quarantine-and-release cycle may repeat without limit, and each quarantine
    and each release advances the lot's `version`." and PRD §3.2: "the
    whole-number floor of `sown_grams` multiplied by the seeds-per-gram figure
    for the lot's species — 88 for `DOUGLAS_FIR`, 55 for `LOBLOLLY_PINE`, and
    two-tenths of a seed per gram for `WHITE_OAK` — multiplied by the lot's
    current `germination_pct`, and finally multiplied by 0.88 to allow for the
    expected cull rate of twelve percent."

    Design: Difficulty/non_linear_state_machine/seed_lot_quarantine_release_cycle
    """
    zone = create_seed_zone()
    lot = create_seed_lot(zone["id"], quantity_grams=500, germination_pct=0.85)

    # First quarantine blocks a sow; release overwrites germination with 0.90.
    quarantined = get_success_data(api.quarantine_seed_lot(lot["id"], NM))
    batch = create_crop_batch(lot["id"], quarantined["version"])
    err_res = api.sow_crop_batch(
        batch["id"], {"actual_sow_date": "2026-09-01", "sown_grams": 300}, NM
    )
    validate_error(err_res, ApiErrorId.ERR_LOT_QUARANTINED)

    released = get_success_data(
        api.release_seed_lot(lot["id"], {"retest_germination_pct": 0.9}, NM)
    )
    assert released["germination_pct"] == 0.9, (
        f"retest germination must overwrite the lot figure, got {released['germination_pct']}"
    )

    # Second loop traversal is unrestricted.
    q2 = get_success_data(api.quarantine_seed_lot(lot["id"], NM))
    assert q2["status"] == "QUARANTINED"
    r2 = get_success_data(api.release_seed_lot(lot["id"], {"retest_germination_pct": 0.9}, NM))
    assert r2["status"] == "AVAILABLE"

    sown = sow_batch(batch["id"], 300)
    assert sown["projected_plantable"] == 20908, (
        "projection must use the retest germination: "
        f"floor(300 * 88 * 0.9 * 0.88) = 20908, got {sown['projected_plantable']}"
    )
