"""Resource temporal overlap (crew half-open intervals, equipment mobilization
buffer) and compensating invariants (disposal void conserves the ledger,
release conserves the crew window) (PRD §2.5, §3.8, §3.9).

Difficulty: resource_temporal_overlap, compensating_invariant.
"""
from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    ApiErrorId,
    create_service_area,
    create_crew,
    create_equipment,
    create_work_order,
    add_tree,
    assess,
    create_estimate,
    add_line_item,
    issue_estimate,
    accept_estimate,
    current_version,
    create_booking,
    record_disposal_ticket,
    setup_scheduled_with_crew,
    TEST_USERS,
)


def _scheduled_hourly(area=None, equipment=False, equip_overrides=None):
    """A SCHEDULED HOURLY work order in a (possibly shared) area, plus the
    requested resource registered in-region. Returns (area, wo, resource)."""
    if area is None:
        area = create_service_area(disposal_fee_cents_per_ton=8000)
    if equipment:
        resource = create_equipment(area["id"], **(equip_overrides or {}))
    else:
        resource = create_crew(area["id"], name="Crew A", hourly_rate_cents=9000)
    wo = create_work_order(area["id"], pricing_mode="HOURLY")
    tree = add_tree(wo["id"], species="Maple", dbh_inches=20)
    assess(wo["id"])
    est = create_estimate(wo["id"])
    add_line_item(est["id"], service_type="REMOVAL", quantity=1, tree_asset_id=tree["id"])
    issue_estimate(wo["id"], est["id"])
    accept_estimate(wo["id"], est["id"])
    return area, wo, resource


# ─── resource_temporal_overlap / crew_half_open_overlap_adjacency_allowed ───


def test_crew_adjacent_booking_allowed_end_equals_start(api):
    """PRD §3.8: "treating each window as half-open over its `start_at` and
    `end_at`: any intersection is rejected with `ERR_CREW_DOUBLE_BOOKED`, but
    adjacency where one window's end exactly equals another's start does not
    count as an overlap and is allowed."

    Design: Difficulty/resource_temporal_overlap/crew_half_open_overlap_adjacency_allowed
    """
    area, wo, crew = _scheduled_hourly()
    create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-15T09:00:00Z", end_at="2026-07-15T12:00:00Z",
    )
    adj = api.create_booking(
        {"work_order_id": wo["id"], "resource_kind": "CREW", "crew_id": crew["id"],
         "start_at": "2026-07-15T12:00:00Z", "end_at": "2026-07-15T14:00:00Z",
         "expected_work_order_version": current_version(wo["id"])},
        TEST_USERS["dispatcher_headers"],
    )
    bk_adj = validate_success(adj, 201)
    assert bk_adj["status"] == "RESERVED"


