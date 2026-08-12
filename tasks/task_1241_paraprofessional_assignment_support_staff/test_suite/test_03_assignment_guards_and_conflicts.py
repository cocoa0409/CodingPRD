"""Assignment proposal guards: priority order, overlap geometry, cap, budget,
date coherence (PRD §2.7, §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_qualification,
    create_active_assignment,
    create_active_plan,
    create_active_student,
    create_assignment_payload,
    create_building_payload,
    create_para,
    create_plan,
    create_plan_payload,
    create_student,
    get_plan_version,
    propose_assignment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]


def test_plan_state_error_beats_budget_error_on_assignment_create(api):
    """PRD §2.7: "Ninth and last, the fiscal check: budget sufficiency is evaluated only after every other rule has passed, else `ERR_INSUFFICIENT_BUDGET`. Fiscal checks always run last so that a request failing both a structural rule and the budget surfaces the structural error."
    PRD §2.7: "the plan must be in a state allowing the operation (configuration writes need `DRAFT` or `ACTIVE`; assignment and coverage writes need `ACTIVE`; close needs `RECONCILING`) else `ERR_PLAN_NOT_ACTIVE`, `ERR_PLAN_NOT_DRAFT`, or `ERR_PLAN_NOT_RECONCILING"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_priority_on_assignment_create
    """
    # Plan stays DRAFT with a budget of 1 cent: both plan-state and budget fail
    plan = create_plan(total_budget_cents=1)
    plan_id = plan["id"]
    building = validate_success(
        api.create_building(create_building_payload(plan_id), ADMIN), 201
    )
    p1 = create_para(plan_id, building["id"])
    s1 = create_active_student(plan_id, building["id"], iep_minutes_per_week=300)

    resp = api.create_assignment(
        create_assignment_payload(
            plan_id, s1["id"], p1["id"], building["id"], plan["version"],
            days_of_week=["MON"], daily_start_minute=480, daily_end_minute=540,
        ),
        COORD,
    )
    data = validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
    assert data["error_id"] != ApiErrorId.ERR_INSUFFICIENT_BUDGET


def test_qualification_error_beats_schedule_overlap_on_assignment_create(api):
    """PRD §2.7: "Fifth, business safety: qualification currency is enforced as `ERR_QUALIFICATION_NOT_CURRENT`, and segregation of duties on countersigning as `ERR_EVALUATION_SELF_COUNTERSIGN`. Sixth, business constraints: schedule overlap (`ERR_SCHEDULE_OVERLAP`), timesheet double-logging (`ERR_TIMESHEET_OVERLAP`), uniqueness rules (`ERR_DUPLICATE_COVERAGE_PLAN`, `ERR_OPEN_CHANGE_ORDER_EXISTS`, `ERR_ALLOCATIONS_ALREADY_COMPUTED`, `ERR_INVALID_REQUEST`), and the weekly-minutes capacity check (`ERR_WEEKLY_MINUTES_CAP_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_priority_on_assignment_create
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)  # no qualifications
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=1500)
    create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)  # A1 ACTIVE 480-780
    # S2 requires BEHAVIOR_SUPPORT (P1 lacks it) AND candidate window overlaps A1
    s2 = create_active_student(
        plan_id, b1, iep_service_level="ONE_TO_ONE", required_qualification="BEHAVIOR_SUPPORT"
    )
    resp = api.create_assignment(
        create_assignment_payload(
            plan_id, s2["id"], p1["id"], b1, get_plan_version(plan_id),
            daily_start_minute=600, daily_end_minute=900,
        ),
        COORD,
    )
    data = validate_error(resp, ApiErrorId.ERR_QUALIFICATION_NOT_CURRENT)
    assert data["error_id"] != ApiErrorId.ERR_SCHEDULE_OVERLAP


