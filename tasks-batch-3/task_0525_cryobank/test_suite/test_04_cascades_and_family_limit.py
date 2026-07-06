"""Cascading side effects (deferral / discard) and family-limit boundary.

Queue-A (Difficulty) translations for transitive_cascade (defer depth-4, discard
depth-3) and boundary_precision_check (family-limit >= boundary on confirm).
"""
from test_helpers import (
    validate_success, TEST_USERS,
    setup_preparing_shipment,
    setup_listed_inventory, setup_recipient_with_consent,
    defer_donor_via_second_application, place_hold,
)

SO = TEST_USERS["screening_officer_headers"]
LT = TEST_USERS["lab_tech_headers"]
CO = TEST_USERS["compliance_officer_headers"]
CM = TEST_USERS["catalog_manager_headers"]


def test_donor_defer_cascade_discards_specimen_cancels_reservation_and_shipment(api):
    """PRD §3.4: "Deferring a donor's screening application ... sets the donor's
    status to DEFERRED and cascades across all of the donor's material: every
    specimen of that donor not already DISCARDED is driven to DISCARDED (carrying
    with it, per the specimen-discard side effects above, the voiding of
    HELD/CONFIRMED reservations and cancellation of their in-flight shipments)".
    PRD §3.2: "each such just-cancelled reservation that has a linked shipment in
    PREPARING or DISPATCHED drives that shipment to CANCELLED".

    Design: Difficulty/transitive_cascade/donor_defer_cascade_depth4
    """
    # Approved donor with RELEASED inventory, a CONFIRMED reservation, and a
    # PREPARING shipment.
    ctx = setup_preparing_shipment(display_code="D-7", dewar_code="T-7", vial_count=2)
    defer_donor_via_second_application(ctx["donor_id"])
    donor = validate_success(api.get_donor(ctx["donor_id"], SO))
    assert donor["status"] == "DEFERRED"
    specimen = validate_success(api.get_specimen(ctx["specimen_id"], CO))
    assert specimen["status"] == "DISCARDED"
    reservation = validate_success(api.get_vial_reservation(ctx["reservation_id"], CM))
    assert reservation["status"] == "CANCELLED"
    shipment = validate_success(api.get_shipment(ctx["shipment_id"], LT))
    assert shipment["status"] == "CANCELLED"


def test_donor_defer_sets_deferred_and_freezes_inventory(api):
    """PRD §3.4: "Deferring a donor's screening application ... sets the donor's
    status to DEFERRED and cascades across all of the donor's material: every
    specimen of that donor not already DISCARDED is driven to DISCARDED ..., and
    every DonorInventory lot of that donor has its hold_status set to FROZEN".

    Asserts the head links of the cascade chain (donor DEFERRED, inventory FROZEN).

    Design: Difficulty/transitive_cascade/donor_defer_cascade_depth4
    """
    ctx = setup_preparing_shipment(display_code="D-7b", dewar_code="T-7b", vial_count=2)
    defer_donor_via_second_application(ctx["donor_id"])
    donor = validate_success(api.get_donor(ctx["donor_id"], SO))
    assert donor["status"] == "DEFERRED"
    inv = validate_success(api.get_donor_inventory(ctx["inventory_id"], CM))
    assert inv["hold_status"] == "FROZEN"


def test_specimen_discard_cancels_confirmed_reservation_and_preparing_shipment(api):
    """PRD §3.2: "When a specimen in RELEASED is discarded, the same voiding of HELD
    and CONFIRMED reservations to CANCELLED occurs, and in addition each such
    just-cancelled reservation that has a linked shipment in PREPARING or DISPATCHED
    drives that shipment to CANCELLED".

    Here the shipment is still PREPARING (not dispatched) — the other branch of
    "PREPARING or DISPATCHED".

    Design: Difficulty/transitive_cascade/specimen_discard_cascade_depth3
    """
    ctx = setup_preparing_shipment(display_code="D-8b", dewar_code="T-8b", vial_count=2)
    validate_success(api.discard_specimen(ctx["specimen_id"], CO))
    reservation = validate_success(api.get_vial_reservation(ctx["reservation_id"], CM))
    assert reservation["status"] == "CANCELLED"
    shipment = validate_success(api.get_shipment(ctx["shipment_id"], LT))
    assert shipment["status"] == "CANCELLED"


