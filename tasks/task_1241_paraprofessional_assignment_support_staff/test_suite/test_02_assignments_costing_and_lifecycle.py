"""Assignment creation costing, guards, lifecycle, and parallel funding (PRD §3.4-§3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_assignment,
    create_active_assignment,
    create_active_plan,
    create_active_student,
    create_para,
    create_plan,
    create_student,
    create_verified_assignment,
    get_plan_version,
    propose_assignment,
    validate_error,
    validate_success,
    create_assignment_payload,
    create_building_payload,
    create_change_order_payload,
    create_plan_payload,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]


def test_assignment_create_initial_state_and_snapshots(api):
    """PRD §3.4: "An accepted proposal lands in `PROPOSED` with `funding_status` `PROVISIONALLY_FUNDED`, its projected cost is added to the plan’s `committed_cost_cents`, and the plan’s `version` increments by one."
    PRD §3.4: "The assignment’s `weekly_minutes` is the daily window length in minutes multiplied by the number of days in `days_of_week`."

    Design: Corner/state_machines/assignment_initial_and_parallel_funding_state
    """
    plan, building, plan_v = create_active_plan()
    p1 = create_para(plan["id"], building["id"])
    s1 = create_active_student(plan["id"], building["id"])

    resp = api.create_assignment(
        create_assignment_payload(plan["id"], s1["id"], p1["id"], building["id"], plan_v),
        COORD,
    )
    a1 = validate_success(resp, 201)
    assert_assignment(a1)
    assert a1["status"] == "PROPOSED"
    assert a1["funding_status"] == "PROVISIONALLY_FUNDED"
    assert a1["weekly_minutes"] == 1500  # (780 - 480) * 5 days
    # TRANSITIONAL / NONE at wage 2000: 300/60 * 2000 = 10000 per day
    assert a1["daily_cost_cents"] == 10000
    assert a1["service_level_snapshot"] == "TRANSITIONAL"
    assert a1["required_qualification_snapshot"] == "NONE"
    assert a1["base_wage_snapshot_cents"] == 2000


def test_assignment_create_response_carries_computed_costs_immediately(api):
    """PRD §3.4: "At creation the assignment snapshots three facts that will never again track their sources: `service_level_snapshot` from the student’s current `iep_service_level`, `required_qualification_snapshot` from the student’s current `required_qualification`, and `base_wage_snapshot_cents` from the para’s current `base_hourly_wage_cents`."
    PRD §3.4: "Fifth, the `daily_cost_cents` is the daily window length divided by sixty, multiplied by that effective rate, rounded half-up to integer cents — and only then is `projected_weekly_cost_cents` formed by multiplying the rounded day cost by the number of service days."

    Design: Corner/consistency_model/same_request_response_shows_computed_fields
    """
    plan, building, plan_v = create_active_plan()
    p1 = create_para(plan["id"], building["id"])
    s1 = create_active_student(
        plan["id"], building["id"], iep_service_level="ONE_TO_ONE", iep_minutes_per_week=1500
    )
    resp = api.create_assignment(
        create_assignment_payload(plan["id"], s1["id"], p1["id"], building["id"], plan_v),
        COORD,
    )
    a1 = validate_success(resp, 201)
    # The create response itself carries the computed costs (no re-read lag):
    # effective rate 2000 + 100 (ONE_TO_ONE stipend) = 2100; 300/60 * 2100 = 10500
    assert a1["daily_cost_cents"] == 10500
    assert a1["projected_weekly_cost_cents"] == 52500
    assert a1["weekly_minutes"] == 1500


def test_assignment_cost_counts_own_minutes_toward_benefit_threshold(api):
    """PRD §3.4: "First, project the para’s schedule: the para’s current `weekly_scheduled_minutes` over `ACTIVE` assignments plus this assignment’s own `weekly_minutes` — this assignment’s minutes deliberately count toward the threshold even though its cost is what is being computed."
    PRD §3.4: "Fourth, if the projected schedule is benefit-eligible, multiply the effective rate by one plus the plan’s `benefit_surcharge_pct`."

    Design: Difficulty/combinatorial_formula/assignment_cost_benefit_circular_order
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    # A1 ACTIVE: 304 min/day Mon-Fri (480-784) = 1520 min/wk
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=1520)
    a1 = create_active_assignment(
        plan_id, s1["id"], p1["id"], b1, plan_v,
        daily_start_minute=480, daily_end_minute=784,
    )
    s2 = create_active_student(plan_id, b1, iep_minutes_per_week=280)

    # A2: 56 min/day Mon-Fri = 280 min/wk -> projected 1520 + 280 = 1800 >= 1800
    resp = api.create_assignment(
        create_assignment_payload(
            plan_id, s2["id"], p1["id"], b1, get_plan_version(plan_id),
            daily_start_minute=800, daily_end_minute=856,
        ),
        COORD,
    )
    a2 = validate_success(resp, 201)
    # Eligibility projected WITH self: rate 2000 * 1.2 = 2400; 56/60 * 2400 = 2240
    assert a2["daily_cost_cents"] == 2240
    assert a2["projected_weekly_cost_cents"] == 2240 * 5  # 11200
    assert a2["daily_cost_cents"] != 1867  # value if eligibility excluded self
    validate_success(api.verify_qualifications(a2["id"], COORD))
    validate_success(api.activate_assignment(a2["id"], COORD))
    para = validate_success(api.get_para(p1["id"], ANY))
    assert para["weekly_scheduled_minutes"] == 1800
    assert para["benefit_eligible"] is True


