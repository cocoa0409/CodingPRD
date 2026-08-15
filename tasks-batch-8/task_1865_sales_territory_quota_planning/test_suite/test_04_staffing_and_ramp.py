"""Territory staffing: half-open assignment windows, headcount capacity,
new-hire ramp requirement, ramp rounding, and assignment end cascades."""
from test_helpers import (
    ADMIN,
    ZERO_RAMP_MULTIPLIERS,
    ApiErrorId,
    activate_territory,
    add_territory,
    create_assignment,
    create_plan,
    create_ramp_schedule,
    create_rep,
    create_rep_assignment_payload,
    get_assignment,
    open_plan,
    setup_allocated_leaf,
    setup_open_plan,
    setup_ramp_boundary_plan,
    validate_error,
    validate_success,
)


def _open_plan_with_two_territories():
    """Plan OPEN with ACTIVE T1 and T2 (capacity 5 each) and one rep."""
    plan = create_plan(label="FY27-O")
    t1 = add_territory(plan["id"], name="T1", headcount_capacity=5)
    t2 = add_territory(plan["id"], name="T2", headcount_capacity=5)
    activate_territory(t1["id"])
    activate_territory(t2["id"])
    open_plan(plan["id"])
    rep = create_rep()
    return plan, t1, t2, rep


def test_rep_assignment_half_open_adjacency_accepted(api):
    """PRD: "The window is half-open: `effective_from` must fall inside the
    plan year, and `effective_to`, when present, is the exclusive end — an
    assignment whose successor begins the day it ends does not overlap it."

    [2027-01-01, 2027-07-01) followed by a window starting exactly 2027-07-01
    is adjacent, not overlapping.

    Design: Difficulty/resource_temporal_overlap/rep_assignment_half_open_adjacency
    """
    plan, t1, t2, rep = _open_plan_with_two_territories()
    a1 = validate_success(api.create_rep_assignment(
        create_rep_assignment_payload(plan["id"], rep["id"], t1["id"],
                                      effective_from="2027-01-01",
                                      effective_to="2027-07-01"), ADMIN), 201)
    assert a1["status"] == "ACTIVE"
    a2 = validate_success(api.create_rep_assignment(
        create_rep_assignment_payload(plan["id"], rep["id"], t2["id"],
                                      effective_from="2027-07-01"), ADMIN),
        201)
    assert a2["status"] == "ACTIVE"


def test_rep_assignment_one_day_overlap_rejected(api):
    """PRD: "the rep must not already hold an `ACTIVE` assignment whose
    half-open window overlaps the new one (`ERR_ASSIGNMENT_OVERLAP`)"

    A new window starting 2027-06-30 precedes the existing window's exclusive
    end 2027-07-01 by one day and collides.

    Design: Difficulty/resource_temporal_overlap/rep_assignment_half_open_adjacency
    """
    plan, t1, t2, rep = _open_plan_with_two_territories()
    validate_success(api.create_rep_assignment(
        create_rep_assignment_payload(plan["id"], rep["id"], t1["id"],
                                      effective_from="2027-01-01",
                                      effective_to="2027-07-01"), ADMIN), 201)
    validate_error(api.create_rep_assignment(
        create_rep_assignment_payload(plan["id"], rep["id"], t2["id"],
                                      effective_from="2027-06-30"), ADMIN),
        ApiErrorId.ERR_ASSIGNMENT_OVERLAP, 409)


def test_headcount_capacity_enforced_rejected(api):
    """PRD: "the territory must not already carry `headcount_capacity` active
    assignments (`ERR_HEADCOUNT_EXCEEDED`)"

    A territory with headcount_capacity 1 accepts the first ACTIVE assignment
    and rejects the second.

    Design: Corner/validations/headcount_capacity_enforced_rejected
    """
    plan = create_plan(label="FY27")
    t = add_territory(plan["id"], name="T", headcount_capacity=1)
    activate_territory(t["id"])
    open_plan(plan["id"])
    r1 = create_rep(full_name="R1")
    r2 = create_rep(full_name="R2")
    validate_success(api.create_rep_assignment(
        create_rep_assignment_payload(plan["id"], r1["id"], t["id"]), ADMIN),
        201)
    validate_error(api.create_rep_assignment(
        create_rep_assignment_payload(plan["id"], r2["id"], t["id"]), ADMIN),
        ApiErrorId.ERR_HEADCOUNT_EXCEEDED, 409)


