"""Shift locking, crew headcount and overlap gates, worker accumulators, the
fatigue penalty gate vs the advisory hours ledger, rest-gap boundaries, and
the badge-vs-rest validation ordering."""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_success,
    assign_worker,
    create_shift,
    register_worker,
    setup_execution_turnaround,
    vet_and_badge_worker,
    make_supervisor_headers,
)


def test_shift_lock_requires_assignment_and_blocks_late_assignments(
    api, coordinator_headers, planner_headers
):
    """PRD §3.3: "A shift is born `PLANNED`; its full status vocabulary is
    `PLANNED`, `LOCKED`, `COMPLETED`, and `CANCELLED`, and the one transition
    the machine defines is the lock, which moves a `PLANNED` shift to `LOCKED`
    and requires at least one `ASSIGNED` assignment — locking an empty shift is
    rejected with `ERR_EMPTY_SHIFT`."
    PRD §3.3: "The shift must still be `PLANNED`; assignments to a locked shift
    are refused with `ERR_SHIFT_LOCKED`."

    Design: Corner/state_machines/shift_lock_lifecycle
    """
    ctx = setup_execution_turnaround()
    worker = ctx["workers"][0]
    # a second badged worker keeps the post-lock attempt free of any other gate
    second = register_worker(ctx["contractor"]["id"], full_name="Ibe Nador", trade="FITTER")
    vet_and_badge_worker(second["id"])
    shift = create_shift(ctx["turnaround"]["id"], planned_headcount=2)

    resp_empty = api.lock_shift(shift["id"], planner_headers)
    validate_error(resp_empty, ApiErrorId.ERR_EMPTY_SHIFT)

    assign_worker(shift["id"], worker["id"], planned_hours=8)
    locked = validate_success(api.lock_shift(shift["id"], planner_headers))
    assert locked["status"] == "LOCKED"

    resp_late = api.create_assignment(
        shift["id"],
        {"worker_id": second["id"], "planned_hours": 4},
        planner_headers,
    )
    validate_error(resp_late, ApiErrorId.ERR_SHIFT_LOCKED)


def test_shift_rejects_assignment_once_headcount_full(api, planner_headers):
    """PRD §3.3: "The shift must have room: when the number of non-`CANCELLED`
    assignments already equals `planned_headcount`, the assignment is rejected
    with `ERR_SHIFT_HEADCOUNT_FULL`."

    Design: Corner/validations/shift_headcount_full_boundary
    """
    ctx = setup_execution_turnaround(num_workers=2)
    w1, w2 = ctx["workers"]
    shift = create_shift(ctx["turnaround"]["id"], planned_headcount=1)

    assign_worker(shift["id"], w1["id"], planned_hours=8)  # 1 == headcount cap now
    resp = api.create_assignment(
        shift["id"], {"worker_id": w2["id"], "planned_hours": 8}, planner_headers
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_HEADCOUNT_FULL)