def test_assignment_cost_rounds_per_day_then_sums(api):
    """PRD §2.6: "Assignment costing rounds each service day first and then
    multiplies by the number of service days in the week — the per-day figure is
    rounded half-up before any weekly aggregation."

    Design: Difficulty/combinatorial_formula/rounding_order_per_day_then_sum_vs_sum_then_round
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=335)
    # 67 min/day Mon-Fri at wage 2000: round_half_up(67/60 * 2000) = 2233 per day
    resp = api.create_assignment(
        create_assignment_payload(
            plan_id, s1["id"], p1["id"], b1, plan_v,
            daily_start_minute=480, daily_end_minute=547,
        ),
        COORD,
    )
    a1 = validate_success(resp, 201)
    assert a1["daily_cost_cents"] == 2233
    assert a1["projected_weekly_cost_cents"] == 11165  # 2233 * 5, not 11167


def test_provisional_allocation_rounds_once_at_end_with_hardship(api):
    """PRD §2.6: "Funding-allocation math, by contrast, sums exact values and
    rounds half-up exactly once at the very end of each variant's computation."
    PRD §3.1: "The building’s raw amount is the `base_grant_cents` plus that service sum multiplied by `per_minute_rate_cents` and by the formula’s `period_weeks`; this raw amount is rounded half-up to integer cents first, and only then multiplied by the building’s `hardship_factor`, with the product rounded half-up once more to yield `provisional_amount_cents`."

    Design: Difficulty/combinatorial_formula/rounding_order_per_day_then_sum_vs_sum_then_round
    """
    plan = validate_success(
        api.create_plan(create_plan_payload(), ADMIN), 201
    )
    building = validate_success(
        api.create_building(
            create_building_payload(plan["id"], name="Jefferson Middle",
                                    building_code="JEF", hardship_factor=1.25),
            ADMIN,
        ),
        201,
    )
    activated = validate_success(api.activate_plan(plan["id"], ADMIN))
    plan_id = plan["id"]
    create_active_student(plan_id, building["id"], iep_minutes_per_week=335)
    formula = validate_success(
        api.create_formula(
            {"plan_id": plan_id, "base_grant_cents": 100000, "per_minute_rate_cents": 5,
             "weight_one_to_one": 1.0, "weight_shared_support": 0.6,
             "weight_transitional": 0.4, "period_weeks": 1},
            ADMIN,
        ),
        201,
    )
    validate_success(api.publish_formula(formula["id"], ADMIN))
    rows = validate_success(
        api.compute_allocations({"formula_id": formula["id"], "period_label": "2026-W19"}, ADMIN),
        201,
    )
    assert isinstance(rows, list) and len(rows) == 1
    # raw = 100000 + (335*0.4)*5*1 = 100670; 100670 * 1.25 = 125837.5 -> 125838
    assert rows[0]["provisional_amount_cents"] == 125838


def test_suspend_from_proposed_returns_invalid_state(api):
    """PRD §3.5: "Suspension moves an `ACTIVE` assignment to `SUSPENDED`, whether a `SpecialEdCoordinator` initiates it directly or the system fires it through the qualification revoke-or-expire cascade of §3.3."
    PRD §3.4: "attempting any assignment transition from a state that does not declare it is rejected with `ERR_ASSIGNMENT_INVALID_STATE`."

    Design: Corner/state_machines/assignment_suspend_from_proposed_returns_invalid_state
    """
    plan, building, plan_v = create_active_plan()
    p1 = create_para(plan["id"], building["id"])
    s1 = create_active_student(plan["id"], building["id"])
    a1 = propose_assignment(plan["id"], s1["id"], p1["id"], building["id"], plan_v)
    assert a1["status"] == "PROPOSED"

    resp = api.suspend_assignment(a1["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)
    after = validate_success(api.get_assignment(a1["id"], ANY))
    assert after["status"] == "PROPOSED"


def test_ended_assignment_is_terminal(api):
    """PRD §3.5: "Ending moves an assignment from any non-terminal state to `ENDED`, with `end_reason` set to `COORDINATOR_ENDED` when a coordinator ends it directly, `SERVICE_CHANGED` under a service change order, or `PLAN_CLOSED` at plan close; the field is null on live assignments."
    PRD §3.4: "attempting any assignment transition from a state that does not declare it is rejected with `ERR_ASSIGNMENT_INVALID_STATE`."

    Design: Corner/state_machines/assignment_terminal_lockdown
    """
    plan, building, plan_v = create_active_plan()
    p1 = create_para(plan["id"], building["id"])
    s1 = create_active_student(plan["id"], building["id"])
    a1 = propose_assignment(plan["id"], s1["id"], p1["id"], building["id"], plan_v)
    ended = validate_success(api.end_assignment(a1["id"], COORD))
    assert ended["status"] == "ENDED"

    resp = api.suspend_assignment(a1["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)
    after = validate_success(api.get_assignment(a1["id"], ANY))
    assert after["status"] == "ENDED"
    assert after["funding_status"] == "SETTLED"


def test_assignment_end_before_activation_restores_plan_ledger(api):
    """PRD §3.5: "The release depends on the departing state: from `PROPOSED` or `QUALIFICATION_VERIFIED`, the plan’s `committed_cost_cents` releases the projected cost; from `ACTIVE`, the para’s `weekly_scheduled_minutes` and benefit flag release and recompute as well; from `SUSPENDED`, both releases already happened at suspension. Every ending, regardless of path, moves `funding_status` to `SETTLED`."

    Design: Difficulty/compensating_invariant/committed_cost_round_trip_no_drift
    """
    plan = validate_success(
        api.create_plan(create_plan_payload(total_budget_cents=1_000_000), ADMIN), 201
    )
    building = validate_success(
        api.create_building(create_building_payload(plan["id"]), ADMIN), 201
    )
    activated = validate_success(api.activate_plan(plan["id"], ADMIN))
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    from test_helpers import add_qualification
    add_qualification(p1["id"], "BEHAVIOR_SUPPORT", "2026-01-10", expires_on="2027-01-10")
    s1 = create_active_student(
        plan_id, b1, iep_service_level="ONE_TO_ONE", required_qualification="BEHAVIOR_SUPPORT"
    )
    # 300/day Mon-Fri at rate 2250 (2000 + 150 BEHAVIOR_SUPPORT + 100 ONE_TO_ONE):
    # daily 11250, weekly 56250
    a1 = propose_assignment(plan_id, s1["id"], p1["id"], b1, activated["version"])
    mid = validate_success(api.get_plan(plan_id, ANY))
    assert mid["committed_cost_cents"] == 56250

    ended = validate_success(api.end_assignment(a1["id"], COORD))
    assert ended["status"] == "ENDED"
    assert ended["funding_status"] == "SETTLED"
    final = validate_success(api.get_plan(plan_id, ANY))
    assert final["committed_cost_cents"] == 0
    assert final["cost_balance_cents"] == 1_000_000


def test_activate_rejected_while_student_service_change_pending(api):
    """PRD §3.4: "The student must currently be `ACTIVE_IEP` (else `ERR_STUDENT_NOT_ASSIGNABLE`), and the funding gate must pass: the assignment’s `funding_status` must still read `PROVISIONALLY_FUNDED`, and the plan’s `committed_cost_cents` — which has included this assignment’s projected cost since proposal — must not exceed `total_budget_cents` minus `settled_cost_cents`."

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_gated_by_student_state
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1)
    a1 = create_verified_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    sco = validate_success(
        api.create_change_order(
            create_change_order_payload(
                s1["id"], "MINUTES_CHANGE", "IEP revision", new_minutes_per_week=900
            ),
            COORD,
        ),
        201,
    )

    resp = api.activate_assignment(a1["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_ASSIGNABLE)
    after = validate_success(api.get_assignment(a1["id"], ANY))
    assert after["status"] == "QUALIFICATION_VERIFIED"
    student = validate_success(api.get_student(s1["id"], ANY))
    assert student["status"] == "SERVICE_CHANGE_PENDING"


def test_failed_resume_moves_only_funding_axis_then_auto_refund(api):
    """PRD §3.5: "The funding dimension is parallel to and independent of the workflow status. An assignment is born `PROVISIONALLY_FUNDED`; successful activation moves it to `FUNDED`; a failed funding gate at activation moves it to `UNFUNDED`, as does a failed budget re-check at resumption from `FUNDED`; and ending settles it — `PROVISIONALLY_FUNDED` to `SETTLED` when ended from `PROPOSED` or `QUALIFICATION_VERIFIED`, `FUNDED` to `SETTLED` when ended from `ACTIVE` or `SUSPENDED`."
    PRD §3.5: "One recovery path exists: after every committed-cost release on the plan, the system reconsiders the plan’s `UNFUNDED` assignments in `created_at` order, earliest first, and any whose `projected_weekly_cost_cents` fits again within the remaining budget returns to `PROVISIONALLY_FUNDED`."

    Design: Difficulty/non_linear_state_machine/assignment_parallel_status_x_funding
    """
    plan = validate_success(
        api.create_plan(create_plan_payload(total_budget_cents=110_000), ADMIN), 201
    )
    building = validate_success(
        api.create_building(create_building_payload(plan["id"]), ADMIN), 201
    )
    activated = validate_success(api.activate_plan(plan["id"], ADMIN))
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1, full_name="Para One", hire_date="2025-08-15")
    p2 = create_para(plan_id, b1, full_name="Para Two", hire_date="2025-08-16")
    p3 = create_para(plan_id, b1, full_name="Para Three", hire_date="2025-08-17")
    # ONE_TO_ONE at wage 2000: effective rate 2100, daily 10500, weekly 52500
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE", student_ref="STU-1")
    s2 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE", student_ref="STU-2")
    s3 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE", student_ref="STU-3")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, activated["version"])
    a2 = create_active_assignment(plan_id, s2["id"], p2["id"], b1)  # committed now 105000
    validate_success(api.suspend_assignment(a2["id"], COORD))        # committed back to 52500
    a3 = propose_assignment(plan_id, s3["id"], p3["id"], b1)         # committed 105000 again

    # Resume A2 fails the budget re-check: status stays SUSPENDED, funding flips
    resp = api.resume_assignment(a2["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BUDGET)
    a2_after = validate_success(api.get_assignment(a2["id"], ANY))
    assert a2_after["status"] == "SUSPENDED"
    assert a2_after["funding_status"] == "UNFUNDED"

    # Ending A3 releases committed cost -> bubble-up re-fund flips A2 back
    validate_success(api.end_assignment(a3["id"], COORD))
    a2_refunded = validate_success(api.get_assignment(a2["id"], ANY))
    assert a2_refunded["status"] == "SUSPENDED"
    assert a2_refunded["funding_status"] == "PROVISIONALLY_FUNDED"

    # Now the budget re-check passes: resume succeeds on both axes
    resumed = validate_success(api.resume_assignment(a2["id"], COORD))
    assert resumed["status"] == "ACTIVE"
    assert resumed["funding_status"] == "FUNDED"


def test_benefit_threshold_exactly_1800_is_eligible(api):
    """PRD §3.5: "The stored `benefit_eligible` flag is this load compared against the plan’s `benefit_threshold_minutes`: at or above the threshold the flag is true, below it the flag is false."
    PRD §3.4: "A successful activation locks `daily_cost_cents` permanently against any further recompute, moves `funding_status` to `FUNDED`, adds the assignment’s `weekly_minutes` to the para’s `weekly_scheduled_minutes`, and recomputes the para’s `benefit_eligible`."

    Design: Difficulty/boundary_precision_check/benefit_threshold_exact_1800_is_eligible
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=1500)
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)  # 1500 min/wk
    s2 = create_active_student(plan_id, b1, iep_minutes_per_week=300)
    a2 = create_verified_assignment(
        plan_id, s2["id"], p1["id"], b1,
        daily_start_minute=800, daily_end_minute=860,  # 60 min/day * 5 = 300 min/wk
    )
    activated = validate_success(api.activate_assignment(a2["id"], COORD))
    # daily cost locked at surcharged rate: 60/60 * (2000 * 1.2) = 2400
    assert activated["daily_cost_cents"] == 2400
    assert activated["funding_status"] == "FUNDED"
    para = validate_success(api.get_para(p1["id"], ANY))
    assert para["weekly_scheduled_minutes"] == 1800  # exactly the threshold
    assert para["benefit_eligible"] is True


def test_assignment_create_at_exact_budget_fit_is_allowed(api):
    """PRD §3.4: "Finally the fiscal guard: the plan’s `committed_cost_cents` plus this candidate’s `projected_weekly_cost_cents` must not exceed `total_budget_cents` minus `settled_cost_cents`, else `ERR_INSUFFICIENT_BUDGET`."
    PRD §2.9: "cost_balance_cents` is what remains: the plan’s `total_budget_cents` minus `committed_cost_cents` minus `settled_cost_cents`."

    Design: Difficulty/boundary_precision_check/budget_exact_fit_allowed
    """
    plan = validate_success(
        api.create_plan(create_plan_payload(total_budget_cents=56_250), ADMIN), 201
    )
    building = validate_success(
        api.create_building(create_building_payload(plan["id"]), ADMIN), 201
    )
    activated = validate_success(api.activate_plan(plan["id"], ADMIN))
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    from test_helpers import add_qualification
    add_qualification(p1["id"], "BEHAVIOR_SUPPORT", "2026-01-10", expires_on="2027-01-10")
    s1 = create_active_student(
        plan_id, b1, iep_service_level="ONE_TO_ONE", required_qualification="BEHAVIOR_SUPPORT"
    )
    # weekly 56250 == total_budget 56250 exactly -> must succeed (<= is inclusive)
    resp = api.create_assignment(
        create_assignment_payload(plan_id, s1["id"], p1["id"], b1, activated["version"]),
        COORD,
    )
    a1 = validate_success(resp, 201)
    assert_assignment(a1)
    plan_after = validate_success(api.get_plan(plan_id, ANY))
    assert plan_after["committed_cost_cents"] == 56250
    assert plan_after["cost_balance_cents"] == 0


def test_assignment_cost_below_threshold_applies_no_surcharge(api):
    """PRD §3.4: "Second, compare that projection to the plan’s `benefit_threshold_minutes`: at or above means benefit-eligible for costing purposes."
    PRD §3.4: "Fourth, if the projected schedule is benefit-eligible, multiply the effective rate by one plus the plan’s `benefit_surcharge_pct`."

    Design: Difficulty/combinatorial_formula/assignment_cost_benefit_circular_order
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    # A1 ACTIVE: 304 min/day Mon-Fri = 1520 min/wk
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=1520)
    create_active_assignment(
        plan_id, s1["id"], p1["id"], b1, plan_v,
        daily_start_minute=480, daily_end_minute=784,
    )
    s2 = create_active_student(plan_id, b1, iep_minutes_per_week=270)
    # A2: 54 min/day Mon-Fri (800-854) = 270 min/wk; projected 1520+270 = 1790 < 1800
    resp = api.create_assignment(
        create_assignment_payload(
            plan_id, s2["id"], p1["id"], b1, get_plan_version(plan_id),
            daily_start_minute=800, daily_end_minute=854,
        ),
        COORD,
    )
    a2 = validate_success(resp, 201)
    # No surcharge: 54/60 * 2000 = 1800 per day
    assert a2["daily_cost_cents"] == 1800
    assert a2["projected_weekly_cost_cents"] == 9000
    assert a2["daily_cost_cents"] != 2160  # the surcharged value


def test_benefit_flag_false_one_minute_below_threshold(api):
    """PRD §3.5: "The stored `benefit_eligible` flag is this load compared against the plan’s `benefit_threshold_minutes`: at or above the threshold the flag is true, below it the flag is false."

    Design: Difficulty/boundary_precision_check/benefit_threshold_exact_1800_is_eligible
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_minutes_per_week=1500)
    create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)  # 1500 min/wk
    s2 = create_active_student(plan_id, b1, iep_minutes_per_week=299)
    # A2: 299 min on Mondays only -> 1500 + 299 = 1799 < 1800
    a2 = create_active_assignment(
        plan_id, s2["id"], p1["id"], b1,
        days_of_week=["MON"], daily_start_minute=800, daily_end_minute=1099,
    )
    assert a2["weekly_minutes"] == 299
    para = validate_success(api.get_para(p1["id"], ANY))
    assert para["weekly_scheduled_minutes"] == 1799
    assert para["benefit_eligible"] is False


def test_end_from_suspended_settles_funding_without_double_release(api):
    """PRD §3.5: "Suspension releases the assignment’s `weekly_minutes` from the para’s `weekly_scheduled_minutes`, recomputes the para’s `benefit_eligible`, and subtracts the assignment’s `projected_weekly_cost_cents` from the plan’s `committed_cost_cents`; the `funding_status` stays `FUNDED` throughout."
    PRD §3.5: "Every ending, regardless of path, moves `funding_status` to `SETTLED`."

    Design: Difficulty/non_linear_state_machine/assignment_parallel_status_x_funding
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)

    suspended = validate_success(api.suspend_assignment(a1["id"], COORD))
    assert suspended["status"] == "SUSPENDED"
    assert suspended["funding_status"] == "FUNDED"  # funding axis unmoved by suspend
    para_mid = validate_success(api.get_para(p1["id"], ANY))
    assert para_mid["weekly_scheduled_minutes"] == 0

    ended = validate_success(api.end_assignment(a1["id"], COORD))
    assert ended["status"] == "ENDED"
    assert ended["funding_status"] == "SETTLED"
    para_end = validate_success(api.get_para(p1["id"], ANY))
    assert para_end["weekly_scheduled_minutes"] == 0  # not double-released
    plan_end = validate_success(api.get_plan(plan_id, ANY))
    assert plan_end["committed_cost_cents"] == 0


def test_suspend_resume_round_trip_restores_committed_without_drift(api):
    """PRD §3.5: "Suspension releases the assignment’s `weekly_minutes` from the para’s `weekly_scheduled_minutes`, recomputes the para’s `benefit_eligible`, and subtracts the assignment’s `projected_weekly_cost_cents` from the plan’s `committed_cost_cents`; the `funding_status` stays `FUNDED` throughout."
    PRD §3.5: "Success re-adds the weekly minutes and recomputes benefit eligibility, and re-adds the projected cost to the plan’s committed figure."

    Design: Difficulty/compensating_invariant/committed_cost_round_trip_no_drift
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)  # weekly 52500

    mid = validate_success(api.get_plan(plan_id, ANY))
    assert mid["committed_cost_cents"] == 52500
    validate_success(api.suspend_assignment(a1["id"], COORD))
    released = validate_success(api.get_plan(plan_id, ANY))
    assert released["committed_cost_cents"] == 0
    resumed = validate_success(api.resume_assignment(a1["id"], COORD))
    assert resumed["status"] == "ACTIVE"
    restored = validate_success(api.get_plan(plan_id, ANY))
    assert restored["committed_cost_cents"] == 52500  # full compensation, no drift
    assert restored["cost_balance_cents"] == restored["total_budget_cents"] - 52500


def test_activation_succeeds_once_student_returns_to_active_iep(api):
    """PRD §3.2: "Cancelling an order, from either `FILED` or `APPROVED`, moves it to `CANCELLED` and simply returns the student to `ACTIVE_IEP` with no assignment impact."
    PRD §3.4: "The student must currently be `ACTIVE_IEP` (else `ERR_STUDENT_NOT_ASSIGNABLE`), and the funding gate must pass: the assignment’s `funding_status` must still read `PROVISIONALLY_FUNDED`, and the plan’s `committed_cost_cents` — which has included this assignment’s projected cost since proposal — must not exceed `total_budget_cents` minus `settled_cost_cents`."

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_gated_by_student_state
    """
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1)
    a1 = create_verified_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    sco = validate_success(
        api.create_change_order(
            create_change_order_payload(s1["id"], "MINUTES_CHANGE", "IEP revision",
                                        new_minutes_per_week=900),
            COORD,
        ),
        201,
    )
    blocked = api.activate_assignment(a1["id"], COORD)
    validate_error(blocked, ApiErrorId.ERR_STUDENT_NOT_ASSIGNABLE)

    # Cancelling the order returns the student to ACTIVE_IEP; the gate then passes
    validate_success(api.cancel_change_order(sco["id"], COORD))
    student = validate_success(api.get_student(s1["id"], ANY))
    assert student["status"] == "ACTIVE_IEP"
    activated = validate_success(api.activate_assignment(a1["id"], COORD))
    assert activated["status"] == "ACTIVE"
    assert activated["funding_status"] == "FUNDED"