def test_new_hire_without_ramp_schedule_rejected(api):
    """PRD: "Finally, a rep whose `hire_date` falls inside the plan year counts
    as a new hire and cannot be staffed without a ramp schedule — omitting
    `ramp_schedule_id` for such a rep fails with `ERR_RAMP_SCHEDULE_REQUIRED`"

    hire_date 2027-02-10 falls inside the 2027 plan year.

    Design: Corner/validations/new_hire_without_ramp_schedule_rejected
    """
    base = setup_open_plan(label="FY27")
    rep = create_rep(hire_date="2027-02-10", full_name="NH")
    validate_error(api.create_rep_assignment(
        create_rep_assignment_payload(base["plan"]["id"], rep["id"],
                                      base["t"]["id"],
                                      effective_from="2027-02-10"), ADMIN),
        ApiErrorId.ERR_RAMP_SCHEDULE_REQUIRED, 422)


def test_assignment_end_twice_rejected(api):
    """PRD: "The transition to `ENDED` stores the end date and freezes the
    assignment's `base_quota_cents`, `ramped_quota_cents`, and
    `final_quota_cents` at their current values."
    PRD: "Then the entity's own from-state is checked against the requested
    transition (`ERR_INVALID_STATE_TRANSITION`)"

    Ending an already-ENDED assignment is rejected, not silently idempotent.

    Design: Corner/state_machines/assignment_end_twice_rejected
    """
    base = setup_open_plan(label="FY27")
    rep = create_rep()
    asg = create_assignment(base["plan"]["id"], rep["id"], base["t"]["id"])
    ended = validate_success(
        api.end_rep_assignment(asg["id"], "2027-06-30", ADMIN), 200)
    assert ended["status"] == "ENDED"
    assert ended["effective_to"] == "2027-06-30"
    validate_error(api.end_rep_assignment(asg["id"], "2027-06-30", ADMIN),
                   ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)


def _setup_two_assignments_on_allocated_leaf():
    """OPEN plan; leaf T allocated 100000; veteran reps R1 (assignment created
    first) and R2 both ACTIVELY assigned to T, each with base share 50000."""
    base = setup_allocated_leaf(target=100000, label="FY27-END")
    plan_id = base["plan"]["id"]
    r1 = create_rep(hire_date="2025-06-01", full_name="R1")
    r2 = create_rep(hire_date="2025-06-01", full_name="R2")
    a1 = create_assignment(plan_id, r1["id"], base["t"]["id"])
    a2 = create_assignment(plan_id, r2["id"], base["t"]["id"])
    return base, r1, r2, a1, a2


def test_assignment_end_freezes_ended_assignment(api):
    """PRD: "The transition to `ENDED` stores the end date and freezes the
    assignment's `base_quota_cents`, `ramped_quota_cents`, and
    `final_quota_cents` at their current values."

    R1's frozen ramped quota is 12 x round_half_up(50000/12) == 12 x 4167 ==
    50004 even though its base was 50000.

    Design: Difficulty/transitive_cascade/assignment_end_share_recompute_cascade
    """
    base, r1, r2, a1, a2 = _setup_two_assignments_on_allocated_leaf()
    assert get_assignment(a1["id"])["base_quota_cents"] == 50000
    ended = validate_success(
        api.end_rep_assignment(a1["id"], "2027-06-30", ADMIN), 200)
    assert ended["status"] == "ENDED"
    frozen = get_assignment(a1["id"])
    assert frozen["base_quota_cents"] == 50000
    assert frozen["ramped_quota_cents"] == 50004
    assert frozen["effective_to"] == "2027-06-30"


def test_assignment_end_recomputes_survivor_shares(api):
    """PRD: "The cascade then fires: the territory's active-assignment count
    drops by one; the retained-quota split recomputes for every remaining
    active assignment on the territory, whose shares grow, whose ramped quotas
    recompute through the ramp calculation, and whose final quotas will
    recompute at reconciliation"

    Sole survivor R2 recomputes to base 100000 and ramped 99996
    (12 x round_half_up(100000/12) == 12 x 8333, pinned rounding — not 100000).

    Design: Difficulty/transitive_cascade/assignment_end_share_recompute_cascade
    """
    base, r1, r2, a1, a2 = _setup_two_assignments_on_allocated_leaf()
    validate_success(api.end_rep_assignment(a1["id"], "2027-06-30", ADMIN),
                     200)
    survivor = get_assignment(a2["id"])
    assert survivor["status"] == "ACTIVE"
    assert survivor["base_quota_cents"] == 100000
    assert survivor["ramped_quota_cents"] == 99996


