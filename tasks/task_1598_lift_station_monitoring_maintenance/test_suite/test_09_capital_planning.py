"""Capital planning: risk-score formula, deterministic ranking, budget-gated
approval, settlement lock, and budget conservation."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_project,
    approve_plan,
    assert_plan_budget_conservation,
    create_plan,
    create_station,
    get_plan,
    get_project,
    rank_plan,
    reset_clock,
    setup_ranked_plan,
    setup_sso_closed,
    validate_error,
    validate_success,
)


class TestRiskScore:
    def test_risk_score_capped_at_100_with_all_bonuses(self, api, capital_program_manager_headers):
        """PRD §3.10: "Every project carries a computed `risk_score` between
        0.00 and 100.00, recomputed on project creation, on field mutation, and
        whenever the parent plan is ranked. The score starts from the product of
        `consequence_of_failure` and `likelihood_of_failure`. A recency bonus of
        15 points is added when the referenced station's `last_sso_occurred_at`
        is set and falls less than 365 days before the current time. A
        resilience bonus of 10 points is added when the station has no backup
        generator. An age component is added equal to the station's age in whole
        years — the elapsed days between the station's `created_at` and now,
        divided by 365.25 and floored — capped at 25 points. The sum is capped
        at 100.00 and rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/capital_risk_score_multi_input_formula
        """
        reset_clock("2001-08-01T00:00:00Z")
        station = create_station(has_backup_generator=False)
        reset_clock("2026-07-01T00:00:00Z")
        setup_sso_closed(
            station["id"], started_at="2026-07-01T00:00:00Z",
            contained_at="2026-07-01T02:00:00Z", submit_at="2026-07-01T03:00:00Z",
            cause_code="PUMP_FAILURE",
        )
        reset_clock("2026-08-01T00:00:00Z")
        plan = create_plan(plan_year=2027, budget_total_usd=1000000)
        res = api.create_capital_project(
            {
                "plan_id": plan["id"], "station_id": station["id"],
                "project_name": "Pump rebuild", "estimated_cost_usd": 50000,
                "consequence_of_failure": 8, "likelihood_of_failure": 7,
            },
            capital_program_manager_headers,
        )
        project = validate_success(res, 201)
        assert project["risk_score"] == pytest.approx(100.00, abs=0.01), (
            "base 56 + recency 15 + resilience 10 + age 24 exceeds the 100.00 cap"
        )

    def test_risk_score_base_only_when_no_bonuses(self, api, capital_program_manager_headers):
        """PRD §3.10: "The score starts from the product of
        `consequence_of_failure` and `likelihood_of_failure`. A recency bonus of
        15 points is added when the referenced station's `last_sso_occurred_at`
        is set and falls less than 365 days before the current time. A
        resilience bonus of 10 points is added when the station has no backup
        generator."
        PRD §3.1: "A newly created station begins life in posture `NORMAL`, with
        `firm_capacity_available_gpm` computed from its pumps and
        `last_sso_occurred_at` null until an overflow occurs."

        Design: Difficulty/combinatorial_formula/capital_risk_score_multi_input_formula
        """
        reset_clock()
        station = create_station(has_backup_generator=True)
        plan = create_plan(plan_year=2027)
        res = api.create_capital_project(
            {
                "plan_id": plan["id"], "station_id": station["id"],
                "project_name": "Baseline", "estimated_cost_usd": 50000,
                "consequence_of_failure": 8, "likelihood_of_failure": 7,
            },
            capital_program_manager_headers,
        )
        project = validate_success(res, 201)
        assert project["risk_score"] == pytest.approx(56.00, abs=0.01), (
            "8 * 7 with no SSO history, a backup generator, and zero age"
        )

    def test_risk_score_recency_and_age_components(self, api, capital_program_manager_headers):
        """PRD §3.10: "A recency bonus of 15 points is added when the referenced
        station's `last_sso_occurred_at` is set and falls less than 365 days
        before the current time."
        PRD §3.10: "An age component is added equal to the station's age in
        whole years — the elapsed days between the station's `created_at` and
        now, divided by 365.25 and floored — capped at 25 points."

        Design: Difficulty/combinatorial_formula/capital_risk_score_multi_input_formula
        """
        reset_clock("2025-07-01T00:00:00Z")
        station = create_station(has_backup_generator=True)
        reset_clock("2026-07-15T00:00:00Z")
        setup_sso_closed(
            station["id"], started_at="2026-07-15T00:00:00Z",
            contained_at="2026-07-15T01:00:00Z", submit_at="2026-07-15T02:00:00Z",
            cause_code="DEBRIS",
        )
        reset_clock("2026-08-01T00:00:00Z")
        plan = create_plan(plan_year=2027)
        res = api.create_capital_project(
            {
                "plan_id": plan["id"], "station_id": station["id"],
                "project_name": "Recency+age", "estimated_cost_usd": 50000,
                "consequence_of_failure": 8, "likelihood_of_failure": 7,
            },
            capital_program_manager_headers,
        )
        project = validate_success(res, 201)
        assert project["risk_score"] == pytest.approx(72.00, abs=0.01), (
            "base 56 + recency 15 + age 1 (396 days), no resilience bonus"
        )


class TestRanking:
    def test_capital_plan_rank_assigns_priority(self, api, capital_program_manager_headers):
        """PRD §3.10: "Ranking orders every `PROPOSED` project by `risk_score`
        descending, with deterministic tie-breaks of lower `estimated_cost_usd`
        first, then earlier `created_at`, then `id`; assigns `priority_rank`
        values 1, 2, 3, ... in that order; recomputes each project's
        `risk_score`; and cascades each ranked project `PROPOSED → RANKED`."

        Design: Corner/state_machines/capital_plan_rank_assigns_priority
        """
        reset_clock()
        station = create_station(has_backup_generator=True)
        plan = create_plan(plan_year=2029, budget_total_usd=500000)
        p_low = add_project(plan["id"], station["id"], project_name="Low",
                            estimated_cost_usd=10000, consequence_of_failure=2,
                            likelihood_of_failure=2)
        p_high = add_project(plan["id"], station["id"], project_name="High",
                             estimated_cost_usd=10000, consequence_of_failure=9,
                             likelihood_of_failure=9)
        p_mid = add_project(plan["id"], station["id"], project_name="Mid",
                            estimated_cost_usd=10000, consequence_of_failure=5,
                            likelihood_of_failure=5)
        res = api.rank_capital_plan(plan["id"], capital_program_manager_headers)
        ranked = validate_success(res, 200)
        assert ranked["status"] == "RANKED"
        assert get_project(p_high["id"])["priority_rank"] == 1, "highest risk first"
        assert get_project(p_mid["id"])["priority_rank"] == 2
        assert get_project(p_low["id"])["priority_rank"] == 3
        assert get_project(p_high["id"])["status"] == "RANKED"

    def test_unrank_reverts_ranked_to_proposed(self, api, capital_program_manager_headers):
        """PRD §3.10: "Unranking reverts the plan `RANKED → DRAFT` and cascades
        every `RANKED` project back to `PROPOSED`, clearing its
        `priority_rank`."

        Design: Corner/state_machines/unrank_reverts_ranked_to_proposed
        """
        reset_clock()
        plan, station, projects = setup_ranked_plan(plan_year=2030)
        res = api.unrank_capital_plan(plan["id"], capital_program_manager_headers)
        plan_after = validate_success(res, 200)
        assert plan_after["status"] == "DRAFT"
        project_after = get_project(projects[0]["id"])
        assert project_after["status"] == "PROPOSED"
        assert project_after["priority_rank"] is None

class TestBudgetGateAndLock:
    def test_budget_exceeded_at_approve(self, api, utility_admin_headers,
                                        capital_program_manager_headers):
        """PRD §3.10: "Approval is rejected with `ERR_BUDGET_EXCEEDED` (HTTP
        422) when the plan's `budget_allocated_usd` exceeds its
        `budget_total_usd`."
        PRD §3.10: "The plan tracks `budget_allocated_usd` — the sum of
        `estimated_cost_usd` across its projects in `PROPOSED`, `RANKED`, or
        `APPROVED`"

        Design: Corner/validations/budget_exceeded_at_approve
        """
        reset_clock()
        station = create_station(has_backup_generator=True)
        plan = create_plan(plan_year=2031, budget_total_usd=100)
        add_project(plan["id"], station["id"], project_name="Too big",
                    estimated_cost_usd=200, consequence_of_failure=5,
                    likelihood_of_failure=5)
        rank_plan(plan["id"])
        current = get_plan(plan["id"])
        res = api.approve_capital_plan(plan["id"], current["version"], utility_admin_headers)
        validate_error(res, ApiErrorId.ERR_BUDGET_EXCEEDED)

    def test_plan_lock_before_7_days_rejected(self, api, utility_admin_headers):
        """PRD §3.10: "Locking is the final plan transition (`APPROVED →
        LOCKED`), performed by a `UtilityAdmin` no sooner than 7 days after
        `approved_at`; an earlier attempt is rejected with
        `ERR_PLAN_NOT_SETTLED` (HTTP 422)."

        Design: Corner/validations/plan_lock_before_7_days_rejected
        """
        reset_clock()
        plan, station, _ = setup_ranked_plan(
            projects=(("P1", 5000.00, 5, 5),), plan_year=2032,
        )
        approve_plan(plan["id"])
        reset_clock("2026-08-04T00:00:00Z")
        res = api.lock_capital_plan(plan["id"], utility_admin_headers)
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_SETTLED)


class TestBudgetConservation:
    def test_in_budget_approve_conserves_budget(self, api, utility_admin_headers):
        """PRD §3.10: "The plan tracks `budget_allocated_usd` — the sum of
        `estimated_cost_usd` across its projects in `PROPOSED`, `RANKED`, or
        `APPROVED` — and `budget_remaining_usd`, the difference between total
        and allocated, floored at 0.00 for reporting purposes while the raw
        difference drives gating."
        PRD §3.10: "On approval the plan stamps `approved_at`, increments its
        `version`, and walks its `RANKED` projects in ascending `priority_rank`:
        the longest prefix of projects whose cumulative `estimated_cost_usd`
        stays within `budget_total_usd` transitions `RANKED → APPROVED`, and
        every remaining `RANKED` project transitions `RANKED → DEFERRED`"

        Design: Difficulty/compensating_invariant/capital_budget_allocation_invariant
        """
        reset_clock()
        plan, station, projects = setup_ranked_plan(
            projects=(("A", 60000.00, 9, 9),), plan_year=2028,
            budget_total_usd=100000,
        )
        plan_after = approve_plan(plan["id"])
        assert plan_after["status"] == "APPROVED"
        assert plan_after["approved_at"] is not None
        project_after = get_project(projects[0]["id"])
        assert project_after["status"] == "APPROVED", "lone project fits the budget"
        plan_read = get_plan(plan["id"])
        assert plan_read["budget_allocated_usd"] == pytest.approx(60000.00, abs=0.01), (
            "only the APPROVED project consumes budget"
        )
        assert plan_read["budget_remaining_usd"] == pytest.approx(40000.00, abs=0.01)
        assert_plan_budget_conservation(plan_read)

    def test_proposed_projects_count_toward_allocated(self, api):
        """PRD §3.10: "The plan tracks `budget_allocated_usd` — the sum of
        `estimated_cost_usd` across its projects in `PROPOSED`, `RANKED`, or
        `APPROVED` — and `budget_remaining_usd`, the difference between total
        and allocated, floored at 0.00 for reporting purposes while the raw
        difference drives gating."

        Design: Difficulty/compensating_invariant/capital_budget_allocation_invariant
        """
        reset_clock()
        station = create_station(has_backup_generator=True)
        plan = create_plan(plan_year=2092, budget_total_usd=100000)
        add_project(plan["id"], station["id"], project_name="A",
                    estimated_cost_usd=60000, consequence_of_failure=5,
                    likelihood_of_failure=5)
        add_project(plan["id"], station["id"], project_name="B",
                    estimated_cost_usd=30000, consequence_of_failure=4,
                    likelihood_of_failure=4)
        plan_read = get_plan(plan["id"])
        assert plan_read["budget_allocated_usd"] == pytest.approx(90000.00, abs=0.01), (
            "both PROPOSED projects count toward allocation"
        )
        assert plan_read["budget_remaining_usd"] == pytest.approx(10000.00, abs=0.01)
        assert_plan_budget_conservation(plan_read)
