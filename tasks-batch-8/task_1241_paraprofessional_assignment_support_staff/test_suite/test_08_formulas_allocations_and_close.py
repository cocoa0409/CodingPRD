"""Allocation formulas, provisional/final funding variants, and plan close
(PRD §3.1, §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_assignment,
    create_active_plan,
    create_active_student,
    create_change_order_payload,
    create_formula_payload,
    create_para,
    create_published_formula,
    create_student,
    log_and_approve_timesheet,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
ANY = TEST_USERS["any_headers"]


def test_compute_requires_published_formula(api):
    """PRD §3.1: "The computation requires the formula to be `PUBLISHED` (else `ERR_FORMULA_NOT_PUBLISHED`) and may run only once per pairing of formula and period label (else `ERR_ALLOCATIONS_ALREADY_COMPUTED`)."

    Design: Corner/endpoints/compute_requires_published_formula
    """
    plan, building, _ = create_active_plan()
    formula = validate_success(
        api.create_formula(create_formula_payload(plan["id"]), ADMIN), 201
    )
    assert formula["status"] == "DRAFT"
    resp = api.compute_allocations(
        {"formula_id": formula["id"], "period_label": "2026-W19"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_FORMULA_NOT_PUBLISHED)


def test_compute_twice_for_same_period_rejected(api):
    """PRD §3.1: "The computation requires the formula to be `PUBLISHED` (else `ERR_FORMULA_NOT_PUBLISHED`) and may run only once per pairing of formula and period label (else `ERR_ALLOCATIONS_ALREADY_COMPUTED`)."

    Design: Corner/endpoints/compute_twice_same_period_rejected
    """
    plan, building, _ = create_active_plan()
    formula = create_published_formula(plan["id"])
    validate_success(
        api.compute_allocations({"formula_id": formula["id"], "period_label": "2026-W19"}, ADMIN),
        201,
    )
    resp = api.compute_allocations(
        {"formula_id": formula["id"], "period_label": "2026-W19"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_ALLOCATIONS_ALREADY_COMPUTED)


def test_formula_publish_supersedes_prior_and_versions_sequence(api):
    """PRD §3.1: "Each formula receives a `version_no` assigned as one more than the highest existing `version_no` for the plan, starting at 1, and begins life in `DRAFT`. Publishing a formula moves it from `DRAFT` to `PUBLISHED` and automatically moves any other `PUBLISHED` formula of the same plan to `SUPERSEDED`, so at most one formula is ever live per plan."

    Design: Corner/endpoints/formula_publish_supersedes_prior
    """
    plan, building, _ = create_active_plan()
    f1 = validate_success(api.create_formula(create_formula_payload(plan["id"]), ADMIN), 201)
    assert f1["version_no"] == 1
    validate_success(api.publish_formula(f1["id"], ADMIN))
    f2 = validate_success(
        api.create_formula(
            create_formula_payload(plan["id"], base_grant_cents=120000, per_minute_rate_cents=6),
            ADMIN,
        ),
        201,
    )
    assert f2["version_no"] == 2
    published2 = validate_success(api.publish_formula(f2["id"], ADMIN))
    assert published2["status"] == "PUBLISHED"
    f1_after = validate_success(api.get_formula(f1["id"], ANY))
    assert f1_after["status"] == "SUPERSEDED"


def test_provisional_allocation_excludes_exited_students(api):
    """PRD §3.1: "A row’s `provisional_amount_cents` projects entitlement-driven funding: take the building’s students whose status is `REGISTERED`, `ACTIVE_IEP`, or `SERVICE_CHANGE_PENDING` (students who have `EXITED` are excluded), multiply each student’s current `iep_minutes_per_week` by the weight matching their current `iep_service_level`, and sum those weighted minutes into a service sum."

    Design: Corner/calculations/allocation_input_set_excludes_exited_student
    """
    plan, building, _ = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    sa = create_active_student(
        plan_id, b1, student_ref="STU-A", iep_service_level="ONE_TO_ONE",
        iep_minutes_per_week=1500,
    )
    sb = create_active_student(
        plan_id, b1, student_ref="STU-B", iep_service_level="SHARED_SUPPORT",
        iep_minutes_per_week=900,
    )
    # Exit SB via service change order before compute
    sco = validate_success(
        api.create_change_order(
            create_change_order_payload(sb["id"], "EXIT", "leaves district"), COORD
        ),
        201,
    )
    validate_success(api.approve_change_order(sco["id"], ADMIN))
    validate_success(api.effectuate_change_order(sco["id"], COORD))
    sb_after = validate_success(api.get_student(sb["id"], ANY))
    assert sb_after["status"] == "EXITED"

    formula = create_published_formula(plan_id)
    rows = validate_success(
        api.compute_allocations({"formula_id": formula["id"], "period_label": "2026-W19"}, ADMIN),
        201,
    )
    assert len(rows) == 1
    # 100000 + (1500*1.0) * 5 * 1 = 107500; SB's 900*0.6 excluded
    assert rows[0]["provisional_amount_cents"] == 107500


def test_close_blocked_by_submitted_timesheet(api):
    """PRD §3.9: "Close is gated on two aggregate conditions, evaluated in the §2.7 order: no timesheet entry for the plan may remain in `SUBMITTED` (else `ERR_UNRESOLVED_TIMESHEETS`), and no coverage plan may remain in `DRAFT`, `PUBLISHED`, or `LOCKED` — every one must be `RECONCILED` (else `ERR_UNRECONCILED_COVERAGE_PLANS`)."

    Design: Corner/endpoints/close_blocked_by_submitted_timesheet
    """
    from test_helpers import log_timesheet, submit_timesheet

    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    t1 = log_timesheet(a1["id"], p1["id"], "2026-05-04", 480, 780)
    submit_timesheet(t1["id"], p1["id"])  # SUBMITTED, not approved
    validate_success(api.begin_reconciliation(plan_id, ADMIN))

    resp = api.close_plan(plan_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_TIMESHEETS)
    after = validate_success(api.get_plan(plan_id, ANY))
    assert after["status"] == "RECONCILING"


def test_close_blocked_by_unreconciled_coverage_plan(api):
    """PRD §3.9: "Close is gated on two aggregate conditions, evaluated in the §2.7 order: no timesheet entry for the plan may remain in `SUBMITTED` (else `ERR_UNRESOLVED_TIMESHEETS`), and no coverage plan may remain in `DRAFT`, `PUBLISHED`, or `LOCKED` — every one must be `RECONCILED` (else `ERR_UNRECONCILED_COVERAGE_PLANS`)."

    Design: Corner/endpoints/close_blocked_by_unreconciled_coverage_plan
    """
    from test_helpers import create_coverage_plan_payload

    plan, building, _ = create_active_plan()
    cp = validate_success(
        api.create_coverage_plan(
            create_coverage_plan_payload(plan["id"], building["id"], "2026-05-06"), COORD
        ),
        201,
    )
    validate_success(api.publish_coverage_plan(cp["id"], COORD))  # PUBLISHED, not RECONCILED
    validate_success(api.begin_reconciliation(plan["id"], ADMIN))

    resp = api.close_plan(plan["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_UNRECONCILED_COVERAGE_PLANS)


def test_plan_close_computes_confirmed_benefit_variance_and_final_allocation(api):
    """PRD §3.9: "The para’s `confirmed_benefit_eligible` is true when at least one such week reached the plan’s `benefit_threshold_minutes`, and false otherwise. The `benefit_variance_cents` claws back surcharge that was provisionally charged but never confirmed: for each ISO week in which the para had at least one assignment `ACTIVE` and the week’s approved minutes fell below the threshold, each such assignment contributes its locked `projected_weekly_cost_cents` minus the same weekly cost recomputed at the non-surcharged effective rate; assignments that were originally costed while the para was ineligible contribute zero, because no surcharge was ever charged on them."
    PRD §3.5: "The stored `benefit_eligible` flag is this load compared against the plan’s `benefit_threshold_minutes`: at or above the threshold the flag is true, below it the flag is false."

    Design: Difficulty/dual_variant_calc/benefit_eligibility_provisional_vs_confirmed
    """
    validate_success(api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN))
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(
        plan_id, b1, iep_service_level="SHARED_SUPPORT", iep_minutes_per_week=1900
    )
    # A1 ACTIVE: 380 min/day Mon-Fri 2026-05-04..05-08 -> 1900 scheduled (>= 1800);
    # surcharged rate 2400 -> locked daily 15200, locked weekly 76000
    a1 = create_active_assignment(
        plan_id, s1["id"], p1["id"], b1, plan_v,
        start_date="2026-05-04", end_date="2026-05-08",
        daily_start_minute=480, daily_end_minute=860,
    )
    assert a1["projected_weekly_cost_cents"] == 76000

    # Approved work falls short: five days x 340 min (480-820) = 1700 < 1800
    for day in ("2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08"):
        log_and_approve_timesheet(a1["id"], p1["id"], day, 480, 820)
    validate_success(api.set_clock({"to_iso8601": "2026-05-11T00:00:00Z"}, ADMIN))

    # Provisional variant during operation: scheduled 1900 >= 1800
    para_pre = validate_success(api.get_para(p1["id"], ANY))
    assert para_pre["benefit_eligible"] is True
    assert para_pre["weekly_scheduled_minutes"] == 1900

    validate_success(api.begin_reconciliation(plan_id, ADMIN))
    closed = validate_success(api.close_plan(plan_id, ADMIN))
    assert closed["status"] == "CLOSED"

    # Confirmed variant at close: 1700 < 1800 -> not confirmed; surcharge clawed back
    para_post = validate_success(api.get_para(p1["id"], ANY))
    assert para_post["confirmed_benefit_eligible"] is False
    assert para_post["benefit_variance_cents"] == 12665  # 76000 - 63335


def test_plan_close_finalizes_allocations_from_approved_minutes(api):
    """PRD §3.9: "Its `final_amount_cents` replays approved labor instead of entitlements: sum `minutes_worked` over `APPROVED` timesheets, map each entry through its assignment’s `student_id` to the student whose *current* building is this row’s building, and weight each student’s minutes by the student’s *current* service-level weight. The raw amount is the `base_grant_cents` plus those weighted minutes multiplied by `per_minute_rate_cents` — the formula’s `period_weeks` is deliberately not applied to actuals — rounded half-up once, then multiplied by the building’s `hardship_factor` and rounded half-up once more at the very end, per the round-once regime of §2.6. The row’s `variance_cents` is the final amount minus the provisional amount, negative when delivery fell short of entitlement, and the row moves from `PROVISIONAL` to `FINALIZED`."

    Design: Difficulty/dual_variant_calc/building_allocation_provisional_vs_final
    """
    validate_success(api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN))
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1, full_name="Pat Para", hire_date="2025-08-15")
    p2 = create_para(plan_id, b1, full_name="Sam Sub", hire_date="2025-09-01")
    sa = create_active_student(
        plan_id, b1, student_ref="STU-A", iep_service_level="ONE_TO_ONE",
        iep_minutes_per_week=1500,
    )
    sb = create_active_student(
        plan_id, b1, student_ref="STU-B", iep_service_level="SHARED_SUPPORT",
        iep_minutes_per_week=900,
    )
    formula = create_published_formula(plan_id)
    rows = validate_success(
        api.compute_allocations({"formula_id": formula["id"], "period_label": "2026-W19"}, ADMIN),
        201,
    )
    assert len(rows) == 1
    alloc_id = rows[0]["id"]
    # Provisional: 100000 + (1500*1.0 + 900*0.6) * 5 * 1 = 110200
    assert rows[0]["provisional_amount_cents"] == 110200

    a_a = create_active_assignment(
        plan_id, sa["id"], p1["id"], b1, plan_v,
        start_date="2026-05-04", end_date="2026-05-08",
    )
    a_b = create_active_assignment(
        plan_id, sb["id"], p2["id"], b1,
        start_date="2026-05-04", end_date="2026-05-08",
        daily_start_minute=480, daily_end_minute=660,
    )
    # Approved actuals fall short of entitlement: A 4x300=1200, B 3x180=540
    for day in ("2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07"):
        log_and_approve_timesheet(a_a["id"], p1["id"], day, 480, 780)
    for day in ("2026-05-04", "2026-05-05", "2026-05-06"):
        log_and_approve_timesheet(a_b["id"], p2["id"], day, 480, 660)
    validate_success(api.set_clock({"to_iso8601": "2026-05-11T00:00:00Z"}, ADMIN))

    validate_success(api.begin_reconciliation(plan_id, ADMIN))
    closed = validate_success(api.close_plan(plan_id, ADMIN))
    assert closed["status"] == "CLOSED"

    alloc = validate_success(api.get_allocation(alloc_id, ANY))
    # Final: 100000 + (1200*1.0 + 540*0.6) * 5 = 107620 (period_weeks not applied)
    assert alloc["final_amount_cents"] == 107620
    assert alloc["variance_cents"] == -2580  # 107620 - 110200
    assert alloc["status"] == "FINALIZED"


def test_compute_produces_one_provisional_row_per_building(api):
    """PRD §3.1: "It produces one funding-allocation row per building of the plan, each pinned to the formula version used at compute time and starting in `PROVISIONAL`."
    PRD §3.1: "The building’s raw amount is the `base_grant_cents` plus that service sum multiplied by `per_minute_rate_cents` and by the formula’s `period_weeks`; this raw amount is rounded half-up to integer cents first, and only then multiplied by the building’s `hardship_factor`, with the product rounded half-up once more to yield `provisional_amount_cents`."

    Design: Difficulty/dual_variant_calc/building_allocation_provisional_vs_final
    """
    from test_helpers import create_building_payload

    plan, building, _ = create_active_plan()
    plan_id = plan["id"]
    b2 = validate_success(
        api.create_building(
            create_building_payload(plan_id, name="Jefferson Middle", building_code="JEF"),
            ADMIN,
        ),
        201,
    )
    create_active_student(
        plan_id, building["id"], student_ref="STU-A", iep_service_level="ONE_TO_ONE",
        iep_minutes_per_week=1500,
    )
    create_active_student(
        plan_id, b2["id"], student_ref="STU-B", iep_service_level="SHARED_SUPPORT",
        iep_minutes_per_week=900,
    )
    formula = create_published_formula(plan_id)
    rows = validate_success(
        api.compute_allocations({"formula_id": formula["id"], "period_label": "2026-W19"}, ADMIN),
        201,
    )
    assert len(rows) == 2  # one row per building of the plan
    by_building = {r["building_id"]: r for r in rows}
    assert by_building[building["id"]]["provisional_amount_cents"] == 107500
    assert by_building[b2["id"]]["provisional_amount_cents"] == 102700
    for row in rows:
        assert row["formula_id"] == formula["id"]  # pinned to the formula version
        assert row["status"] == "PROVISIONAL"


def test_close_ends_active_assignments_with_plan_closed_reason(api):
    """PRD §3.9: "Every assignment still `ACTIVE` or `SUSPENDED` is ended with `end_reason` `PLAN_CLOSED` and its committed share released, and the plan’s `version` increments by one."
    PRD §3.5: "The stored `benefit_eligible` flag is this load compared against the plan’s `benefit_threshold_minutes`: at or above the threshold the flag is true, below it the flag is false."

    Design: Difficulty/dual_variant_calc/benefit_eligibility_provisional_vs_confirmed
    """
    validate_success(api.set_clock({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN))
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1, iep_service_level="ONE_TO_ONE")
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v)
    pre = validate_success(api.get_plan(plan_id, ANY))
    assert pre["committed_cost_cents"] == 52500
    version_before_close = validate_success(api.begin_reconciliation(plan_id, ADMIN))["version"]

    closed = validate_success(api.close_plan(plan_id, ADMIN))
    assert closed["status"] == "CLOSED"
    assert closed["version"] == version_before_close + 1
    a1_after = validate_success(api.get_assignment(a1["id"], ANY))
    assert a1_after["status"] == "ENDED"
    assert a1_after["end_reason"] == "PLAN_CLOSED"
    assert closed["committed_cost_cents"] == 0  # committed share released
    # Provisional flag was computed live from scheduled minutes (1500 < 1800)
    para_after = validate_success(api.get_para(p1["id"], ANY))
    assert para_after["benefit_eligible"] is False