def test_ramp_schedule_shape_validation_rejected(api):
    """PRD: "each carries a `name` and a `multipliers` array of exactly twelve
    numbers, where the first entry is the quota multiplier for a rep's first
    tenure month, the second entry for the second tenure month, and so on
    through the twelfth; every entry lies between 0.00 and 1.00 inclusive with
    at most two decimal places, and the sequence is non-decreasing. A schedule
    violating any of those shape rules is rejected with
    `ERR_INVALID_RAMP_SCHEDULE`."

    The all-zero schedule is non-decreasing and within range, so it is legal.

    Design: Corner/entities/ramp_schedule_shape_validation_rejected
    """
    validate_error(api.create_ramp_schedule(
        {"name": "short",
         "multipliers": [0.00, 0.25, 0.50, 0.75, 1.00, 1.00, 1.00, 1.00, 1.00,
                         1.00, 1.00]}, ADMIN),
        ApiErrorId.ERR_INVALID_RAMP_SCHEDULE, 422)
    validate_error(api.create_ramp_schedule(
        {"name": "decreasing",
         "multipliers": [0.50, 0.25, 0.50, 0.75, 1.00, 1.00, 1.00, 1.00, 1.00,
                         1.00, 1.00, 1.00]}, ADMIN),
        ApiErrorId.ERR_INVALID_RAMP_SCHEDULE, 422)
    ok = validate_success(api.create_ramp_schedule(
        {"name": "zeros", "multipliers": list(ZERO_RAMP_MULTIPLIERS)}, ADMIN),
        201)
    assert len(ok["multipliers"]) == 12


def _setup_ramp_rounding_scenario():
    """OPEN plan; leaf T allocated the full target 100000; standard ramp
    schedule [0.00, 0.25, 0.50, 0.75, 1.00 x8]; rep hired 2027-01-10 (day <=
    15, so January is tenure month 1)."""
    base = setup_allocated_leaf(target=100000, productivity=1000000,
                                label="FY27-RAMP")
    ramp = create_ramp_schedule(name="Std Ramp")
    rep = create_rep(hire_date="2027-01-10", full_name="New Hire")
    return base, ramp, rep


def test_ramp_quota_uses_pinned_two_step_rounding(api):
    """PRD: "First, the annual share is divided by twelve and rounded half-up
    to whole cents, giving the monthly base."
    PRD: "Each month's contribution is the monthly base times that month's
    multiplier, rounded half-up to whole cents — the second pinned rounding
    step — and the ramped quota is the plain integer sum of the twelve
    already-rounded contributions. Rounding only once after summing unrounded
    contributions is invalid."

    monthly base = round_half_up(100000/12) == 8333; ramped =
    0 + 2083 + 4167 + 6250 + 8333 x 8 == 79164.

    Design: Difficulty/combinatorial_formula/ramp_quota_per_month_rounding
    """
    base, ramp, rep = _setup_ramp_rounding_scenario()
    asg = validate_success(api.create_rep_assignment(
        create_rep_assignment_payload(base["plan"]["id"], rep["id"],
                                      base["t"]["id"],
                                      ramp_schedule_id=ramp["id"]), ADMIN),
        201)
    assert asg["base_quota_cents"] == 100000, \
        "sole ACTIVE sharer of the leaf's retained quota"
    assert asg["ramped_quota_cents"] == 79164