def test_cross_building_travel_buffer_boundary(api):
    """PRD §3.4: "The new window must survive the schedule-overlap rule against the para’s other `ACTIVE` assignments, else `ERR_SCHEDULE_OVERLAP`: two windows on a shared weekday in the *same* building conflict when they genuinely overlap, with bare adjacency (one window’s start equal to the other’s end) explicitly allowed; windows in *different* buildings conflict unless the gap between them is at least the plan’s `travel_buffer_minutes` on both sides — the first window must not begin before the second window’s end plus the buffer, and the second must not begin before the first window’s end plus the buffer."

    Design: Difficulty/resource_temporal_overlap/para_schedule_half_open_with_travel_buffer
    """
    plan, building, plan_v = create_active_plan()
    plan_id = plan["id"]
    b2 = validate_success(
        api.create_building(
            create_building_payload(plan_id, name="Jefferson Middle", building_code="JEF"),
            ADMIN,
        ),
        201,
    )
    p1 = create_para(plan_id, building["id"])
    s1 = create_active_student(plan_id, building["id"], iep_minutes_per_week=1500)
    create_active_assignment(plan_id, s1["id"], p1["id"], building["id"], plan_v)  # 480-780 at B1
    s2 = create_active_student(plan_id, b2["id"], iep_minutes_per_week=300)

    # Cross-building candidate starting 780 (gap 0 < 30 buffer) -> conflict
    resp = api.create_assignment(
        create_assignment_payload(
            plan_id, s2["id"], p1["id"], b2["id"], get_plan_version(plan_id),
            daily_start_minute=780, daily_end_minute=840,
        ),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_OVERLAP)

    # Cross-building candidate starting 810 (gap exactly 30 == buffer) -> allowed
    resp2 = api.create_assignment(
        create_assignment_payload(
            plan_id, s2["id"], p1["id"], b2["id"], get_plan_version(plan_id),
            daily_start_minute=810, daily_end_minute=870,
        ),
        COORD,
    )
    a2 = validate_success(resp2, 201)
    assert a2["status"] == "PROPOSED"


