"""Department budget buckets, posture thresholds, and pool floor."""
import pytest

from test_helpers import (
    ApiErrorId,
    allocate_cycle,
    approve_coverage_plan,
    assert_department_budget_invariant,
    close_cycle,
    create_application,
    create_coverage_plan,
    create_cycle,
    create_department,
    create_faculty,
    create_submitted_review,
    decide_application,
    get_application,
    grant_for_application,
    make_department_chair_headers,
    make_faculty_headers,
    open_cycle,
    run_accruals,
    separate_faculty,
    set_department_chair,
    setup_department_with_chair,
    setup_full_award,
    setup_reviewers,
    setup_submitted_sabbatical_application,
    submit_application,
    submit_coverage_plan,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PROVOST = TEST_USERS["provost_headers"]


class TestDepartmentDefaults:
    def test_department_create_defaults(self, api):
        """PRD 3.1: "A new department is born with `reserved_amount` and
        `spent_amount` both zero, posture `OPEN`, and `version` 1."
        PRD 3.1: "`available_amount` is whatever remains: the pool minus the
        reserved and spent amounts."

        Design: Corner/entities/department_create_defaults
        """
        data = validate_success(
            api.create_department({"name": "Engineering", "replacement_pool": 160000.00}, ADMIN),
            expected_status=201,
        )
        assert data["reserved_amount"] == pytest.approx(0.00, abs=0.005)
        assert data["spent_amount"] == pytest.approx(0.00, abs=0.005)
        assert data["available_amount"] == pytest.approx(160000.00, abs=0.005)
        assert data["posture"] == "OPEN"
        assert data["version"] == 1


class TestPoolFloor:
    def test_pool_patch_below_commitments_rejected(self, api):
        """PRD 3.1: "The pool may never be set below the sum of the reserved and
        spent amounts; such an edit is rejected with `ERR_POOL_BELOW_COMMITMENTS`."
        PRD 3.1: "The boundaries are inclusive: a utilization of exactly seventy
        percent is `CONSTRAINED`, and exactly ninety-five percent is `FROZEN`."

        Design: Corner/validations/pool_patch_below_commitments_rejected
        """
        base = setup_department_with_chair()
        dept, chair = base["department"], base["chair"]
        faculty = create_faculty(dept["id"])
        run_accruals()
        cycle = open_cycle(create_cycle()["id"])
        app = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])
        plan = create_coverage_plan(app["id"], chair["id"], 3)
        submit_coverage_plan(plan["id"], chair["id"])
        approve_coverage_plan(plan["id"])  # reserved 24000.00

        too_low = api.update_department(dept["id"], {"replacement_pool": 20000.00}, ADMIN)
        validate_error(too_low, ApiErrorId.ERR_POOL_BELOW_COMMITMENTS)

        exact = validate_success(
            api.update_department(dept["id"], {"replacement_pool": 24000.00}, ADMIN)
        )
        assert exact["replacement_pool"] == pytest.approx(24000.00, abs=0.005)
        assert exact["available_amount"] == pytest.approx(0.00, abs=0.005)
        # utilization 1.0 >= 0.95 -> FROZEN
        assert exact["posture"] == "FROZEN"


class TestPostureThresholdBoundaries:
    def test_posture_threshold_transitions_at_exact_boundaries(self, api):
        """PRD 3.1: "The boundaries are inclusive: a utilization of exactly
        seventy percent is `CONSTRAINED`, and exactly ninety-five percent is
        `FROZEN`." PRD 3.1: "A `FROZEN` department cannot move coverage plans
        forward — both plan submission and plan approval are rejected with
        `ERR_DEPARTMENT_FROZEN`"

        Design: Corner/cross_cutting_layers/posture_threshold_transitions_at_exact_boundaries
        """
        base = setup_department_with_chair()
        dept, chair = base["department"], base["chair"]
        f1 = create_faculty(dept["id"])
        f2 = create_faculty(dept["id"], academic_rank="ASSISTANT_PROFESSOR",
                            annual_base_salary=100000.00)
        f3 = create_faculty(dept["id"], academic_rank="FULL_PROFESSOR",
                            annual_base_salary=140000.00)
        run_accruals()
        cycle = open_cycle(create_cycle(award_quota=3)["id"])
        app1 = setup_submitted_sabbatical_application(f1["id"], cycle["id"])
        app2 = setup_submitted_sabbatical_application(f2["id"], cycle["id"])
        app3 = setup_submitted_sabbatical_application(f3["id"], cycle["id"])

        cp1 = create_coverage_plan(app1["id"], chair["id"], 14)
        submit_coverage_plan(cp1["id"], chair["id"])
        cp2 = create_coverage_plan(app2["id"], chair["id"], 5)
        submit_coverage_plan(cp2["id"], chair["id"])
        cp3 = create_coverage_plan(app3["id"], chair["id"], 1)  # stays DRAFT

        approve_coverage_plan(cp1["id"])
        d1 = validate_success(api.get_department(dept["id"], ADMIN))
        # 14 courses * 8000 = 112000 reserved on a 160000 pool: exactly 0.70
        assert d1["reserved_amount"] == pytest.approx(112000.00, abs=0.005)
        assert d1["posture"] == "CONSTRAINED"

        approve_coverage_plan(cp2["id"])
        d2 = validate_success(api.get_department(dept["id"], ADMIN))
        # 112000 + 40000 = 152000: exactly 0.95 -> FROZEN
        assert d2["reserved_amount"] == pytest.approx(152000.00, abs=0.005)
        assert d2["posture"] == "FROZEN"

        frozen_submit = api.submit_coverage_plan(
            cp3["id"], make_department_chair_headers(chair["id"])
        )
        validate_error(frozen_submit, ApiErrorId.ERR_DEPARTMENT_FROZEN)