def test_ramp_quota_sum_then_round_is_invalid(api):
    """PRD: "Each month's contribution is the monthly base times that month's
    multiplier, rounded half-up to whole cents — the second pinned rounding
    step — and the ramped quota is the plain integer sum of the twelve
    already-rounded contributions. Rounding only once after summing unrounded
    contributions is invalid."

    The per-month rounded contributions are 0, 2083, 4167, 6250 and 8333 x8;
    the sum-then-round alternative 79167 is explicitly invalid.

    Design: Difficulty/combinatorial_formula/ramp_quota_per_month_rounding
    """
    base, ramp, rep = _setup_ramp_rounding_scenario()
    asg = validate_success(api.create_rep_assignment(
        create_rep_assignment_payload(base["plan"]["id"], rep["id"],
                                      base["t"]["id"],
                                      ramp_schedule_id=ramp["id"]), ADMIN),
        201)
    monthly_base = 8333  # round_half_up(100000 / 12)
    contributions = [0, 2083, 4167, 6250] + [monthly_base] * 8
    expected = sum(contributions)
    assert expected == 79164
    assert asg["ramped_quota_cents"] == expected
    assert asg["ramped_quota_cents"] != 79167, \
        "sum-then-round is explicitly invalid"


def test_ramp_day15_hire_boundary(api):
    """PRD: "when the rep's hire day falls after the fifteenth of the month,
    reduce the index by one more, so the hire month counts as tenure month zero
    and contributes nothing."

    Identical except for the hire day: R15 (hired 2027-03-15) counts March as
    tenure month 1 and ramps to 75000 on base 120000 (0+0+0+2500+5000+7500+
    6x10000); R16 (hired 2027-03-16) makes March tenure month 0 and ramps to
    65000 (0+0+0+0+2500+5000+7500+5x10000).

    Design: Corner/calculations/ramp_day15_hire_boundary
    """
    fx = setup_ramp_boundary_plan()
    plan_id = fx["plan"]["id"]
    a15 = validate_success(api.create_rep_assignment(
        create_rep_assignment_payload(plan_id, fx["r15"]["id"],
                                      fx["t15"]["id"],
                                      ramp_schedule_id=fx["ramp"]["id"]),
        ADMIN), 201)
    a16 = validate_success(api.create_rep_assignment(
        create_rep_assignment_payload(plan_id, fx["r16"]["id"],
                                      fx["t16"]["id"],
                                      ramp_schedule_id=fx["ramp"]["id"]),
        ADMIN), 201)
    assert a15["base_quota_cents"] == 120000
    assert a15["ramped_quota_cents"] == 75000
    assert a16["base_quota_cents"] == 120000
    assert a16["ramped_quota_cents"] == 65000


def test_ramp_tenure_beyond_schedule_is_fully_ramped(api):
    """PRD: "A tenure index of zero or less yields a multiplier of 0.00 for
    that month; an index of thirteen or more yields 1.00; anything in between
    selects the schedule entry at that index position."

    A rep hired 2025-03-10 has tenure index >= 13 in every month of the 2027
    plan year, so the ramped quota equals the full base even with a ramp
    schedule attached.

    Design: Corner/calculations/ramp_tenure_beyond_schedule_is_fully_ramped
    """
    base = setup_allocated_leaf(target=120000, productivity=1000000,
                                label="FY27-VET")
    ramp = create_ramp_schedule(name="Std")
    rep = create_rep(hire_date="2025-03-10", full_name="Vet")
    asg = validate_success(api.create_rep_assignment(
        create_rep_assignment_payload(base["plan"]["id"], rep["id"],
                                      base["t"]["id"],
                                      ramp_schedule_id=ramp["id"]), ADMIN),
        201)
    assert asg["base_quota_cents"] == 120000
    assert asg["ramped_quota_cents"] == 120000


def test_cross_plan_assignment_reference_rejected(api):
    """PRD: "A reference that crosses plan boundaries is rejected with
    `ERR_CROSS_PLAN_REFERENCE` (HTTP 409)" and "a rep assignment still requires
    its territory to live in the plan it names."

    Design: Corner/validations/cross_plan_assignment_reference_rejected
    """
    plan_a = create_plan(label="A", start_date="2027-01-01",
                         end_date="2027-12-31", lock_date="2027-01-15")
    ta = add_territory(plan_a["id"], name="TA")
    activate_territory(ta["id"])
    plan_b = create_plan(label="B", start_date="2028-01-01",
                         end_date="2028-12-31", lock_date="2028-01-15")
    tb = add_territory(plan_b["id"], name="TB")
    activate_territory(tb["id"])
    rep = create_rep()
    validate_error(api.create_rep_assignment(
        create_rep_assignment_payload(plan_a["id"], rep["id"], tb["id"]),
        ADMIN), ApiErrorId.ERR_CROSS_PLAN_REFERENCE, 409)
