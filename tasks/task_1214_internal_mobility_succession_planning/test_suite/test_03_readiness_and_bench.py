"""Readiness scoring, bench strength variants, and development-plan lifecycle."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_employee, setup_hrbp, setup_role, setup_active_role,
    setup_active_role_with_entry,
    add_successor_entry, add_active_successor, activate_entry,
    create_and_activate_plan,
    assert_posture_matches_strength,
)

ADMIN = TEST_USERS["admin_headers"]


class TestReadinessScore:
    def test_readiness_score_without_plan_is_rating_half_only(self, api):
        """PRD §3.3: "it is one half of the employee's current rating points —
        20 for `LOW`, 50 for `SOLID`, 80 for `STRONG`, 100 for `EXCEPTIONAL` —
        plus one half of the plan percentage, where the plan percentage is the
        plan's `completion_pct` when a plan exists in `ACTIVE` or `COMPLETED`
        status and zero otherwise; the blend is rounded half-up to 2 decimal
        places."
        PRD §3.3: "The score is computed at entry creation and recomputed on
        entry updates, on plan creation and plan updates (whether the change is
        progress or status), and whenever calibration applies a new rating to
        the entry's employee."

        Design: Corner/calculations/readiness_score_without_plan_is_rating_half_only
        """
        hrbp, hrbp_headers = setup_hrbp()
        successor = setup_employee(employee_code="S80", job_level=6,
                                   performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_role(hrbp_headers, role_title="Role 80", criticality_tier="TIER_3")
        entry = add_successor_entry(role["id"], successor["id"], hrbp_headers,
                                    readiness_rating="READY_1_2", slate_position=1)
        assert entry["readiness_score"] == pytest.approx(40.00, abs=0.001), (
            f"STRONG with no plan must score 0.5*80 = 40.00, got {entry['readiness_score']}"
        )


class TestBenchStrengthVariants:
    def _setup_dual_variant_roles(self, api):
        """WEIGHTED and COVERAGE roles with identical slates: one ACTIVE
        READY_NOW entry at position 1 whose plan is ACTIVE at 100."""
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPB1")
        incumbent = setup_employee(employee_code="INC1", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        successor = setup_employee(employee_code="SUC1", job_level=6,
                                   performance_rating="STRONG", hire_date="2022-07-01")
        roles = {}
        for method, title in (("WEIGHTED", "Staff Engineer"), ("COVERAGE", "Platform Lead")):
            role = setup_active_role(hrbp_headers, incumbent["id"], role_title=title,
                                     criticality_tier="TIER_2", assessment_method=method)
            entry = add_active_successor(role["id"], successor["id"], hrbp_headers,
                                         readiness_rating="READY_NOW", slate_position=1)
            create_and_activate_plan(entry["id"], hrbp_headers,
                                     target_readiness="READY_NOW", completion_pct=100)
            roles[method] = (role, entry)
        return hrbp_headers, roles

    def test_weighted_variant_bench_value(self, api):
        """PRD §3.2: "Under the `WEIGHTED` variant, each entry's raw
        contribution is its readiness weight — 1.0 for `READY_NOW`, 0.6 for
        `READY_1_2`, 0.3 for `READY_3_PLUS` — multiplied by 0.9 raised to the
        power of its `slate_position` minus one, multiplied by its
        `readiness_score` divided by 100."
        PRD §3.2: "then the sum is divided by 4.0951 — the maximum achievable
        sum, attained when all five slate positions hold a `READY_NOW` entry
        scoring 100 (1.0 plus 0.9 plus 0.81 plus 0.729 plus 0.6561) — and
        multiplied by 100, with the final value rounded half-up to 2 decimal
        places."

        Design: Difficulty/dual_variant_calc/bench_strength_weighted_vs_coverage_same_slate
        """
        hrbp_headers, roles = self._setup_dual_variant_roles(api)
        role_w, entry_w = roles["WEIGHTED"]

        entry = get_success_data(api.get_successor(entry_w["id"], hrbp_headers))
        assert entry["readiness_score"] == pytest.approx(90.00, abs=0.001), (
            "0.5*80 (STRONG) + 0.5*100 (plan) = 90.00"
        )
        role = get_success_data(api.get_critical_role(role_w["id"], hrbp_headers))
        assert role["bench_strength"] == pytest.approx(21.98, abs=0.001), (
            f"WEIGHTED bench must be 0.900/4.0951*100 = 21.98, got {role['bench_strength']}"
        )
        assert role["bench_posture"] == "THIN"

    def test_coverage_variant_bench_value(self, api):
        """PRD §3.2: "Under the `COVERAGE` variant, the count of `ACTIVE`
        entries rated `READY_NOW` or `READY_1_2` is divided by five and
        multiplied by 100, rounded half-up to a whole-number percentage; this
        variant ignores both `readiness_score` and `slate_position`."
        PRD §3.2: "The two variants deliberately produce different values for
        identical slate data."

        Design: Difficulty/dual_variant_calc/bench_strength_weighted_vs_coverage_same_slate
        """
        hrbp_headers, roles = self._setup_dual_variant_roles(api)
        role_c, _ = roles["COVERAGE"]
        role_w, _ = roles["WEIGHTED"]

        coverage = get_success_data(api.get_critical_role(role_c["id"], hrbp_headers))
        assert coverage["bench_strength"] == pytest.approx(20, abs=0.001), (
            f"COVERAGE bench must be 1/5*100 = 20, got {coverage['bench_strength']}"
        )
        assert coverage["bench_posture"] == "THIN"
        weighted = get_success_data(api.get_critical_role(role_w["id"], hrbp_headers))
        assert weighted["bench_strength"] != coverage["bench_strength"], (
            "identical slate data must yield different values under the two variants"
        )


class TestWeightedRoundingOrder:
    def _setup_two_entry_role(self, api):
        """WEIGHTED role with ACTIVE READY_NOW entries: A at position 3 with
        plan at 30 (score 25.00), B at position 4 with plan at 20 (score 20.00)."""
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPB4")
        incumbent = setup_employee(employee_code="INC4", department="OPS", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        sue_a = setup_employee(employee_code="SA4", department="OPS", job_level=5,
                               performance_rating="LOW", hire_date="2024-05-01")
        sue_b = setup_employee(employee_code="SB4", department="OPS", job_level=5,
                               performance_rating="LOW", hire_date="2024-05-01")
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="Ops Lead",
                                 department="OPS", criticality_tier="TIER_3")
        entry_a = add_active_successor(role["id"], sue_a["id"], hrbp_headers,
                                       readiness_rating="READY_NOW", slate_position=3)
        entry_b = add_active_successor(role["id"], sue_b["id"], hrbp_headers,
                                       readiness_rating="READY_NOW", slate_position=4)
        create_and_activate_plan(entry_a["id"], hrbp_headers, completion_pct=30)
        create_and_activate_plan(entry_b["id"], hrbp_headers, completion_pct=20)
        return hrbp_headers, role, entry_a, entry_b

    def test_per_entry_readiness_scores(self, api):
        """PRD §3.3: "it is one half of the employee's current rating points —
        20 for `LOW`, 50 for `SOLID`, 80 for `STRONG`, 100 for `EXCEPTIONAL` —
        plus one half of the plan percentage, where the plan percentage is the
        plan's `completion_pct` when a plan exists in `ACTIVE` or `COMPLETED`
        status and zero otherwise; the blend is rounded half-up to 2 decimal
        places."

        Design: Difficulty/combinatorial_formula/bench_weighted_per_entry_rounding_order_pinned
        """
        hrbp_headers, role, entry_a, entry_b = self._setup_two_entry_role(api)
        a = get_success_data(api.get_successor(entry_a["id"], hrbp_headers))
        b = get_success_data(api.get_successor(entry_b["id"], hrbp_headers))
        assert a["readiness_score"] == pytest.approx(25.00, abs=0.001), (
            "0.5*20 (LOW) + 0.5*30 = 25.00"
        )
        assert b["readiness_score"] == pytest.approx(20.00, abs=0.001), (
            "0.5*20 (LOW) + 0.5*20 = 20.00"
        )

    def test_rounding_order_pinned_bench_value(self, api):
        """PRD §3.2: "The rounding order is pinned: each contribution is first
        rounded half-up to 3 decimal places, then the rounded contributions are
        summed, then the sum is divided by 4.0951 — the maximum achievable sum,
        attained when all five slate positions hold a `READY_NOW` entry scoring
        100 (1.0 plus 0.9 plus 0.81 plus 0.729 plus 0.6561) — and multiplied by
        100, with the final value rounded half-up to 2 decimal places."

        Design: Difficulty/combinatorial_formula/bench_weighted_per_entry_rounding_order_pinned
        """
        hrbp_headers, role, _, _ = self._setup_two_entry_role(api)
        role = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        # Pinned order: round(0.20250,3)=0.203 + round(0.14580,3)=0.146 = 0.349
        # -> 0.349/4.0951*100 = 8.52; summing raw first would give 8.51.
        assert role["bench_strength"] == pytest.approx(8.52, abs=0.001), (
            f"pinned rounding order must yield 8.52, got {role['bench_strength']}"
        )
        assert role["bench_strength"] != pytest.approx(8.51, abs=0.0001)
        assert role["bench_posture"] == "THIN"


class TestBenchPostureBoundaries:
    def test_bench_posture_coverage_boundaries(self, api):
        """PRD §2.9: "A critical role's `bench_posture` is a band derived from
        its stored `bench_strength` after every recomputation: `EMPTY` when the
        strength is exactly 0; `THIN` when the strength is greater than 0 and
        less than 40; `ADEQUATE` when the strength is at least 40 and less than
        70; `STRONG` when the strength is at least 70."
        PRD §2.9: "The boundaries are pinned: 0 is `EMPTY` rather than `THIN`,
        40.00 is `ADEQUATE` rather than `THIN`, and 70.00 is `STRONG` rather
        than `ADEQUATE`."

        Design: Corner/calculations/bench_posture_coverage_boundaries
        """
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPB81")
        incumbent = setup_employee(employee_code="INC81", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="Role 81",
                                 criticality_tier="TIER_2", assessment_method="COVERAGE")
        codes = ["B81A", "B81B", "B81C", "B81D"]
        for i, code in enumerate(codes[:2], start=1):
            emp = setup_employee(employee_code=code, job_level=6,
                                 performance_rating="STRONG", hire_date="2022-07-01")
            add_active_successor(role["id"], emp["id"], hrbp_headers,
                                 readiness_rating="READY_NOW", slate_position=i)

        mid = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert mid["bench_strength"] == pytest.approx(40, abs=0.001)
        assert mid["bench_posture"] == "ADEQUATE", (
            "40 is the ADEQUATE floor (inclusive), not THIN"
        )

        for i, code in enumerate(codes[2:], start=3):
            emp = setup_employee(employee_code=code, job_level=6,
                                 performance_rating="STRONG", hire_date="2022-07-01")
            add_active_successor(role["id"], emp["id"], hrbp_headers,
                                 readiness_rating="READY_NOW", slate_position=i)

        end = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert end["bench_strength"] == pytest.approx(80, abs=0.001)
        assert end["bench_posture"] == "STRONG", "80 >= 70 must be STRONG"
        assert_posture_matches_strength(end)


class TestSuspendReinstate:
    def _setup_two_active_coverage_role(self, api):
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPB51")
        incumbent = setup_employee(employee_code="INC51", job_level=8,
                                   performance_rating="STRONG", hire_date="2019-03-01")
        sue_a = setup_employee(employee_code="S51A", job_level=6,
                               performance_rating="STRONG", hire_date="2022-07-01")
        sue_b = setup_employee(employee_code="S51B", job_level=6,
                               performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_active_role(hrbp_headers, incumbent["id"], role_title="QA Manager",
                                 criticality_tier="TIER_2", assessment_method="COVERAGE")
        add_active_successor(role["id"], sue_a["id"], hrbp_headers,
                             readiness_rating="READY_NOW", slate_position=1)
        entry_b = add_active_successor(role["id"], sue_b["id"], hrbp_headers,
                                       readiness_rating="READY_NOW", slate_position=2)
        return hrbp_headers, role, entry_b

    def test_successor_suspend_reinstate_roundtrip_bench_follows(self, api):
        """PRD §3.2: "joins and departures in either direction cause the role's
        `bench_strength` and `bench_posture` to recompute with `posture_alert`
        maintained per §2.9."
        PRD §3.2: "The `bench_strength` itself is computed over the role's
        `ACTIVE` entries only — `DRAFT`, `SUSPENDED`, `REMOVED`, and `PROMOTED`
        entries are excluded"
        PRD §2.9: "It is set to true when the band degrades into `THIN` or
        `EMPTY` from `ADEQUATE` or `STRONG`, and it is cleared when the band
        recovers into `ADEQUATE` or `STRONG`; sideways movement within the weak
        bands, or within the healthy bands, leaves the flag untouched."

        Design: Corner/state_machines/successor_suspend_reinstate_roundtrip_bench_follows
        """
        hrbp_headers, role, entry_b = self._setup_two_active_coverage_role(api)

        suspended = validate_success(api.patch_successor(entry_b["id"], {
            "status": "SUSPENDED", "suspension_reason": "PERFORMANCE_CONCERN",
        }, hrbp_headers), 200)
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspension_reason"] == "PERFORMANCE_CONCERN"

        mid = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert mid["bench_strength"] == pytest.approx(20, abs=0.001), (
            "suspending one of two COVERAGE entries must drop the bench to 1/5 = 20"
        )
        assert mid["bench_posture"] == "THIN"
        assert mid["posture_alert"] is True, "ADEQUATE -> THIN degradation sets the alert"

        reinstated = validate_success(
            api.patch_successor(entry_b["id"], {"status": "ACTIVE"}, hrbp_headers), 200,
        )
        assert reinstated["status"] == "ACTIVE"

        end = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert end["bench_strength"] == pytest.approx(40, abs=0.001)
        assert end["bench_posture"] == "ADEQUATE"
        assert end["posture_alert"] is False, "recovery to ADEQUATE clears the alert"

    def test_successor_suspend_draft_returns_invalid_state(self, api):
        """PRD §3.2: "an entry transition attempted from the wrong status fails
        with `ERR_SUCCESSOR_INVALID_STATE`"
        PRD §3.2: "suspension moves `ACTIVE` to `SUSPENDED`"

        Design: Corner/state_machines/successor_suspend_draft_returns_invalid_state
        """
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPB52")
        successor = setup_employee(employee_code="S52", job_level=6,
                                   performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_role(hrbp_headers, role_title="Draft Role", criticality_tier="TIER_3")
        entry = add_successor_entry(role["id"], successor["id"], hrbp_headers,
                                    readiness_rating="READY_3_PLUS", slate_position=1)
        resp = api.patch_successor(entry["id"], {
            "status": "SUSPENDED", "suspension_reason": "ORG_CHANGE",
        }, hrbp_headers)
        validate_error(resp, ApiErrorId.ERR_SUCCESSOR_INVALID_STATE, 409)
        after = get_success_data(api.get_successor(entry["id"], hrbp_headers))
        assert after["status"] == "DRAFT"

    def test_successor_suspend_missing_reason_returns_invalid_request(self, api):
        """PRD §3.2: "suspension moves `ACTIVE` to `SUSPENDED` and requires a
        `suspension_reason` of `PERFORMANCE_CONCERN`, `EMPLOYEE_REQUEST`, or
        `ORG_CHANGE` (absent, the request is rejected with
        `ERR_INVALID_REQUEST`)"

        Design: Corner/state_machines/successor_suspend_missing_reason_returns_invalid_request
        """
        ctx = setup_active_role_with_entry(role_title="Role 53", criticality_tier="TIER_3")
        entry = ctx["entry"]
        resp = api.patch_successor(entry["id"], {"status": "SUSPENDED"}, ctx["hrbp_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        after = get_success_data(api.get_successor(entry["id"], ctx["hrbp_headers"]))
        assert after["status"] == "ACTIVE"


class TestDevelopmentPlanLifecycle:
    def test_plan_completion_auto_upgrades_readiness_rating(self, api):
        """PRD §3.3: "when a plan completes and its `target_readiness` outranks
        the entry's current `readiness_rating` — with `READY_NOW` ranked above
        `READY_1_2`, itself ranked above `READY_3_PLUS` — the entry's
        `readiness_rating` is raised to the target band without further human
        action."
        PRD §3.3: "Completion also recomputes the role's bench and posture,
        with `posture_alert` maintained per §2.9."

        Design: Corner/state_machines/plan_completion_auto_upgrades_readiness_rating
        """
        ctx = setup_active_role_with_entry(
            method="COVERAGE", readiness="READY_3_PLUS", plan_pct=100,
            plan_target="READY_1_2",
        )
        role = ctx["role"]
        entry = ctx["entry"]
        plan = ctx["plan"]
        hrbp_headers = ctx["hrbp_headers"]

        before = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert before["bench_strength"] == pytest.approx(0, abs=0.001), (
            "a READY_3_PLUS entry never counts toward COVERAGE"
        )
        assert before["bench_posture"] == "EMPTY"

        completed = validate_success(api.patch_development_plan(
            plan["id"], {"status": "COMPLETED"}, hrbp_headers,
        ), 200)
        assert completed["status"] == "COMPLETED"

        entry = get_success_data(api.get_successor(entry["id"], hrbp_headers))
        assert entry["readiness_rating"] == "READY_1_2", (
            "completing a READY_1_2-targeted plan must upgrade the READY_3_PLUS entry"
        )
        assert entry["readiness_score"] == pytest.approx(90.00, abs=0.001)

        role = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert role["bench_strength"] == pytest.approx(20, abs=0.001)
        assert role["bench_posture"] == "THIN"

    def test_plan_complete_below_100_returns_plan_incomplete(self, api):
        """PRD §3.3: "Completion moves `ACTIVE` to `COMPLETED` and is gated on
        `completion_pct` being exactly 100, failing with `ERR_PLAN_INCOMPLETE`
        below that — the plan-state check is evaluated before the completeness
        check."

        Design: Corner/state_machines/plan_complete_below_100_returns_plan_incomplete
        """
        ctx = setup_active_role_with_entry(readiness="READY_1_2", plan_pct=80,
                                           criticality_tier="TIER_3")
        plan = ctx["plan"]
        resp = api.patch_development_plan(
            plan["id"], {"status": "COMPLETED"}, ctx["hrbp_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_INCOMPLETE, 409)
        after = get_success_data(api.get_development_plan(ctx["entry"]["id"], ctx["hrbp_headers"]))
        assert len(after) == 1 and after[0]["status"] == "ACTIVE"

    def test_plan_abandon_recomputes_readiness_score(self, api):
        """PRD §3.3: "Because plan activation makes the plan count and
        abandonment makes it stop counting, both transitions recompute the
        entry's `readiness_score` and the role's `bench_strength`."
        PRD §3.3: "where the plan percentage is the plan's `completion_pct`
        when a plan exists in `ACTIVE` or `COMPLETED` status and zero
        otherwise"

        Design: Corner/state_machines/plan_abandon_recomputes_readiness_score
        """
        ctx = setup_active_role_with_entry(
            method="WEIGHTED", readiness="READY_NOW", plan_pct=80,
            criticality_tier="TIER_3",
        )
        role = ctx["role"]
        entry = ctx["entry"]
        plan = ctx["plan"]
        hrbp_headers = ctx["hrbp_headers"]

        before_entry = get_success_data(api.get_successor(entry["id"], hrbp_headers))
        assert before_entry["readiness_score"] == pytest.approx(80.00, abs=0.001)

        abandoned = validate_success(api.patch_development_plan(
            plan["id"], {"status": "ABANDONED"}, hrbp_headers,
        ), 200)
        assert abandoned["status"] == "ABANDONED"

        entry = get_success_data(api.get_successor(entry["id"], hrbp_headers))
        assert entry["readiness_score"] == pytest.approx(40.00, abs=0.001), (
            "after abandonment the plan stops counting: 0.5*80 + 0 = 40.00"
        )
        role = get_success_data(api.get_critical_role(role["id"], hrbp_headers))
        assert role["bench_strength"] == pytest.approx(9.77, abs=0.001), (
            "contribution 1.0*1.0*0.40 = 0.400 -> 0.400/4.0951*100 = 9.77"
        )

    def test_plan_reactivate_abandoned_returns_plan_invalid_state(self, api):
        """PRD §3.3: "Abandonment moves a plan from `DRAFT` or `ACTIVE` to
        `ABANDONED` (from any other status, `ERR_PLAN_INVALID_STATE`)."
        PRD §3.3: "Activation moves `DRAFT` to `ACTIVE` and requires both that
        the plan is `DRAFT` (otherwise `ERR_PLAN_INVALID_STATE`) and that its
        successor entry is `ACTIVE` (otherwise `ERR_SUCCESSOR_INVALID_STATE`)."

        Design: Corner/state_machines/plan_reactivate_abandoned_returns_plan_invalid_state
        """
        ctx = setup_active_role_with_entry(readiness="READY_1_2",
                                           criticality_tier="TIER_3")
        hrbp_headers = ctx["hrbp_headers"]
        plan = validate_success(api.create_development_plan(
            ctx["entry"]["id"], {"target_readiness": "READY_NOW"}, hrbp_headers,
        ), 201)
        abandoned = validate_success(api.patch_development_plan(
            plan["id"], {"status": "ABANDONED"}, hrbp_headers,
        ), 200)
        assert abandoned["status"] == "ABANDONED"

        resp = api.patch_development_plan(plan["id"], {"status": "ACTIVE"}, hrbp_headers)
        validate_error(resp, ApiErrorId.ERR_PLAN_INVALID_STATE, 409)
        after = get_success_data(
            api.get_development_plan(ctx["entry"]["id"], hrbp_headers)
        )
        assert after[0]["status"] == "ABANDONED"

    def test_second_development_plan_returns_plan_already_exists(self, api):
        """PRD §3.3: "Each successor entry may carry at most one
        **DevelopmentPlan**; attempting to create a second is rejected with
        `ERR_PLAN_ALREADY_EXISTS`."
        PRD §3.3: "the entry's plan can be read back as an array of zero or one
        element."

        Design: Corner/validations/second_development_plan_returns_plan_already_exists
        """
        hrbp, hrbp_headers = setup_hrbp(employee_code="HRPB94")
        successor = setup_employee(employee_code="S94", job_level=6,
                                   performance_rating="STRONG", hire_date="2022-07-01")
        role = setup_role(hrbp_headers, role_title="Role 94", criticality_tier="TIER_3")
        entry = add_successor_entry(role["id"], successor["id"], hrbp_headers,
                                    readiness_rating="READY_3_PLUS", slate_position=1)
        validate_success(api.create_development_plan(
            entry["id"], {"target_readiness": "READY_1_2"}, hrbp_headers,
        ), 201)

        resp = api.create_development_plan(
            entry["id"], {"target_readiness": "READY_NOW"}, hrbp_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_ALREADY_EXISTS, 409)

        plans = get_success_data(api.get_development_plan(entry["id"], hrbp_headers))
        assert isinstance(plans, list) and len(plans) == 1, (
            "the entry must still carry exactly one plan"
        )