class TestReserveReleaseConservation:
    def test_reserve_holds_between_approve_and_release(self, api):
        """PRD 3.1: "An invariant holds at all times — the reserved, spent, and
        available amounts always sum exactly back to `replacement_pool`."
        PRD 3.5: "On approval the department's `reserved_amount` increases by
        the `provisional_cost`, `available_amount` and the posture are recomputed"

        Design: Difficulty/compensating_invariant/department_budget_reserve_release_conservation
        """
        ctx = setup_full_award(courses_to_cover=3, award_quota=1)
        # Re-read the department state captured at approval time: the award
        # pipeline confirmed the plan at allocation, so use a fresh approve-only
        # pipeline to observe the reserve step directly.
        base = setup_department_with_chair()
        dept, chair = base["department"], base["chair"]
        faculty = create_faculty(dept["id"])
        reviewers = setup_reviewers()
        run_accruals()
        cycle = open_cycle(create_cycle(award_quota=1)["id"])
        app = setup_submitted_sabbatical_application(faculty["id"], cycle["id"])
        for reviewer, (m, c, f) in zip(reviewers, ((80, 90, 70), (90, 85, 95), (70, 60, 80))):
            create_submitted_review(app["id"], reviewer["id"], m, c, f)
        plan = create_coverage_plan(app["id"], chair["id"], 3)
        submit_coverage_plan(plan["id"], chair["id"])
        approve_coverage_plan(plan["id"])

        dept_mid = validate_success(api.get_department(dept["id"], ADMIN))
        assert dept_mid["reserved_amount"] == pytest.approx(24000.00, abs=0.005)
        assert dept_mid["available_amount"] == pytest.approx(136000.00, abs=0.005)
        assert_department_budget_invariant(dept_mid)
        assert dept_mid["posture"] == "OPEN"
        assert ctx["grant"]["status"] == "SCHEDULED"  # pipeline sanity

    def test_release_after_separation_restores_pool_exactly(self, api):
        """PRD 3.9: "every one of their `SCHEDULED` grants is cancelled with the
        full unwind of §3.7 — credit restore of thirty-six per semester,
        `CONFIRMED` plan released with the department's `reserved_amount`
        dropping by the `provisional_cost` and posture recomputed"
        PRD 3.1: "An invariant holds at all times — the reserved, spent, and
        available amounts always sum exactly back to `replacement_pool`."

        Design: Difficulty/compensating_invariant/department_budget_reserve_release_conservation
        """
        ctx = setup_full_award(courses_to_cover=3, award_quota=1)
        dept = ctx["department"]
        # Pre-separation sanity: plan CONFIRMED so its 24000.00 sits in reserved.
        dept_pre = validate_success(api.get_department(dept["id"], ADMIN))
        assert dept_pre["reserved_amount"] == pytest.approx(24000.00, abs=0.005)
        assert dept_pre["posture"] == "OPEN"

        separate_faculty(ctx["faculty"]["id"], "2026-12-15T00:00:00Z")

        dept_post = validate_success(api.get_department(dept["id"], ADMIN))
        assert dept_post["reserved_amount"] == pytest.approx(0.00, abs=0.005)
        assert dept_post["spent_amount"] == pytest.approx(0.00, abs=0.005)
        assert dept_post["available_amount"] == pytest.approx(160000.00, abs=0.005)
        assert dept_post["posture"] == "OPEN"
        assert_department_budget_invariant(dept_post)

        plan_post = validate_success(api.get_coverage_plan(ctx["plan"]["id"], ADMIN))
        assert plan_post["status"] == "RELEASED"
