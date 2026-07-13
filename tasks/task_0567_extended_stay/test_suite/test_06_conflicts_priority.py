"""Validation precedence and cross-entity state guards: state-before-referential on
check-in, unit-conflict-before-capacity on booking, unit-available-at-check-in,
housekeeping-requires-active-stay, and employee double-booking geometry."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    checkin_retail_stay, book_retail_stay, setup_corporate_stay,
    create_rate_plan, create_unit, create_stay_payload,
    create_housekeeping_visit_payload, TEST_USERS,
)

PM = TEST_USERS["property_manager_headers"]


# --- State (generic) beats referential (business) on re-check-in ---

def test_recheckin_active_stay_returns_invalid_state(api):
    """PRD §3.4: "A stay that is not `RESERVED` yields `ERR_INVALID_STATE`; a unit
    that is not `AVAILABLE` at this moment yields `ERR_UNIT_NOT_AVAILABLE`"
    PRD §2.8: "6. State: the target resource is in a state that admits the requested
    transition, else `ERR_INVALID_STATE` (409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_checkin
    """
    ctx = checkin_retail_stay(api, deposit_held_cents=0)  # ACTIVE, unit OCCUPIED
    resp = api.check_in_stay(ctx["stay"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_recheckin_leaves_active_stay_unchanged(api):
    """PRD §2.8: "Business-specific checks (unit availability, master-lease status,
    stay status, temporal conflicts, date sanity, minimum term, capacity, deposit
    sufficiency, and optimistic concurrency) follow the six generic checks above"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_referential_on_checkin
    """
    ctx = checkin_retail_stay(api, deposit_held_cents=0)
    resp = api.check_in_stay(ctx["stay"]["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    stay = validate_success(api.get_stay(ctx["stay"]["id"], PM))
    assert stay["status"] == "ACTIVE"


# --- Unit occupancy conflict beats master-lease capacity on booking ---

def test_overlap_and_over_capacity_booking_returns_unit_conflict(api):
    """PRD §2.8: "Their relative priority, where two can apply to the same request,
    is: unit availability at check-in first, then master-lease-active, then
    stay-active, then the unit occupancy conflict, then employee double-booking,
    then date sanity, then minimum term, then master-lease capacity, then
    deposit-overdraw, and finally the renegotiation stale-version check."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_booking
    """
    ctx = setup_corporate_stay(api, committed_units=1)  # s1 [05-01,06-30) consumes the 1 unit
    admin = ctx["admin_headers"]
    resp = api.create_stay(create_stay_payload(
        ctx["unit"]["id"], ctx["rate_plan"]["id"],
        move_in="2026-06-01T00:00:00Z", planned_move_out="2026-07-31T00:00:00Z",
        deposit_held_cents=0, master_lease_id=ctx["lease"]["id"],
        employee_id=ctx["employee"]["id"]), admin)
    validate_error(resp, ApiErrorId.ERR_UNIT_TIME_CONFLICT.value)


def test_rejected_over_capacity_overlap_does_not_consume_unit(api):
    """PRD §3.3: "Two windows that overlap, and two windows that merely touch
    end-to-start (the new stay beginning on the very day a prior stay ends), are
    both rejected with `ERR_UNIT_TIME_CONFLICT`: for a unit, adjacency is forbidden
    and at least one full day of separation is required."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_booking
    """
    ctx = setup_corporate_stay(api, committed_units=1)
    admin = ctx["admin_headers"]
    resp = api.create_stay(create_stay_payload(
        ctx["unit"]["id"], ctx["rate_plan"]["id"],
        move_in="2026-06-01T00:00:00Z", planned_move_out="2026-07-31T00:00:00Z",
        deposit_held_cents=0, master_lease_id=ctx["lease"]["id"],
        employee_id=ctx["employee"]["id"]), admin)
    validate_error(resp, ApiErrorId.ERR_UNIT_TIME_CONFLICT.value)
    lease = validate_success(api.get_master_lease(ctx["lease"]["id"], PM))
    assert lease["units_consumed"] == 1  # only the original s1 still counts


# --- Check-in requires the unit AVAILABLE (cross-entity) ---

def _setup_occupied_unit_with_pending_second_stay(api):
    rate_plan = create_rate_plan(api)
    unit = create_unit(api)
    s1 = validate_success(api.create_stay(create_stay_payload(
        unit["id"], rate_plan["id"], move_in="2026-05-01T00:00:00Z",
        planned_move_out="2026-06-30T00:00:00Z", deposit_held_cents=0), PM),
        expected_status=201)
    validate_success(api.check_in_stay(s1["id"], PM))  # unit now OCCUPIED
    s2 = validate_success(api.create_stay(create_stay_payload(
        unit["id"], rate_plan["id"], move_in="2026-08-01T00:00:00Z",
        planned_move_out="2026-09-30T00:00:00Z", deposit_held_cents=0), PM),
        expected_status=201)
    return unit, s2


def test_checkin_on_occupied_unit_returns_unit_not_available(api):
    """PRD §3.4: "It is admissible only when the stay is `RESERVED`, the referenced
    unit is currently `AVAILABLE`, and — if the stay carries a `master_lease_id` —
    that lease is `ACTIVE`."
    PRD §3.4: "a unit that is not `AVAILABLE` at this moment yields
    `ERR_UNIT_NOT_AVAILABLE`"

    Design: Difficulty/cross_entity_state_dependency/stay_checkin_requires_unit_available
    """
    _unit, s2 = _setup_occupied_unit_with_pending_second_stay(api)
    resp = api.check_in_stay(s2["id"], PM)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)


def test_rejected_checkin_leaves_second_stay_reserved(api):
    """PRD §3.4: "Checking in is a `PropertyManager` action that activates a reserved
    stay. It is admissible only when the stay is `RESERVED`, the referenced unit is
    currently `AVAILABLE`, and — if the stay carries a `master_lease_id` — that lease
    is `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/stay_checkin_requires_unit_available
    """
    _unit, s2 = _setup_occupied_unit_with_pending_second_stay(api)
    resp = api.check_in_stay(s2["id"], PM)
    validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)
    fetched = validate_success(api.get_stay(s2["id"], PM))
    assert fetched["status"] == "RESERVED"


# --- Housekeeping requires an ACTIVE stay ---

def test_housekeeping_against_reserved_stay_rejected(api):
    """PRD §3.5: "A visit may be scheduled only while its stay is `ACTIVE`;
    scheduling against a stay in any other status is rejected with
    `ERR_STAY_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/housekeeping_requires_active_stay
    """
    ctx = book_retail_stay(api, deposit_held_cents=0)  # RESERVED, never checked in
    resp = api.create_housekeeping_visit(
        create_housekeeping_visit_payload(ctx["stay"]["id"],
                                          scheduled_date="2026-05-10T00:00:00Z"), PM)
    validate_error(resp, ApiErrorId.ERR_STAY_NOT_ACTIVE.value)


def test_rejected_housekeeping_creates_no_visit(api):
    """PRD §3.5: "A visit may be scheduled only while its stay is `ACTIVE`;
    scheduling against a stay in any other status is rejected with
    `ERR_STAY_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/housekeeping_requires_active_stay
    """
    ctx = book_retail_stay(api, deposit_held_cents=0)
    resp = api.create_housekeeping_visit(
        create_housekeeping_visit_payload(ctx["stay"]["id"],
                                          scheduled_date="2026-05-10T00:00:00Z"), PM)
    validate_error(resp, ApiErrorId.ERR_STAY_NOT_ACTIVE.value)
    listing = api.list_housekeeping_visits(PM, params={"stay_id": ctx["stay"]["id"]})
    assert listing.json()["data"] == []


# --- Employee double-booking: overlap forbidden, adjacency allowed ---

def test_employee_overlapping_stay_rejected(api):
    """PRD §3.3: "When an `employee_id` is supplied, the new half-open window
    `[move_in, planned_move_out)` must not overlap any non-cancelled stay of the
    same employee. Unlike the unit rule, adjacency is allowed here and no buffer is
    imposed: two of the employee's windows that merely touch end-to-start are
    permitted, but any true overlap is rejected with `ERR_EMPLOYEE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/employee_overlap_no_buffer_adjacency_allowed
    """
    ctx = setup_corporate_stay(api, committed_units=10)  # s1 on u1 [05-01,06-30)
    u2 = create_unit(api, name="U2", property_name="Oak Ridge")
    resp = api.create_stay(create_stay_payload(
        u2["id"], ctx["rate_plan"]["id"], move_in="2026-06-15T00:00:00Z",
        planned_move_out="2026-08-14T00:00:00Z", deposit_held_cents=0,
        master_lease_id=ctx["lease"]["id"], employee_id=ctx["employee"]["id"]),
        ctx["admin_headers"])
    validate_error(resp, ApiErrorId.ERR_EMPLOYEE_DOUBLE_BOOKED.value)


def test_employee_adjacent_stay_accepted(api):
    """PRD §3.3: "Unlike the unit rule, adjacency is allowed here and no buffer is
    imposed: two of the employee's windows that merely touch end-to-start are
    permitted, but any true overlap is rejected with `ERR_EMPLOYEE_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/employee_overlap_no_buffer_adjacency_allowed
    """
    ctx = setup_corporate_stay(api, committed_units=10)  # s1 on u1 [05-01,06-30)
    u2 = create_unit(api, name="U2", property_name="Oak Ridge")
    created = validate_success(api.create_stay(create_stay_payload(
        u2["id"], ctx["rate_plan"]["id"], move_in="2026-06-30T00:00:00Z",
        planned_move_out="2026-08-29T00:00:00Z", deposit_held_cents=0,
        master_lease_id=ctx["lease"]["id"], employee_id=ctx["employee"]["id"]),
        ctx["admin_headers"]), expected_status=201)
    fetched = validate_success(api.get_stay(created["id"], PM))
    assert fetched["status"] == "RESERVED"