def test_crew_interior_overlap_rejected(api):
    """PRD §3.8: "For a `CREW` booking, the new window is checked for overlap
    against every other `RESERVED` or `FINALIZED` booking of the same crew,
    treating each window as half-open over its `start_at` and `end_at`: any
    intersection is rejected with `ERR_CREW_DOUBLE_BOOKED`"

    Design: Difficulty/resource_temporal_overlap/crew_half_open_overlap_adjacency_allowed
    """
    area, wo, crew = _scheduled_hourly()
    create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-15T09:00:00Z", end_at="2026-07-15T12:00:00Z",
    )
    res = api.create_booking(
        {"work_order_id": wo["id"], "resource_kind": "CREW", "crew_id": crew["id"],
         "start_at": "2026-07-15T11:59:00Z", "end_at": "2026-07-15T12:30:00Z",
         "expected_work_order_version": current_version(wo["id"])},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(res, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)


# ─── resource_temporal_overlap / equipment_mobilization_buffer ───


def test_equipment_buffer_rejects_back_to_back_booking(api):
    """PRD §3.8: "For an `EQUIPMENT` booking, the unit's
    `mobilization_buffer_minutes` is added to both sides of each existing
    `RESERVED` or `FINALIZED` window of that same unit, and the new booking is
    rejected with `ERR_EQUIPMENT_DOUBLE_BOOKED` if it falls within that
    buffered span — so adjacency that would be legal for a crew is rejected
    for a buffered unit."

    Design: Difficulty/resource_temporal_overlap/equipment_mobilization_buffer_rejects_adjacency
    """
    area, wo, crane = _scheduled_hourly(
        equipment=True,
        equip_overrides={"kind": "CRANE", "name": "Crane-1",
                         "hourly_rate_cents": 20000, "mobilization_buffer_minutes": 30},
    )
    create_booking(
        wo["id"], "EQUIPMENT", equipment_id=crane["id"],
        start_at="2026-07-16T09:00:00Z", end_at="2026-07-16T12:00:00Z",
    )
    # end==start adjacency: 0-min gap < 30-min buffer -> rejected.
    res = api.create_booking(
        {"work_order_id": wo["id"], "resource_kind": "EQUIPMENT", "equipment_id": crane["id"],
         "start_at": "2026-07-16T12:00:00Z", "end_at": "2026-07-16T14:00:00Z",
         "expected_work_order_version": current_version(wo["id"])},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(res, ApiErrorId.ERR_EQUIPMENT_DOUBLE_BOOKED.value)


def test_crew_adjacency_allowed_but_equipment_buffer_rejected(api):
    """PRD §3.8: "adjacency that would be legal for a crew is rejected for a
    buffered unit." PRD §3.8: "adjacency where one window's end exactly equals
    another's start does not count as an overlap and is allowed."

    Design: Difficulty/resource_temporal_overlap/equipment_mobilization_buffer_rejects_adjacency
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    # Equipment leg: buffered crane rejects end==start adjacency.
    crane = create_equipment(area["id"], kind="CRANE", name="Crane-2",
                             hourly_rate_cents=20000, mobilization_buffer_minutes=30)
    wo_e = create_work_order(area["id"], pricing_mode="HOURLY")
    te = add_tree(wo_e["id"], species="Maple", dbh_inches=20)
    assess(wo_e["id"])
    ee = create_estimate(wo_e["id"])
    add_line_item(ee["id"], service_type="REMOVAL", quantity=1, tree_asset_id=te["id"])
    issue_estimate(wo_e["id"], ee["id"])
    accept_estimate(wo_e["id"], ee["id"])
    create_booking(
        wo_e["id"], "EQUIPMENT", equipment_id=crane["id"],
        start_at="2026-07-18T09:00:00Z", end_at="2026-07-18T12:00:00Z",
    )
    rej = api.create_booking(
        {"work_order_id": wo_e["id"], "resource_kind": "EQUIPMENT",
         "equipment_id": crane["id"], "start_at": "2026-07-18T12:00:00Z",
         "end_at": "2026-07-18T14:00:00Z",
         "expected_work_order_version": current_version(wo_e["id"])},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(rej, ApiErrorId.ERR_EQUIPMENT_DOUBLE_BOOKED.value)


# ─── compensating_invariant / disposal_void_conserves_disposal_ledger ───


def test_void_recorded_ticket_leaves_disposal_ledger_zero(api):
    """PRD §2.5: "Voiding a disposal ticket that was only ever recorded (never
    finalized) leaves the work order's accrued disposal cost exactly as it
    was." PRD §3.9: "voiding a never-finalized ticket leaves the accrued
    disposal cost unchanged."

    Design: Difficulty/compensating_invariant/disposal_void_conserves_disposal_ledger
    """
    area, wo, crew = _scheduled_hourly()
    ticket = record_disposal_ticket(wo["id"], debris_tons=3.5)
    voided = validate_success(
        api.void_disposal_ticket(wo["id"], ticket["id"], TEST_USERS["finance_clerk_headers"]), 200,
    )
    assert voided["status"] == "VOIDED"
    wo_after = validate_success(
        api.get_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert wo_after["disposal_cost_accrued_cents"] == 0


def test_void_after_record_does_not_accrue_then_unwind(api):
    """PRD §3.9: "the ticket starts `RECORDED` with `fee_cents` of 0." PRD
    §3.9: "voiding a never-finalized ticket leaves the accrued disposal cost
    unchanged."

    Design: Difficulty/compensating_invariant/disposal_void_conserves_disposal_ledger
    """
    area, wo, crew = _scheduled_hourly()
    wo_before = validate_success(
        api.get_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert wo_before["disposal_cost_accrued_cents"] == 0
    ticket = record_disposal_ticket(wo["id"], debris_tons=2.0)
    assert ticket["fee_cents"] == 0
    api.void_disposal_ticket(wo["id"], ticket["id"], TEST_USERS["finance_clerk_headers"])
    wo_after = validate_success(
        api.get_work_order(wo["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert wo_after["disposal_cost_accrued_cents"] == 0


# ─── compensating_invariant / release_conserves_crew_reserved_window ───


def test_release_conserves_crew_window_for_identical_rebooking(api):
    """PRD §2.5: "Releasing a reserved booking restores that resource's total
    reserved time to precisely the value it held before the booking existed"
    PRD §3.9: "release ... simply frees the resource's occupied window so it
    no longer participates in overlap checks"

    Design: Difficulty/compensating_invariant/release_conserves_crew_reserved_window
    """
    area = create_service_area(disposal_fee_cents_per_ton=8000)
    crew = create_crew(area["id"], name="Crew A", hourly_rate_cents=9000)

    w1 = create_work_order(area["id"], pricing_mode="HOURLY", site_address="22 Free St")
    t1 = add_tree(w1["id"], species="Maple", dbh_inches=20)
    assess(w1["id"])
    e1 = create_estimate(w1["id"])
    add_line_item(e1["id"], service_type="REMOVAL", quantity=1, tree_asset_id=t1["id"])
    issue_estimate(w1["id"], e1["id"])
    accept_estimate(w1["id"], e1["id"])
    bk1 = create_booking(
        w1["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-17T09:00:00Z", end_at="2026-07-17T12:00:00Z",
    )

    w2 = create_work_order(area["id"], pricing_mode="HOURLY", site_address="23 Free St")
    t2 = add_tree(w2["id"], species="Maple", dbh_inches=20)
    assess(w2["id"])
    e2 = create_estimate(w2["id"])
    add_line_item(e2["id"], service_type="REMOVAL", quantity=1, tree_asset_id=t2["id"])
    issue_estimate(w2["id"], e2["id"])
    accept_estimate(w2["id"], e2["id"])
    pre = api.create_booking(
        {"work_order_id": w2["id"], "resource_kind": "CREW", "crew_id": crew["id"],
         "start_at": "2026-07-17T09:00:00Z", "end_at": "2026-07-17T12:00:00Z",
         "expected_work_order_version": current_version(w2["id"])},
        TEST_USERS["dispatcher_headers"],
    )
    validate_error(pre, ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)

    released = validate_success(
        api.release_booking(bk1["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert released["status"] == "RELEASED"

    bk2 = validate_success(api.create_booking(
        {"work_order_id": w2["id"], "resource_kind": "CREW", "crew_id": crew["id"],
         "start_at": "2026-07-17T09:00:00Z", "end_at": "2026-07-17T12:00:00Z",
         "expected_work_order_version": current_version(w2["id"])},
        TEST_USERS["dispatcher_headers"],
    ), 201)
    assert bk2["status"] == "RESERVED"


def test_released_booking_no_longer_participates_in_overlap(api):
    """PRD §3.9: "release is permitted only on a booking still `RESERVED`
    (otherwise `ERR_BOOKING_NOT_RESERVED`) and simply frees the resource's
    occupied window so it no longer participates in overlap checks, touching
    no ledger because a reserved booking was never billed."

    Design: Difficulty/compensating_invariant/release_conserves_crew_reserved_window
    """
    area, wo, crew = _scheduled_hourly()
    bk = create_booking(
        wo["id"], "CREW", crew_id=crew["id"],
        start_at="2026-07-19T09:00:00Z", end_at="2026-07-19T12:00:00Z",
    )
    released = validate_success(
        api.release_booking(bk["id"], TEST_USERS["dispatcher_headers"]), 200,
    )
    assert released["status"] == "RELEASED"
    # An overlapping booking of the same crew now succeeds (window freed).
    rebook = validate_success(api.create_booking(
        {"work_order_id": wo["id"], "resource_kind": "CREW", "crew_id": crew["id"],
         "start_at": "2026-07-19T10:00:00Z", "end_at": "2026-07-19T11:00:00Z",
         "expected_work_order_version": current_version(wo["id"])},
        TEST_USERS["dispatcher_headers"],
    ), 201)
    assert rebook["status"] == "RESERVED"