def test_weekly_cap_inclusive_at_equality_and_rejects_excess(api):
    """PRD §3.4: "Adding the assignment’s `weekly_minutes` to the para’s `weekly_scheduled_minutes` must not exceed `contracted_max_weekly_minutes`, else `ERR_WEEKLY_MINUTES_CAP_EXCEEDED`."

    Design: Corner/calculations/weekly_cap_enforced_and_boundary_allowed
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1, contracted_max_weekly_minutes=1500)
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=1500)
    # 300/day Mon-Fri = 1500 min/wk == cap exactly -> allowed
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    assert a1["weekly_minutes"] == 1500
    para = validate_success(api.get_para(p1["id"], ANY))
    assert para["weekly_scheduled_minutes"] == 1500

    # 1500 + 300 > 1500 -> rejected
    s2 = create_active_student(plan_id, b1, iep_minutes_per_week=300)
    resp = api.create_assignment(
        create_assignment_payload(
            plan_id, s2["id"], p1["id"], b1, get_plan_version(plan_id),
            daily_start_minute=800, daily_end_minute=860,
        ),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_WEEKLY_MINUTES_CAP_EXCEEDED)


def test_assignment_end_before_start_returns_invalid_date_range(api):
    """PRD §3.4: "the service window from `start_date` through `end_date`, where the end must not precede the start (else `ERR_INVALID_DATE_RANGE`); a non-empty `days_of_week` subset of `MON`, `TUE`, `WED`, `THU`, `FRI`, `SAT`, `SUN`; and the daily window from `daily_start_minute` to `daily_end_minute`, where the end must be strictly later than the start."

    Design: Corner/validations/assignment_end_before_start_returns_invalid_date_range
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=300)
    resp = api.create_assignment(
        create_assignment_payload(
            plan_id, s1["id"], p1["id"], b1, plan_v,
            start_date="2026-06-30", end_date="2026-05-04",
            days_of_week=["MON"], daily_start_minute=480, daily_end_minute=540,
        ),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_expired_qualification_rejected_under_default_clock(api):
    """PRD §2.4: "At server startup the logical clock reads exactly
    2026-05-01T00:00:00Z, and it continues to read that default until an
    administrator explicitly moves it."
    PRD §3.4: "The para must hold the `required_qualification_snapshot` current as of the current logical date — completed on or before it, unexpired, unrevoked — else `ERR_QUALIFICATION_NOT_CURRENT` (a snapshot of `NONE` is satisfied by every para)."

    Design: Corner/validations/qualification_expired_at_default_clock
    """
    # No set-clock call: the default logical clock is 2026-05-01T00:00:00Z
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    # Expired 2026-04-01 < default clock 2026-05-01 -> not current
    add_qualification(p1["id"], "BEHAVIOR_SUPPORT", "2025-01-10", expires_on="2026-04-01")
    s1 = create_active_student(
        plan_id, b1, iep_service_level="ONE_TO_ONE", required_qualification="BEHAVIOR_SUPPORT"
    )
    resp = api.create_assignment(
        create_assignment_payload(plan_id, s1["id"], p1["id"], b1, plan_v), COORD
    )
    validate_error(resp, ApiErrorId.ERR_QUALIFICATION_NOT_CURRENT)


def test_genuine_insufficient_budget_on_assignment_create(api):
    """PRD §3.4: "Finally the fiscal guard: the plan’s `committed_cost_cents` plus this candidate’s `projected_weekly_cost_cents` must not exceed `total_budget_cents` minus `settled_cost_cents`, else `ERR_INSUFFICIENT_BUDGET`."

    Design: Corner/validations/genuine_insufficient_budget_on_create
    """
    plan = validate_success(
        api.create_plan(create_plan_payload(total_budget_cents=1000), ADMIN), 201
    )
    building = validate_success(
        api.create_building(create_building_payload(plan["id"]), ADMIN), 201
    )
    activated = validate_success(api.activate_plan(plan["id"], ADMIN))
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    add_qualification(p1["id"], "BEHAVIOR_SUPPORT", "2026-01-10", expires_on="2027-01-10")
    s1 = create_active_student(
        plan_id, b1, iep_service_level="ONE_TO_ONE", required_qualification="BEHAVIOR_SUPPORT"
    )
    # Weekly 56250 > budget 1000 -> rejected (402)
    resp = api.create_assignment(
        create_assignment_payload(plan_id, s1["id"], p1["id"], b1, activated["version"]),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BUDGET)
    rows = validate_success(api.list_assignments(ANY, params={"plan_id": plan_id}))
    assert rows == []


def test_plan_state_error_beats_budget_error_in_reconciling(api):
    """PRD §2.7: "Ninth and last, the fiscal check: budget sufficiency is evaluated only after every other rule has passed, else `ERR_INSUFFICIENT_BUDGET`. Fiscal checks always run last so that a request failing both a structural rule and the budget surfaces the structural error."
    PRD §2.7: "the plan must be in a state allowing the operation (configuration writes need `DRAFT` or `ACTIVE`; assignment and coverage writes need `ACTIVE`; close needs `RECONCILING`) else `ERR_PLAN_NOT_ACTIVE`, `ERR_PLAN_NOT_DRAFT`, or `ERR_PLAN_NOT_RECONCILING"

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_priority_on_assignment_create
    """
    # RECONCILING plan with a 1-cent budget: both the plan-state check and the
    # fiscal check are armed; the structural state error must surface
    plan = create_plan(total_budget_cents=1)
    plan_id = plan["id"]
    building = validate_success(
        api.create_building(create_building_payload(plan_id), ADMIN), 201
    )
    validate_success(api.activate_plan(plan_id, ADMIN))
    # Roster writes require plan DRAFT or ACTIVE (PRD §3.1), so the para and
    # student must exist before reconciliation begins.
    p1 = create_para(plan_id, building["id"])
    s1 = create_active_student(plan_id, building["id"], iep_minutes_per_week=300)
    validate_success(api.begin_reconciliation(plan_id, ADMIN))

    resp = api.create_assignment(
        create_assignment_payload(
            plan_id, s1["id"], p1["id"], building["id"], get_plan_version(plan_id),
            days_of_week=["MON"], daily_start_minute=480, daily_end_minute=540,
        ),
        COORD,
    )
    data = validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
    assert data["error_id"] != ApiErrorId.ERR_INSUFFICIENT_BUDGET


def test_qualification_error_beats_schedule_overlap_on_resume(api):
    """PRD §3.5: "Resumption from `SUSPENDED` back to `ACTIVE` re-runs four checks, in the §2.7 order: the qualification re-check against the snapshot (else `ERR_QUALIFICATION_NOT_CURRENT`); the schedule re-check against the para’s other `ACTIVE` assignments under the same travel-buffer rule (else `ERR_SCHEDULE_OVERLAP`); the capacity re-check that the para’s `weekly_scheduled_minutes` plus the assignment’s `weekly_minutes` stays within `contracted_max_weekly_minutes` (else `ERR_WEEKLY_MINUTES_CAP_EXCEEDED`); and the budget re-check that the plan’s `committed_cost_cents` plus the assignment’s `projected_weekly_cost_cents` fits within `total_budget_cents` minus `settled_cost_cents` (else `ERR_INSUFFICIENT_BUDGET`, with `funding_status` flipping to `UNFUNDED` on failure)."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_priority_on_assignment_create
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    add_qualification(p1["id"], "BEHAVIOR_SUPPORT", "2026-01-10", expires_on="2027-01-10")
    s2 = create_active_student(
        plan_id, b1, iep_service_level="ONE_TO_ONE", required_qualification="BEHAVIOR_SUPPORT"
    )
    a2 = create_active_assignment(plan_id, s2["id"], p1["id"], b1, plan_v)  # 480-780

    # Revoke -> A2 auto-suspended; its window is released
    validate_success(api.revoke_qualification(p1["id"], {"qualification": "BEHAVIOR_SUPPORT"}, ADMIN))
    a2_mid = validate_success(api.get_assignment(a2["id"], ANY))
    assert a2_mid["status"] == "SUSPENDED"

    # A3 (no qualification needed) takes the same window and activates
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=1500)
    a3 = create_active_assignment(plan_id, s1["id"], p1["id"], b1)
    assert a3["status"] == "ACTIVE"

    # Resume violates BOTH qualification currency (revoked) and schedule overlap
    resp = api.resume_assignment(a2["id"], COORD)
    data = validate_error(resp, ApiErrorId.ERR_QUALIFICATION_NOT_CURRENT)
    assert data["error_id"] != ApiErrorId.ERR_SCHEDULE_OVERLAP


def test_same_building_adjacency_allowed_genuine_overlap_rejected(api):
    """PRD §3.4: "The new window must survive the schedule-overlap rule against the para’s other `ACTIVE` assignments, else `ERR_SCHEDULE_OVERLAP`: two windows on a shared weekday in the *same* building conflict when they genuinely overlap, with bare adjacency (one window’s start equal to the other’s end) explicitly allowed; windows in *different* buildings conflict unless the gap between them is at least the plan’s `travel_buffer_minutes` on both sides — the first window must not begin before the second window’s end plus the buffer, and the second must not begin before the first window’s end plus the buffer."

    Design: Difficulty/resource_temporal_overlap/para_schedule_half_open_with_travel_buffer
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=1500)
    create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)  # 480-780 at B1
    s2 = create_active_student(plan_id, b1, iep_minutes_per_week=300)

    # Bare adjacency in the SAME building (780 == 780) is explicitly allowed
    resp_ok = api.create_assignment(
        create_assignment_payload(
            plan_id, s2["id"], p1["id"], b1, get_plan_version(plan_id),
            daily_start_minute=780, daily_end_minute=840,
        ),
        COORD,
    )
    a2 = validate_success(resp_ok, 201)
    assert a2["status"] == "PROPOSED"

    # A genuine same-building overlap (600-840 vs 480-780) conflicts
    resp_bad = api.create_assignment(
        create_assignment_payload(
            plan_id, s2["id"], p1["id"], b1, get_plan_version(plan_id),
            daily_start_minute=600, daily_end_minute=840,
        ),
        COORD,
    )
    validate_error(resp_bad, ApiErrorId.ERR_SCHEDULE_OVERLAP)


