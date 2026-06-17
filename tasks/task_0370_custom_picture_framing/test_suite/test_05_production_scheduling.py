"""Production scheduling: workbench interval overlap, fragile bench requirement,
cross-entity preconditions, validation-priority pairs, the glass-buffer boundary,
and the workbench free-interval conservation invariant.

Translates queue A (Difficulty) priority_pair_validation_conflict (both),
boundary_precision_check (glass-buffer instance), cross_entity_state_dependency
(both), resource_temporal_overlap (both), and compensating_invariant
(task-release instance); plus queue B (Corner) validations fragile instance.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_customer, create_order, add_line, measure_line, quote, pay,
    create_workbench,
    setup_quoted_order, setup_deposit_paid_order, setup_in_production_order,
    setup_fragile_in_production_order,
)

DESIGNER = TEST_USERS["frame_designer_headers"]
TECH = TEST_USERS["frame_production_tech_headers"]
CLERK = TEST_USERS["front_desk_clerk_headers"]


def _schedule(api, order_id, bench_id, start, end):
    return api.create_task(
        {"order_id": order_id, "workbench_id": bench_id, "start_minute": start, "end_minute": end}, TECH)


# ===========================================================================
# Difficulty: resource_temporal_overlap / assembly_bench_half_open_overlap_rejected
# ===========================================================================
def test_assembly_bench_half_open_overlap_rejected(api):
    """PRD §3.6: "On an assembly bench, the new half-open interval may not overlap any
    existing task's half-open interval on the bench. ... Either form of collision is
    rejected with `ERR_WORKBENCH_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/assembly_bench_half_open_overlap_rejected
    """
    cust, order, line = setup_in_production_order(deposit_pct=0.30, measure_dims=(8, 10))
    bench = create_workbench(bench_type="ASSEMBLY", bench_name="Asm O")
    get_success_data(_schedule(api, order["id"], bench["id"], 0, 60))
    resp = _schedule(api, order["id"], bench["id"], 30, 90)  # overlaps [0,60)
    validate_error(resp, ApiErrorId.ERR_WORKBENCH_CONFLICT)


def test_assembly_bench_adjacent_interval_accepted(api):
    """PRD §3.6: "The interval is half-open, covering `start_minute` up to but not
    including `end_minute`." ... "On an assembly bench, the new half-open interval may
    not overlap any existing task's half-open interval on the bench."

    Second test for the assembly-overlap instance: an adjacent [60,120) task does NOT
    overlap [0,60) under half-open semantics and is accepted.

    Design: Difficulty/resource_temporal_overlap/assembly_bench_half_open_overlap_rejected
    """
    cust, order, line = setup_in_production_order(deposit_pct=0.30, measure_dims=(8, 10))
    bench = create_workbench(bench_type="ASSEMBLY", bench_name="Asm Adj")
    get_success_data(_schedule(api, order["id"], bench["id"], 0, 60))
    adj = validate_success(_schedule(api, order["id"], bench["id"], 60, 120), expected_status=201)
    assert adj["task_status"] == "SCHEDULED"
    assert adj["start_minute"] == 60


# ===========================================================================
# Difficulty: resource_temporal_overlap / glass_bench_buffer_padded_adjacency_rejected
# ===========================================================================
def test_glass_bench_buffer_padded_adjacency_rejected(api):
    """PRD §3.6: "On a glass-cutting bench the rule is stricter: the gap between the
    new interval and every neighboring task on the bench must be at least the bench's
    `clean_buffer_minutes`, so two jobs that merely abut, or sit closer than the
    buffer, conflict. Either form of collision is rejected with `ERR_WORKBENCH_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/glass_bench_buffer_padded_adjacency_rejected
    """
    cust, order, line = setup_fragile_in_production_order()
    bench = create_workbench(bench_type="GLASS_CUTTING", clean_buffer_minutes=30, bench_name="Glass P")
    get_success_data(_schedule(api, order["id"], bench["id"], 0, 60))
    # Adjacent [60,120): gap 0 < buffer 30 -> conflict.
    resp = _schedule(api, order["id"], bench["id"], 60, 120)
    validate_error(resp, ApiErrorId.ERR_WORKBENCH_CONFLICT)


def test_glass_bench_gap_below_buffer_rejected(api):
    """PRD §3.6: "the gap between the new interval and every neighboring task on the
    bench must be at least the bench's `clean_buffer_minutes`, so two jobs that merely
    abut, or sit closer than the buffer, conflict."

    Second test for the glass-buffer-adjacency instance: a positive gap that is still
    below the buffer (gap 15 < 30) conflicts.

    Design: Difficulty/resource_temporal_overlap/glass_bench_buffer_padded_adjacency_rejected
    """
    cust, order, line = setup_fragile_in_production_order()
    bench = create_workbench(bench_type="GLASS_CUTTING", clean_buffer_minutes=30, bench_name="Glass G")
    get_success_data(_schedule(api, order["id"], bench["id"], 0, 60))
    resp = _schedule(api, order["id"], bench["id"], 75, 120)  # gap 15 < 30
    validate_error(resp, ApiErrorId.ERR_WORKBENCH_CONFLICT)


# ===========================================================================
# Difficulty: boundary_precision_check / glass_bench_buffer_gap_exactly_equals_buffer_is_allowed
# ===========================================================================
def test_glass_bench_buffer_gap_exactly_equals_buffer_is_allowed(api):
    """PRD §3.6: "the gap between the new interval and every neighboring task on the
    bench must be at least the bench's `clean_buffer_minutes`".

    Boundary: gap exactly 30 == buffer 30 satisfies the at-least rule.

    Design: Difficulty/boundary_precision_check/glass_bench_buffer_gap_exactly_equals_buffer_is_allowed
    """
    cust, order, line = setup_fragile_in_production_order()
    bench = create_workbench(bench_type="GLASS_CUTTING", clean_buffer_minutes=30, bench_name="Glass B")
    get_success_data(_schedule(api, order["id"], bench["id"], 0, 60))
    # New task [90,150): gap from [0,60) is 30 == buffer -> allowed.
    accepted = validate_success(_schedule(api, order["id"], bench["id"], 90, 150), expected_status=201)
    assert accepted["task_status"] == "SCHEDULED"
    assert accepted["start_minute"] == 90


def test_glass_bench_buffer_gap_one_above_buffer_allowed(api):
    """PRD §3.6: "the gap between the new interval and every neighboring task on the
    bench must be at least the bench's `clean_buffer_minutes`".

    Second test (boundary X+1): a gap of 31 (> buffer 30) is comfortably allowed.

    Design: Difficulty/boundary_precision_check/glass_bench_buffer_gap_exactly_equals_buffer_is_allowed
    """
    cust, order, line = setup_fragile_in_production_order()
    bench = create_workbench(bench_type="GLASS_CUTTING", clean_buffer_minutes=30, bench_name="Glass B2")
    get_success_data(_schedule(api, order["id"], bench["id"], 0, 60))
    accepted = validate_success(_schedule(api, order["id"], bench["id"], 91, 150), expected_status=201)
    assert accepted["task_status"] == "SCHEDULED"
    assert accepted["start_minute"] == 91


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / state_beats_fiscal_on_pickup
# ===========================================================================
def test_state_beats_fiscal_on_pickup_of_unready_unpaid_order(api):
    """PRD §2.6: "sixth, the target resource's state being valid for the requested
    transition ... and tenth and eleventh, the fiscal checks on deposits, balances,
    and pickup (the 402 family). A lower-priority check is never reported while a
    higher-priority one is failing."
    PRD §3.7: "Pickup ... advances `production_status` from `READY` to `PICKED_UP`."

    A pickup on a QUOTED (not READY), unpaid order fails the state check before the
    fiscal check, so ERR_INVALID_STATE (priority 6) wins over ERR_BALANCE_OUTSTANDING.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pickup_of_unready_unpaid_order
    """
    cust, quoted, line = setup_quoted_order(deposit_pct=0.30, measure_dims=(8, 10))
    resp = api.pickup_order(quoted["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_state_beats_fiscal_on_pickup_from_intake(api):
    """PRD §2.6: "A lower-priority check is never reported while a higher-priority one
    is failing."
    PRD §3.7: "Pickup ... advances `production_status` from `READY` to `PICKED_UP`."

    Second test for the state-vs-fiscal pair: pickup from INTAKE (also unpaid) still
    reports the state-family error, never the fiscal one.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_pickup_of_unready_unpaid_order
    """
    cust = create_customer()
    order = create_order(cust["id"], deposit_pct=0.30)  # INTAKE, unpaid
    resp = api.pickup_order(order["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / fragile_safety_beats_temporal_overlap
# ===========================================================================
def test_fragile_safety_beats_temporal_overlap_on_task_schedule(api):
    """PRD §3.6: "Scheduling runs two gating checks in order. First, fragile handling:
    if the order has a fragile line, the chosen workbench must be of type
    `GLASS_CUTTING`; choosing any other bench for a fragile order is rejected with
    `ERR_FRAGILE_REQUIRES_GLASS_BENCH`. Second, interval availability against the other
    `SCHEDULED` or `COMPLETED` tasks already on that same bench."

    A fragile order onto an occupied ASSEMBLY bench violates both; the fragile (first)
    check wins.

    Design: Difficulty/priority_pair_validation_conflict/fragile_safety_beats_temporal_overlap_on_task_schedule
    """
    # Occupy an assembly bench with a non-fragile order's task on [0,60).
    cust_a, other_order, ol = setup_in_production_order(deposit_pct=0.50, measure_dims=(8, 10))
    asm = create_workbench(bench_type="ASSEMBLY", bench_name="Asm S")
    get_success_data(_schedule(api, other_order["id"], asm["id"], 0, 60))
    # Fragile order requests an overlapping [30,90) on that same assembly bench.
    cust_f, frag_order, fl = setup_fragile_in_production_order()
    resp = _schedule(api, frag_order["id"], asm["id"], 30, 90)
    validate_error(resp, ApiErrorId.ERR_FRAGILE_REQUIRES_GLASS_BENCH)


def test_fragile_safety_reported_on_empty_assembly_bench(api):
    """PRD §3.6: "First, fragile handling: if the order has a fragile line, the chosen
    workbench must be of type `GLASS_CUTTING`; choosing any other bench for a fragile
    order is rejected with `ERR_FRAGILE_REQUIRES_GLASS_BENCH`."

    Second test for the safety-vs-temporal pair: with NO temporal conflict (empty
    bench), the fragile safety error still fires, confirming it is a standalone
    higher-priority gate.

    Design: Difficulty/priority_pair_validation_conflict/fragile_safety_beats_temporal_overlap_on_task_schedule
    """
    cust_f, frag_order, fl = setup_fragile_in_production_order()
    asm = create_workbench(bench_type="ASSEMBLY", bench_name="Asm Empty")
    resp = _schedule(api, frag_order["id"], asm["id"], 0, 60)
    validate_error(resp, ApiErrorId.ERR_FRAGILE_REQUIRES_GLASS_BENCH)


# ===========================================================================
# Difficulty: cross_entity_state_dependency / start_production_blocked_unless_all_lines_measured
# ===========================================================================
def test_start_production_blocked_unless_all_lines_measured(api):
    """PRD §3.6: "An order moves from `QUOTED` to `IN_PRODUCTION` only when ... every
    non-voided frame line has `line_status` of `MEASURED`, with any unmeasured
    non-voided line causing rejection with `ERR_LINES_NOT_MEASURED`."

    Design: Difficulty/cross_entity_state_dependency/start_production_blocked_unless_all_lines_measured
    """
    cust = create_customer()
    order = create_order(cust["id"], deposit_pct=0.30)
    la = add_line(order["id"], order["version"], artwork_label="A",
                  nominal_width_in=8, nominal_height_in=10, molding_rate_per_ui=0.30)
    refreshed = get_success_data(api.get_order(order["id"], DESIGNER))
    lb = add_line(order["id"], refreshed["version"], artwork_label="B",
                  nominal_width_in=9, nominal_height_in=12, molding_rate_per_ui=0.30)
    measure_line(la["id"], 8, 10)  # B stays DRAFT
    quoted = quote(order["id"])
    pay(quoted["id"], "DEPOSIT", 45.00)
    resp = api.start_production(quoted["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_LINES_NOT_MEASURED)
    after = get_success_data(api.get_order(quoted["id"], DESIGNER))
    assert after["production_status"] == "QUOTED"


def test_start_production_succeeds_once_all_lines_measured(api):
    """PRD §3.6: "An order moves from `QUOTED` to `IN_PRODUCTION` only when its
    `payment_status` is `DEPOSIT_PAID` or `PAID_IN_FULL` ... and when every non-voided
    frame line has `line_status` of `MEASURED`".

    Second test for the lines-measured cross-entity dependency: with both lines
    measured the transition succeeds.

    Design: Difficulty/cross_entity_state_dependency/start_production_blocked_unless_all_lines_measured
    """
    cust = create_customer()
    order = create_order(cust["id"], deposit_pct=0.30)
    la = add_line(order["id"], order["version"], artwork_label="A",
                  nominal_width_in=8, nominal_height_in=10, molding_rate_per_ui=0.30)
    refreshed = get_success_data(api.get_order(order["id"], DESIGNER))
    lb = add_line(order["id"], refreshed["version"], artwork_label="B",
                  nominal_width_in=9, nominal_height_in=12, molding_rate_per_ui=0.30)
    measure_line(la["id"], 8, 10)
    measure_line(lb["id"], 9, 12)
    quoted = quote(order["id"])
    pay(quoted["id"], "DEPOSIT", quoted["deposit_required"])
    started = get_success_data(api.start_production(quoted["id"], TECH))
    assert started["production_status"] == "IN_PRODUCTION"


# ===========================================================================
# Difficulty: cross_entity_state_dependency / mark_ready_blocked_unless_all_tasks_completed
# ===========================================================================
def test_mark_ready_blocked_unless_all_tasks_completed(api):
    """PRD §3.7: "This is allowed only when every production task belonging to the
    order has `task_status` of `COMPLETED`; any incomplete task causes rejection with
    `ERR_TASKS_INCOMPLETE`."

    Design: Difficulty/cross_entity_state_dependency/mark_ready_blocked_unless_all_tasks_completed
    """
    cust, order, line = setup_in_production_order(deposit_pct=0.30, measure_dims=(8, 10))
    bench = create_workbench(bench_type="ASSEMBLY", bench_name="Asm T")
    get_success_data(_schedule(api, order["id"], bench["id"], 0, 30))  # left SCHEDULED
    resp = api.mark_ready(order["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_TASKS_INCOMPLETE)
    after = get_success_data(api.get_order(order["id"], DESIGNER))
    assert after["production_status"] == "IN_PRODUCTION"


def test_mark_ready_succeeds_once_all_tasks_completed(api):
    """PRD §3.7: "Once production is finished, the `FrameProductionTech` marks the
    order ready, advancing `production_status` from `IN_PRODUCTION` to `READY`. This is
    allowed only when every production task belonging to the order has `task_status` of
    `COMPLETED`".

    Second test for the tasks-completed cross-entity dependency: completing the task
    unblocks mark-ready.

    Design: Difficulty/cross_entity_state_dependency/mark_ready_blocked_unless_all_tasks_completed
    """
    cust, order, line = setup_in_production_order(deposit_pct=0.30, measure_dims=(8, 10))
    bench = create_workbench(bench_type="ASSEMBLY", bench_name="Asm T2")
    task = get_success_data(_schedule(api, order["id"], bench["id"], 0, 30))
    get_success_data(api.complete_task(task["id"], TECH))
    ready = get_success_data(api.mark_ready(order["id"], TECH))
    assert ready["production_status"] == "READY"


# ===========================================================================
# Difficulty: compensating_invariant / task_release_conserves_workbench_free_interval
# ===========================================================================
def test_task_release_conserves_workbench_free_interval(api):
    """PRD §3.8: "Every production task for the order that is `SCHEDULED` or
    `COMPLETED` is moved to `RELEASED`, which frees its half-open interval on the
    workbench so the bench becomes available again."

    After cancel releases the [0,60) reservation, a brand-new task on [0,60) on the
    same bench is accepted (no occupancy drift).

    Design: Difficulty/compensating_invariant/task_release_conserves_workbench_free_interval
    """
    cust, o1, l1 = setup_in_production_order(deposit_pct=0.30, measure_dims=(8, 10))
    bench = create_workbench(bench_type="ASSEMBLY", bench_name="Asm F")
    t1 = get_success_data(_schedule(api, o1["id"], bench["id"], 0, 60))
    get_success_data(api.cancel_order(o1["id"], CLERK))
    released = get_success_data(api.get_task(t1["id"], TECH))
    assert released["task_status"] == "RELEASED"
    # Second order on the same freed bench/interval.
    cust2, o2, l2 = setup_in_production_order(deposit_pct=0.30, measure_dims=(8, 10))
    t2 = validate_success(_schedule(api, o2["id"], bench["id"], 0, 60), expected_status=201)
    assert t2["task_status"] == "SCHEDULED"
    assert t2["start_minute"] == 0


def test_released_task_interval_reusable_by_overlapping_new_task(api):
    """PRD §3.8: "which frees its half-open interval on the workbench so the bench
    becomes available again."

    Second test for the interval-conservation invariant: after release, even an
    interval overlapping the original [0,60) (here [30,90)) is accepted because the old
    reservation no longer occupies the bench.

    Design: Difficulty/compensating_invariant/task_release_conserves_workbench_free_interval
    """
    cust, o1, l1 = setup_in_production_order(deposit_pct=0.30, measure_dims=(8, 10))
    bench = create_workbench(bench_type="ASSEMBLY", bench_name="Asm F2")
    t1 = get_success_data(_schedule(api, o1["id"], bench["id"], 0, 60))
    get_success_data(api.cancel_order(o1["id"], CLERK))
    cust2, o2, l2 = setup_in_production_order(deposit_pct=0.30, measure_dims=(8, 10))
    t2 = validate_success(_schedule(api, o2["id"], bench["id"], 30, 90), expected_status=201)
    assert t2["task_status"] == "SCHEDULED"


# ===========================================================================
# Corner: validations / fragile_order_on_assembly_bench_rejected_when_no_overlap
# ===========================================================================
def test_fragile_order_on_assembly_bench_rejected_when_no_overlap(api):
    """PRD §3.6: "if the order has a fragile line, the chosen workbench must be of
    type `GLASS_CUTTING`; choosing any other bench for a fragile order is rejected with
    `ERR_FRAGILE_REQUIRES_GLASS_BENCH`."

    Design: Corner/validations/fragile_order_on_assembly_bench_rejected_when_no_overlap
    """
    cust, frag_order, fl = setup_fragile_in_production_order()
    asm = create_workbench(bench_type="ASSEMBLY", bench_name="Asm Fr")
    resp = _schedule(api, frag_order["id"], asm["id"], 0, 60)  # empty bench, no overlap
    validate_error(resp, ApiErrorId.ERR_FRAGILE_REQUIRES_GLASS_BENCH)