def test_overlapping_shift_assignment_rejected(api, planner_headers):
    """PRD §3.3: "The worker must not already hold an assignment whose shift
    overlaps the candidate: shift intervals are compared as half-open ranges,
    so a candidate whose `starts_at` coincides exactly with an existing
    assignment's `ends_at` does not overlap, while any positive intersection
    draws `ERR_SHIFT_OVERLAP`."

    Design: Corner/validations/shift_overlap_rejected
    """
    ctx = setup_execution_turnaround()
    worker = ctx["workers"][0]
    sa = create_shift(
        ctx["turnaround"]["id"],
        shift_date="2026-06-15", starts_at="2026-06-15T08:00:00Z",
        ends_at="2026-06-15T16:00:00Z",
    )
    sb = create_shift(
        ctx["turnaround"]["id"],
        shift_date="2026-06-15", starts_at="2026-06-15T15:00:00Z",
        ends_at="2026-06-15T23:00:00Z",
    )
    assign_worker(sa["id"], worker["id"], planned_hours=8)

    resp = api.create_assignment(
        sb["id"], {"worker_id": worker["id"], "planned_hours": 8}, planner_headers
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


def test_assignment_completion_updates_distinct_worker_totals(
    api, planner_headers
):
    """PRD §3.3: "Completing an assignment — a `ContractorSupervisor` action
    legal only while the turnaround is in `EXECUTION` — records the worked
    `actual_hours`, moves the assignment from `ASSIGNED` to `COMPLETED`, adds
    those hours into the worker's `total_shift_hours` (the running sum of
    `actual_hours` across the worker's `COMPLETED` assignments), and triggers
    the fatigue recomputation."
    PRD §3.3: "The worker's `ledger_hours` field is the sum of `planned_hours`
    over the input set, a plain chronological hours accumulator".

    Design: Corner/calculations/assignment_complete_updates_worker_totals
    """
    ctx = setup_execution_turnaround()
    contractor = ctx["contractor"]
    worker = ctx["workers"][0]
    shift = create_shift(ctx["turnaround"]["id"], planned_headcount=3)
    assignment = assign_worker(shift["id"], worker["id"], planned_hours=8)

    completed = validate_success(
        api.complete_assignment(
            assignment["id"],
            {"actual_hours": 7.5},
            make_supervisor_headers(contractor["id"]),
        )
    )
    assert completed["status"] == "COMPLETED"

    after = validate_success(api.get_worker(worker["id"], planner_headers))
    assert after["total_shift_hours"] == 7.5, (
        f"total_shift_hours must track actuals: {after['total_shift_hours']} != 7.5"
    )
    assert after["ledger_hours"] == 8, (
        f"ledger_hours must track planned hours: {after['ledger_hours']} != 8"
    )


def _setup_rest_gap_scenario(api):
    """EXECUTION turnaround, two badged workers W1/W2 both ASSIGNED to shift SA
    (2026-06-13 08:00-16:00); candidate shifts SB (06-14 02:00-10:00, exactly a
    10h gap after SA) and SC (06-14 01:00-09:00, a 9h gap after SA)."""
    ctx = setup_execution_turnaround(num_workers=2)
    t_id = ctx["turnaround"]["id"]
    sa = create_shift(
        t_id, shift_date="2026-06-13", starts_at="2026-06-13T08:00:00Z",
        ends_at="2026-06-13T16:00:00Z", planned_headcount=5,
    )
    sb = create_shift(
        t_id, shift_date="2026-06-14", starts_at="2026-06-14T02:00:00Z",
        ends_at="2026-06-14T10:00:00Z", planned_headcount=5,
    )
    sc = create_shift(
        t_id, shift_date="2026-06-14", starts_at="2026-06-14T01:00:00Z",
        ends_at="2026-06-14T09:00:00Z", planned_headcount=5,
    )
    w1, w2 = ctx["workers"]
    assign_worker(sa["id"], w1["id"], planned_hours=8)
    assign_worker(sa["id"], w2["id"], planned_hours=8)
    return ctx, sa, sb, sc


def test_rest_gap_exactly_ten_hours_admitted(api, planner_headers):
    """PRD §3.3: "Consecutive assignments must also respect the minimum rest
    gap: the interval from the end of one kept assignment's shift to the start
    of the next must be at least ten hours, with a gap of exactly ten hours
    admitted and anything shorter rejected with `ERR_REST_PERIOD_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/worker_rest_gap_exactly_minimum_admitted_below_rejected
    """
    ctx, _sa, sb, _sc = _setup_rest_gap_scenario(api)
    w1 = ctx["workers"][0]

    # SB starts exactly 10h after SA ends -> equality admitted
    resp = api.create_assignment(
        sb["id"], {"worker_id": w1["id"], "planned_hours": 8}, planner_headers
    )
    admitted = validate_success(resp, 201)
    assert admitted["status"] == "ASSIGNED"
    assert admitted["worker_id"] == w1["id"]
    assert admitted["shift_id"] == sb["id"]


def test_rest_gap_nine_hours_rejected(api, planner_headers):
    """PRD §3.3: "Consecutive assignments must also respect the minimum rest
    gap: the interval from the end of one kept assignment's shift to the start
    of the next must be at least ten hours, with a gap of exactly ten hours
    admitted and anything shorter rejected with `ERR_REST_PERIOD_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/worker_rest_gap_exactly_minimum_admitted_below_rejected
    """
    ctx, _sa, _sb, sc = _setup_rest_gap_scenario(api)
    w2 = ctx["workers"][1]

    # SC starts 9h after SA ends -> below the ten-hour floor
    resp = api.create_assignment(
        sc["id"], {"worker_id": w2["id"], "planned_hours": 8}, planner_headers
    )
    validate_error(resp, ApiErrorId.ERR_REST_PERIOD_VIOLATION)


def _setup_fatigue_scenario(api):
    """EXECUTION turnaround; one badged worker ASSIGNED to S1 (NIGHT 06-13
    22:00 -> 06-14 06:00, 8h) and S2 (DAY 06-14 18:00 -> 06-15 00:00, 6h; the
    12h gap after S1 accrues the rest penalty): stored penalty 15, ledger 14.
    Returns (ctx, candidate night shift S3 06-15 22:00 -> 06-16 06:00)."""
    ctx = setup_execution_turnaround()
    t_id = ctx["turnaround"]["id"]
    s1 = create_shift(
        t_id, shift_date="2026-06-13", shift_type="NIGHT",
        starts_at="2026-06-13T22:00:00Z", ends_at="2026-06-14T06:00:00Z",
    )
    s2 = create_shift(
        t_id, shift_date="2026-06-14", shift_type="DAY",
        starts_at="2026-06-14T18:00:00Z", ends_at="2026-06-15T00:00:00Z",
    )
    s3 = create_shift(
        t_id, shift_date="2026-06-15", shift_type="NIGHT",
        starts_at="2026-06-15T22:00:00Z", ends_at="2026-06-16T06:00:00Z",
    )
    worker = ctx["workers"][0]
    assign_worker(s1["id"], worker["id"], planned_hours=8)
    assign_worker(s2["id"], worker["id"], planned_hours=6)
    return ctx, s3


def test_fatigue_penalty_score_twenty_rejects_assignment(api, planner_headers):
    """PRD §3.3: "Walking the ordered assignments, each assignment adds five
    penalty points when its shift is a `NIGHT` shift, and ten penalty points
    when the gap from the previous kept assignment's shift end to this shift's
    start is at least ten hours but strictly less than fourteen hours".
    PRD §3.3: "When a candidate assignment is evaluated, its shift is inserted
    into the worker's ordering and the projected penalty score is computed with
    the candidate included; a projected score of twenty or more rejects the
    assignment with `ERR_FATIGUE_LIMIT`."

    Design: Difficulty/dual_variant_calc/fatigue_penalty_rejects_worker_hours_ledger_admits
    """
    ctx, s3 = _setup_fatigue_scenario(api)
    worker = ctx["workers"][0]

    # projected: 5 (S1 NIGHT) + 10 (S2 rest 12h) + 5 (S3 NIGHT) = 20 >= 20
    resp = api.create_assignment(
        s3["id"], {"worker_id": worker["id"], "planned_hours": 8}, planner_headers
    )
    validate_error(resp, ApiErrorId.ERR_FATIGUE_LIMIT)


def test_fatigue_rejection_leaves_stored_worker_fields_unchanged(api, planner_headers):
    """PRD §3.3: "The stored `fatigue_penalty_score` and `ledger_hours` always
    reflect only the worker's existing assignments and are recomputed after
    every assignment creation, completion, and cancellation."
    PRD §3.3: "This is deliberately stricter than the ledger view — a worker
    carrying twenty-two ledger hours whose night work and short rests push the
    projected score to twenty is rejected even though `HOURS_LEDGER` would
    have admitted them."

    Design: Difficulty/dual_variant_calc/fatigue_penalty_rejects_worker_hours_ledger_admits
    """
    ctx, s3 = _setup_fatigue_scenario(api)
    worker = ctx["workers"][0]

    resp = api.create_assignment(
        s3["id"], {"worker_id": worker["id"], "planned_hours": 8}, planner_headers
    )
    validate_error(resp, ApiErrorId.ERR_FATIGUE_LIMIT)

    after = validate_success(api.get_worker(worker["id"], planner_headers))
    assert after["fatigue_penalty_score"] == 15, (
        "rejected candidate must not enter the stored score: "
        f"{after['fatigue_penalty_score']} != 15"
    )
    assert after["ledger_hours"] == 14, (
        f"ledger stays 8 + 6 = 14 (a 22-hour projection would have been admitted): "
        f"{after['ledger_hours']} != 14"
    )


def _setup_suspended_worker_scenario(api):
    """EXECUTION turnaround; worker BADGED and ASSIGNED to SA (06-13
    08:00-16:00), then badge SUSPENDED; candidate SC (06-14 01:00-09:00) sits
    9h after SA — inside the rest-gap floor."""
    ctx = setup_execution_turnaround()
    t_id = ctx["turnaround"]["id"]
    worker = ctx["workers"][0]
    sa = create_shift(
        t_id, shift_date="2026-06-13", starts_at="2026-06-13T08:00:00Z",
        ends_at="2026-06-13T16:00:00Z", planned_headcount=3,
    )
    assign_worker(sa["id"], worker["id"], planned_hours=8)
    return ctx, worker, sa


def test_suspended_worker_assignment_reports_badge_error_over_rest_gap(
    api, coordinator_headers, planner_headers
):
    """PRD §2.8: "Every request is evaluated against a fixed cascade of checks,
    and the first failing check in this order determines the error returned."
    PRD §2.8: "9. Safety gates, applicable to crew assignment, daily-report
    drafting, work-item start, permit transitions, and isolation transitions:
    the worker's badge is `BADGED` (`ERR_BADGE_NOT_CLEARED`)" precedes "10.
    Temporal rules, applicable to crew assignment, isolation planning, and
    permit transitions: no half-open shift overlap (`ERR_SHIFT_OVERLAP`), the
    minimum rest gap holds (`ERR_REST_PERIOD_VIOLATION`)".

    Design: Difficulty/priority_pair_validation_conflict/assign_badge_safety_error_beats_rest_temporal
    """
    ctx, worker, _sa = _setup_suspended_worker_scenario(api)
    validate_success(
        api.badge_transition_worker(worker["id"], {"to": "SUSPENDED"}, coordinator_headers)
    )
    sc = create_shift(
        ctx["turnaround"]["id"], shift_date="2026-06-14",
        starts_at="2026-06-14T01:00:00Z", ends_at="2026-06-14T09:00:00Z",
        planned_headcount=3,
    )

    # badge (safety, tier 9) must surface before the 9h rest gap (temporal, tier 10)
    resp = api.create_assignment(
        sc["id"], {"worker_id": worker["id"], "planned_hours": 8}, planner_headers
    )
    validate_error(resp, ApiErrorId.ERR_BADGE_NOT_CLEARED)


def test_badge_rejection_creates_no_assignment_and_keeps_suspension(
    api, coordinator_headers, planner_headers
):
    """PRD §3.3: "The worker's badge must be `BADGED`; anything else —
    `REGISTERED`, `VETTED`, `SUSPENDED`, or `DEBADGED` — draws
    `ERR_BADGE_NOT_CLEARED`."

    Design: Difficulty/priority_pair_validation_conflict/assign_badge_safety_error_beats_rest_temporal
    """
    ctx, worker, _sa = _setup_suspended_worker_scenario(api)
    validate_success(
        api.badge_transition_worker(worker["id"], {"to": "SUSPENDED"}, coordinator_headers)
    )
    sc = create_shift(
        ctx["turnaround"]["id"], shift_date="2026-06-14",
        starts_at="2026-06-14T01:00:00Z", ends_at="2026-06-14T09:00:00Z",
        planned_headcount=3,
    )

    resp = api.create_assignment(
        sc["id"], {"worker_id": worker["id"], "planned_hours": 8}, planner_headers
    )
    validate_error(resp, ApiErrorId.ERR_BADGE_NOT_CLEARED)

    after = validate_success(api.get_worker(worker["id"], planner_headers))
    assert after["badge_status"] == "SUSPENDED"
    sc_assignments = validate_success(
        api.list_shift_assignments(sc["id"], planner_headers)
    )
    assert sc_assignments == [], "rejected assignment must leave no trace on the shift"