def test_assignment_one_cent_over_budget_rejected(api):
    """PRD §3.4: "Finally the fiscal guard: the plan’s `committed_cost_cents` plus this candidate’s `projected_weekly_cost_cents` must not exceed `total_budget_cents` minus `settled_cost_cents`, else `ERR_INSUFFICIENT_BUDGET`."

    Design: Difficulty/boundary_precision_check/budget_exact_fit_allowed
    """
    plan = validate_success(
        api.create_plan(create_plan_payload(total_budget_cents=56_249), ADMIN), 201
    )
    building = validate_success(
        api.create_building(create_building_payload(plan["id"]), ADMIN), 201
    )
    activated = validate_success(api.activate_plan(plan["id"], ADMIN))
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    add_qualification(p1["id"], "BEHAVIOR_SUPPORT", "2026-01-10", expires_on="2027-01-10")
    s1 = create_active_student(
        plan_id, b1, iep_service_level="ONE_TO_ONE", required_qualification="BEHAVIOR_SUPPORT"
    )
    # weekly 56250 > total_budget 56249 by one cent -> rejected
    resp = api.create_assignment(
        create_assignment_payload(plan_id, s1["id"], p1["id"], b1, activated["version"]),
        COORD,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BUDGET)
    rows = validate_success(api.list_assignments(ANY, params={"plan_id": plan_id}))
    assert rows == []
