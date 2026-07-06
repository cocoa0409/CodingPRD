"""Material orders (pallets, capacity, placement state) and crew/phase scheduling."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, schedule_payload,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["project_manager_headers"]


# --------------------------------------------------------------------------
# Pallet aggregation
# --------------------------------------------------------------------------
def test_material_order_pallets_round_per_line_then_sum(api):
    """PRD §3.6: "Placement computes the order's pallet figures via the pallet aggregation, whose
    rounding order is pinned: round each line to whole pallets first, then sum. Only covered lines
    whose product unit is `SQFT` or `FACE_SQFT` contribute pallets; `EACH` and `LINEAR_FT` lines
    contribute none. For each covered square-foot line, the billable quantity (its `measured_quantity`
    times one plus the product's `waste_factor`) is divided by the product's `coverage_per_pallet_sqft`
    and rounded up to the next whole pallet."

    Design: Difficulty/combinatorial_formula/material_order_pallet_round_per_line_then_sum
    """
    ctx = fx.setup_pallet_material_order(api)
    data = validate_success(api.place_material_order(ctx["material_order_id"], PM))
    # ceil(130/120) + ceil(100/120) = 2 + 1 = 3 (sum-then-round would give ceil(230/120) = 2).
    assert data["total_pallets"] == 3, f"expected 3 pallets (round-per-line), got {data['total_pallets']}"


def test_material_order_total_sqft_ordered_from_whole_pallets(api):
    """PRD §3.6: "`total_pallets` is the sum of those per-line pallet counts, and
    `total_sqft_ordered` is the sum, over the same lines, of each line's whole-pallet count
    multiplied by that product's coverage per pallet. Confirming delivery advances `PLACED` to
    `DELIVERED`."

    Design: Difficulty/combinatorial_formula/material_order_pallet_round_per_line_then_sum
    """
    ctx = fx.setup_pallet_material_order(api)
    data = validate_success(api.place_material_order(ctx["material_order_id"], PM))
    assert data["total_sqft_ordered"] == 360, \
        f"expected 3 pallets * 120 = 360 sqft ordered, got {data['total_sqft_ordered']}"
    assert data["status"] == "PLACED", f"expected PLACED, got {data['status']}"


# --------------------------------------------------------------------------
# Empty-line-set boundary
# --------------------------------------------------------------------------
def test_material_order_empty_line_items_rejected(api):
    """PRD §3.6: "Creating an order with an empty `line_item_ids` array is rejected with
    `ERR_NO_ORDERABLE_ITEMS` (422); a `line_item_ids` entry that names no line item, or one belonging
    to a different project, is an `ERR_LINE_ITEM_NOT_FOUND` (404)."

    Design: Difficulty/boundary_precision_check/material_order_empty_line_set
    """
    base = fx.setup_contracted_paver_project(api, email="ee@example.com")
    resp = api.create_material_order(
        {"project_id": base["project"]["id"], "requested_delivery_date": "2026-06-10", "line_item_ids": []}, PM)
    validate_error(resp, ApiErrorId.ERR_NO_ORDERABLE_ITEMS)


def test_rejected_empty_material_order_not_created(api):
    """PRD §3.6: "Creating an order with an empty `line_item_ids` array is rejected with
    `ERR_NO_ORDERABLE_ITEMS` (422); a `line_item_ids` entry that names no line item, or one belonging
    to a different project, is an `ERR_LINE_ITEM_NOT_FOUND` (404)."

    Design: Difficulty/boundary_precision_check/material_order_empty_line_set
    """
    base = fx.setup_contracted_paver_project(api, email="ee2@example.com")
    pid = base["project"]["id"]
    api.create_material_order(
        {"project_id": pid, "requested_delivery_date": "2026-06-10", "line_item_ids": []}, PM)
    data, _meta = validate_paginated(api.list_project_material_orders(pid, PM))
    assert len(data) == 0, f"a rejected empty order must not be persisted; found {len(data)}"


# --------------------------------------------------------------------------
# Placement requires a contracted project
# --------------------------------------------------------------------------
def test_place_material_order_requires_contracted_project(api):
    """PRD §3.6: "Placing an order advances `DRAFT` to `PLACED`. Placement is allowed only while the
    project is `CONTRACTED` or `IN_PRODUCTION`, and only if fewer than two other material orders
    already in `PLACED` or `DELIVERED` share this order's region and `requested_delivery_date`."
    PRD §2.5: "The target resource must sit in a state from which the transition is legal. A generic
    violation is `ERR_INVALID_STATE` (409)."

    Design: Difficulty/cross_entity_state_dependency/material_order_place_requires_contracted_project
    """
    ctx = fx.setup_material_order_on_quoted(api)
    resp = api.place_material_order(ctx["material_order_id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_rejected_place_leaves_order_draft(api):
    """PRD §3.6: "Placing an order advances `DRAFT` to `PLACED`. Placement is allowed only while the
    project is `CONTRACTED` or `IN_PRODUCTION`, and only if fewer than two other material orders
    already in `PLACED` or `DELIVERED` share this order's region and `requested_delivery_date`."

    Design: Difficulty/cross_entity_state_dependency/material_order_place_requires_contracted_project
    """
    ctx = fx.setup_material_order_on_quoted(api)
    api.place_material_order(ctx["material_order_id"], PM)
    data = validate_success(api.get_material_order(ctx["material_order_id"], PM))
    assert data["status"] == "DRAFT", f"a rejected placement must leave the order DRAFT, got {data['status']}"


# --------------------------------------------------------------------------
# Delivery daily capacity
# --------------------------------------------------------------------------
def test_delivery_daily_capacity_third_order_rejected(api):
    """PRD §3.6: "only if fewer than two other material orders already in `PLACED` or `DELIVERED`
    share this order's region and `requested_delivery_date`; a third order for the same region and
    date is rejected with `ERR_DELIVERY_SLOT_FULL` (409)."

    Design: Difficulty/resource_temporal_overlap/delivery_daily_capacity_aggregate
    """
    ctx = fx.setup_delivery_capacity_full(api)
    resp = api.place_material_order(ctx["material_order_id"], PM)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_SLOT_FULL)


def test_rejected_third_order_stays_draft(api):
    """PRD §3.6: "only if fewer than two other material orders already in `PLACED` or `DELIVERED`
    share this order's region and `requested_delivery_date`; a third order for the same region and
    date is rejected with `ERR_DELIVERY_SLOT_FULL` (409)."

    Design: Difficulty/resource_temporal_overlap/delivery_daily_capacity_aggregate
    """
    ctx = fx.setup_delivery_capacity_full(api)
    api.place_material_order(ctx["material_order_id"], PM)
    data = validate_success(api.get_material_order(ctx["material_order_id"], PM))
    assert data["status"] == "DRAFT", f"a capacity-rejected order must stay DRAFT, got {data['status']}"


# --------------------------------------------------------------------------
# Start production requires delivered material (isolated)
# --------------------------------------------------------------------------
def test_start_production_without_delivered_material(api):
    """PRD §3.6: "A `ProjectManager` moves the project into production, advancing `CONTRACTED` to
    `IN_PRODUCTION`. This requires that at least one of the project's material orders is `DELIVERED`
    (else `ERR_MATERIAL_NOT_DELIVERED`, 409) and that at least one work phase is already `SCHEDULED`."

    Design: Corner/validations/start_production_without_delivered_material_returns_error
    """
    # A SCHEDULED phase is present so the material-delivery precondition is the only one that fails.
    ctx = fx.setup_start_production_no_material(api)
    resp = api.start_production(ctx["project_id"], PM)
    validate_error(resp, ApiErrorId.ERR_MATERIAL_NOT_DELIVERED)


# --------------------------------------------------------------------------
# Schedule date-range ordering
# --------------------------------------------------------------------------
def test_schedule_end_before_start_invalid_date_range(api):
    """PRD §3.7: "The `end_date` must be on or after the `start_date`, or the request fails with
    `ERR_INVALID_DATE_RANGE` (422)."

    Design: Corner/validations/schedule_end_before_start_returns_invalid_date_range
    """
    ctx = fx.setup_planned_phase_for_date_range(api)
    resp = api.schedule_work_phase(
        ctx["phase_id"], schedule_payload(ctx["crew_id"], start_date="2026-06-15", end_date="2026-06-10"), PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


# --------------------------------------------------------------------------
# Crew closed-interval double-booking
# --------------------------------------------------------------------------
def test_crew_closed_interval_touching_endpoints_double_booked(api):
    """PRD §3.7: "The crew must not already hold another phase in `SCHEDULED` or `IN_PROGRESS` whose
    `[start_date, end_date]` interval — treated as closed, so touching endpoints count as
    overlapping — intersects the requested interval; a clash is rejected with `ERR_CREW_DOUBLE_BOOKED`
    (409)."

    Design: Difficulty/resource_temporal_overlap/crew_closed_interval_touching_endpoint_overlap
    """
    ctx = fx.setup_crew_double_book(api)
    resp = api.schedule_work_phase(
        ctx["phase_id"], schedule_payload(ctx["crew_id"], start_date="2026-06-05", end_date="2026-06-08"), PM)
    validate_error(resp, ApiErrorId.ERR_CREW_DOUBLE_BOOKED)


def test_rejected_double_book_leaves_crew_count_at_one(api):
    """PRD §3.7: "The crew must not already hold another phase in `SCHEDULED` or `IN_PROGRESS` whose
    `[start_date, end_date]` interval — treated as closed, so touching endpoints count as
    overlapping — intersects the requested interval; a clash is rejected with `ERR_CREW_DOUBLE_BOOKED`
    (409)."

    Design: Difficulty/resource_temporal_overlap/crew_closed_interval_touching_endpoint_overlap
    """
    ctx = fx.setup_crew_double_book(api)
    api.schedule_work_phase(
        ctx["phase_id"], schedule_payload(ctx["crew_id"], start_date="2026-06-05", end_date="2026-06-08"), PM)
    crew = validate_success(api.get_crew(ctx["crew_id"], PM))
    phase = validate_success(api.get_work_phase(ctx["phase_id"], PM))
    assert crew["active_booking_count"] == 1, \
        f"a rejected schedule must not book the crew; count={crew['active_booking_count']}"
    assert phase["status"] == "PLANNED", f"rejected phase must stay PLANNED, got {phase['status']}"


# --------------------------------------------------------------------------
# WALL_BUILD schedule requires an approved permit
# --------------------------------------------------------------------------
def test_wall_build_schedule_requires_approved_permit(api):
    """PRD §3.7: "If the `phase_type` is `WALL_BUILD` and the project requires a permit, the
    project's permit must be `APPROVED`, or the request fails with `ERR_PERMIT_NOT_APPROVED` (409)."

    Design: Difficulty/cross_entity_state_dependency/wall_build_schedule_requires_permit_approved
    """
    ctx = fx.setup_wall_build_planned_permit_submitted(api)
    resp = api.schedule_work_phase(
        ctx["phase_id"], schedule_payload(ctx["crew_id"], start_date="2026-06-11", end_date="2026-06-14"), PM)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPROVED)


def test_rejected_wall_build_schedule_leaves_phase_planned_and_crew_free(api):
    """PRD §3.7: "If the `phase_type` is `WALL_BUILD` and the project requires a permit, the
    project's permit must be `APPROVED`, or the request fails with `ERR_PERMIT_NOT_APPROVED` (409)."

    Design: Difficulty/cross_entity_state_dependency/wall_build_schedule_requires_permit_approved
    """
    ctx = fx.setup_wall_build_planned_permit_submitted(api)
    api.schedule_work_phase(
        ctx["phase_id"], schedule_payload(ctx["crew_id"], start_date="2026-06-11", end_date="2026-06-14"), PM)
    phase = validate_success(api.get_work_phase(ctx["phase_id"], PM))
    crew = validate_success(api.get_crew(ctx["crew_id"], PM))
    assert phase["status"] == "PLANNED", f"rejected phase must stay PLANNED, got {phase['status']}"
    assert crew["active_booking_count"] == 0, \
        f"rejected schedule must not book the crew; count={crew['active_booking_count']}"


# --------------------------------------------------------------------------
# Permit gate (priority 8) beats crew overlap (priority 9)
# --------------------------------------------------------------------------
def test_permit_gate_precedes_crew_overlap_on_schedule(api):
    """PRD §2.5: "The first rung that fails determines the response, so a lower-priority failure
    never masks a higher-priority one."
    PRD §2.5: "8. Compliance gates. Permit and HOA approval gates apply here (detailed in §3),
    surfacing `ERR_PERMIT_NOT_APPROVED` or `ERR_HOA_NOT_APPROVED` (409)."
    PRD §2.5: "9. Temporal and capacity conflicts. Crew double-booking, delivery daily capacity, and
    date-range ordering are checked here, surfacing `ERR_CREW_DOUBLE_BOOKED` (409), ..."

    Design: Difficulty/priority_pair_validation_conflict/schedule_safety_beats_temporal
    """
    ctx = fx.setup_schedule_safety_conflict(api)
    resp = api.schedule_work_phase(
        ctx["phase_id"], schedule_payload(ctx["crew_id"], start_date="2026-06-12", end_date="2026-06-14"), PM)
    validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_APPROVED)


def test_rejected_safety_conflict_leaves_phase_planned(api):
    """PRD §2.5: "The first rung that fails determines the response, so a lower-priority failure
    never masks a higher-priority one."
    PRD §2.5: "8. Compliance gates. Permit and HOA approval gates apply here (detailed in §3),
    surfacing `ERR_PERMIT_NOT_APPROVED` or `ERR_HOA_NOT_APPROVED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/schedule_safety_beats_temporal
    """
    ctx = fx.setup_schedule_safety_conflict(api)
    api.schedule_work_phase(
        ctx["phase_id"], schedule_payload(ctx["crew_id"], start_date="2026-06-12", end_date="2026-06-14"), PM)
    phase = validate_success(api.get_work_phase(ctx["phase_id"], PM))
    assert phase["status"] == "PLANNED", f"rejected WALL_BUILD phase must stay PLANNED, got {phase['status']}"