def test_family_limit_reached_exactly_at_ge_boundary(api):
    """PRD §3.5: "The donor's is_family_limit_reached flag is true exactly when
    reported_family_count is greater than or equal to family_limit — note that
    reaching the limit exactly, not merely exceeding it, closes the donor."
    PRD §3.8: "On confirmation, the donor's reported_family_count is recomputed as
    the count of distinct recipient_id having a CONFIRMED entry for that donor, and
    the donor's is_family_limit_reached is recomputed (true when that count reaches
    or exceeds family_limit)".

    family_limit=2: one CONFIRMED family -> not reached; second distinct CONFIRMED
    family -> count 2 == 2 -> reached.

    Design: Difficulty/boundary_precision_check/family_limit_ge_boundary_on_confirm
    """
    inv = setup_listed_inventory(display_code="D-11", family_limit=2,
                                 initial_vial_count=5, dewar_code="T-11")
    donor_id = inv["donor_id"]

    def ship_and_report(fam_name, email, dewar_serial, birth_date, confirm):
        rcp = setup_recipient_with_consent(donor_id, family_name=fam_name,
                                           contact_email=email)
        cur = validate_success(api.get_donor_inventory(inv["inventory_id"], CM))
        res = place_hold(inv["inventory_id"], rcp["recipient_id"], rcp["headers"], 1,
                         cur["version"])
        validate_success(api.confirm_reservation(res["id"], CM))
        ship = validate_success(api.create_shipment({
            "reservation_id": res["id"], "clinic_address": fam_name,
            "ln2_dewar_serial": dewar_serial,
        }, LT), expected_status=201)
        validate_success(api.dispatch_shipment(ship["id"], LT))
        entry = validate_success(api.create_sibling_registry_entry({
            "donor_id": donor_id, "recipient_id": rcp["recipient_id"],
            "birth_reported_date": birth_date,
        }, rcp["headers"]), expected_status=201)
        if confirm:
            validate_success(api.confirm_sibling_registry(entry["id"], CO))
        return entry["id"]

    # Family 1 confirmed -> count 1, not reached.
    ship_and_report("Fam 1", "1@x.com", "DS-11a", "2026-06-05T00:00:00Z", confirm=True)
    donor = validate_success(api.get_donor(donor_id, SO))
    assert donor["reported_family_count"] == 1
    assert donor["is_family_limit_reached"] is False
    # Family 2 pending, then confirm -> count 2 == family_limit 2 -> reached.
    sib2 = ship_and_report("Fam 2", "2@x.com", "DS-11b", "2026-06-06T00:00:00Z",
                           confirm=False)
    validate_success(api.confirm_sibling_registry(sib2, CO))
    donor = validate_success(api.get_donor(donor_id, SO))
    assert donor["reported_family_count"] == 2
    assert donor["is_family_limit_reached"] is True, "2 >= 2 boundary reached"


def test_family_limit_not_reached_below_ge_boundary(api):
    """PRD §3.5: "The donor's is_family_limit_reached flag is true exactly when
    reported_family_count is greater than or equal to family_limit — note that
    reaching the limit exactly, not merely exceeding it, closes the donor."

    family_limit=3 with one CONFIRMED family: count 1 < 3 -> not reached (below the
    >= boundary).

    Design: Difficulty/boundary_precision_check/family_limit_ge_boundary_on_confirm
    """
    inv = setup_listed_inventory(display_code="D-11b", family_limit=3,
                                 initial_vial_count=5, dewar_code="T-11c")
    donor_id = inv["donor_id"]
    rcp = setup_recipient_with_consent(donor_id, family_name="Fam Only",
                                       contact_email="only@x.com")
    cur = validate_success(api.get_donor_inventory(inv["inventory_id"], CM))
    res = place_hold(inv["inventory_id"], rcp["recipient_id"], rcp["headers"], 1,
                     cur["version"])
    validate_success(api.confirm_reservation(res["id"], CM))
    ship = validate_success(api.create_shipment({
        "reservation_id": res["id"], "clinic_address": "Only Clinic",
        "ln2_dewar_serial": "DS-only",
    }, LT), expected_status=201)
    validate_success(api.dispatch_shipment(ship["id"], LT))
    entry = validate_success(api.create_sibling_registry_entry({
        "donor_id": donor_id, "recipient_id": rcp["recipient_id"],
        "birth_reported_date": "2026-06-05T00:00:00Z",
    }, rcp["headers"]), expected_status=201)
    validate_success(api.confirm_sibling_registry(entry["id"], CO))
    donor = validate_success(api.get_donor(donor_id, SO))
    assert donor["reported_family_count"] == 1
    assert donor["is_family_limit_reached"] is False, "1 < 3, boundary not reached"
