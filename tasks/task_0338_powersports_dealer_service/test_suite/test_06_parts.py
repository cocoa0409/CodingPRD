"""Parts inventory: the conservation invariant under reserve/release/consume,
the insufficient-stock guard, restock, and the stale-part-version OCC rule.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_part_payload, create_part_line_payload, TEST_USERS,
    create_part, setup_part_reserved_on_open_ro, setup_repair_order,
    assert_part_inventory_conserved,
)

PC = TEST_USERS["parts_clerk_headers"]
SA = TEST_USERS["service_advisor_headers"]


def test_reserve_then_release_conserves_on_hand(api):
    """PRD 3.9: "Releasing a reserved line directly is permitted to a PartsClerk or
    ServiceAdvisor only while the parent order's billing_status is UNBILLED ...
    releasing moves the line to RELEASED, decreases the part's reserved_qty by the
    quantity, and increases available_qty by the quantity."

    Design: Difficulty/compensating_invariant/part_inventory_reserve_then_release_conserves_on_hand
    """
    ro, part, pl = setup_part_reserved_on_open_ro(on_hand_qty=10, reserve_qty=4)
    assert part["reserved_qty"] == 4
    assert part["available_qty"] == 6
    released = validate_success(api.release_part_line(pl["id"], PC), 200)
    assert released["status"] == "RELEASED"
    part_after = validate_success(api.get_part(part["id"], PC), 200)
    assert part_after["available_qty"] == 10
    assert part_after["reserved_qty"] == 0
    assert part_after["consumed_qty"] == 0


def test_release_restores_conservation_invariant(api):
    """PRD 2.9: "For any Part, the quantity on hand always equals the quantity
    available plus the quantity reserved plus the quantity consumed."

    Design: Difficulty/compensating_invariant/part_inventory_reserve_then_release_conserves_on_hand
    """
    ro, part, pl = setup_part_reserved_on_open_ro(on_hand_qty=10, reserve_qty=4)
    validate_success(api.release_part_line(pl["id"], PC), 200)
    part_after = validate_success(api.get_part(part["id"], PC), 200)
    assert_part_inventory_conserved(part_after)
    assert part_after["on_hand_qty"] == 10


def test_complete_consumes_reserved_parts(api):
    """PRD 3.6: "Completing work advances IN_PROGRESS to WORK_COMPLETE; on
    completion the platform finalizes ... and consumes every reserved part line on
    the order — each such PartLine moves from RESERVED to CONSUMED, and for its Part
    the reserved_qty is decreased by the line quantity while consumed_qty is
    increased by the same quantity, preserving conservation."

    Design: Corner/state_machines/ro_complete_consumes_reserved_parts_cascade
    """
    # Build an RO with a service line, reserve 4 of a 10-on-hand part, then complete.
    cust, unit, tech, ro, lines = setup_repair_order(
        flat_rate_hours_list=[1.0], authorized_amount_cents=90_000)
    part = create_part(unit_price_cents=4500, on_hand_qty=10)
    validate_success(api.create_part_line(
        create_part_line_payload(ro["id"], part["id"], 4, part["version"]), PC), 201)
    validate_success(api.start_repair_order(ro["id"], SA), 200)
    completed = validate_success(api.complete_repair_order(ro["id"], SA), 200)
    part_after = validate_success(api.get_part(part["id"], PC), 200)
    assert part_after["consumed_qty"] == 4
    assert part_after["reserved_qty"] == 0
    assert part_after["available_qty"] == 6
    assert completed["parts_total_cents"] == 18000


def test_reservation_exceeding_available_rejected(api):
    """PRD 3.9: "The requested quantity must not exceed the part's available_qty; an
    over-reservation is rejected with ERR_PART_INSUFFICIENT_STOCK."

    Design: Corner/validations/part_reservation_exceeds_available_rejected
    """
    cust, unit, tech, ro, lines = setup_repair_order(
        flat_rate_hours_list=[], authorized_amount_cents=90_000)
    part = create_part(unit_price_cents=3000, on_hand_qty=5)
    res = api.create_part_line(
        create_part_line_payload(ro["id"], part["id"], 6, part["version"]), PC)
    validate_error(res, "ERR_PART_INSUFFICIENT_STOCK")


def test_stale_part_version_on_reservation_rejected(api):
    """PRD 2.6: "If that value does not equal the part's current version — because
    another writer has already reserved or restocked the part, leaving the client's
    view of availability stale — the request is rejected with ERR_STALE_PART_VERSION
    (HTTP 412), and no reservation is created."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_part_version_on_part_line_rejected
    """
    cust, unit, tech, ro, lines = setup_repair_order(
        flat_rate_hours_list=[], authorized_amount_cents=90_000)
    part = create_part(unit_price_cents=3000, on_hand_qty=10)
    stale_v = part["version"]
    validate_success(api.create_part_line(
        create_part_line_payload(ro["id"], part["id"], 2, stale_v), PC), 201)
    res = api.create_part_line(
        create_part_line_payload(ro["id"], part["id"], 2, stale_v), PC)
    validate_error(res, "ERR_STALE_PART_VERSION")
    part_after = validate_success(api.get_part(part["id"], PC), 200)
    assert part_after["reserved_qty"] == 2


def test_part_create_initializes_computed_inventory_fields(api):
    """PRD 3.9: "On creation reserved_qty and consumed_qty are zero and
    available_qty equals on_hand_qty."

    Design: Corner/entities/part_create_initializes_computed_inventory_fields
    """
    part = validate_success(api.create_part(
        create_part_payload(unit_price_cents=800, on_hand_qty=12), PC), 201)
    assert part["available_qty"] == 12
    assert part["reserved_qty"] == 0
    assert part["consumed_qty"] == 0


def test_restock_increments_on_hand_and_version(api):
    """PRD 3.9: "Restocking a part — increasing its on_hand_qty — is done by
    submitting an add_qty; restocking increases both on_hand_qty and available_qty
    by that amount and increments the part's version."

    Design: Corner/endpoints/restock_increments_on_hand_and_version
    """
    part = validate_success(api.create_part(
        create_part_payload(unit_price_cents=2000, on_hand_qty=3), PC), 201)
    assert part["version"] == 1
    restocked = validate_success(api.restock_part(part["id"], {"add_qty": 5}, PC), 200)
    assert restocked["on_hand_qty"] == 8
    assert restocked["available_qty"] == 8
    assert restocked["version"] == 2
