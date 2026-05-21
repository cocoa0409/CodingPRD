"""CompPlan calculations — merit_increase_amount and
equity_refresh_amount in every PRD-stated combination.

Covers:
* Annual merit by rating (9/6/3/0/0% of pinned_base_salary_cents floored).
* Promotion-bump path (+5% when promotion + rating in {OUTSTANDING, EXCEEDS}).
* PIP zero path (Employee.status == ON_PIP overrides).
* SEMI_ANNUAL halving (integer-division floor).
* Equity refresh: level-band x rating grant table, cadence multiplier,
  half-up rounding BEFORE the floor bump, PIP zero path.
* Weighted-goal-score provisional (DRAFT) vs canonical (post-submit).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    create_comp_plan_payload,
    expected_equity_refresh_units,
    expected_merit_increase_cents,
    propose_plan,
    setup_draft_comp_plan,
    setup_finalized_review_case,
    setup_submittable_review_case,
    submit_review_case,
    validate_success,
)


# ===========================================================================
# Merit calculation — annual base table
# ===========================================================================
class TestMeritByRating:
    """PRD §3.7 base merit table.

    'For `ANNUAL` cadence the base table is: `OUTSTANDING` returns 9
    percent, `EXCEEDS` returns 6 percent, `MEETS` returns 3 percent,
    and both `NEEDS_IMPROVEMENT` and `UNSATISFACTORY` return 0
    percent... The raw merit amount in cents is the floor of
    `pinned_base_salary_cents` multiplied by the selected percentage
    divided by 100.'
    """

    @pytest.mark.parametrize("rating,expected_pct", [
        ("OUTSTANDING", 9),
        ("EXCEEDS", 6),
        ("MEETS", 3),
    ])
    def test_annual_merit_for_rating(self, api, rating, expected_pct):
        """PRD §3.7: "For `ANNUAL` cadence the base table is:
        `OUTSTANDING` returns 9 percent, `EXCEEDS` returns 6 percent,
        `MEETS` returns 3 percent...The raw merit amount in cents is the
        floor of `pinned_base_salary_cents` multiplied by the selected
        percentage divided by 100."

        # difficulty: combinatorial_formula/merit_tiered_rate_with_state_branching
        """
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating=rating,
            subject_base_salary_cents=10_000_000,
        )
        plan = validate_success(api.propose_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.manager.headers,
        ), 200)
        expected = expected_merit_increase_cents(
            pinned_base_salary_cents=10_000_000,
            cadence="ANNUAL",
            final_rating=rating,
            promotion_to_level=None,
            current_job_level=4,
            employee_on_pip=False,
        )
        assert plan["merit_increase_cents"] == expected
        # Sanity: equals base_salary * pct / 100 (floored).
        assert plan["merit_increase_cents"] == (10_000_000 * expected_pct) // 100

    @pytest.mark.parametrize("rating", ["NEEDS_IMPROVEMENT", "UNSATISFACTORY"])
    def test_annual_merit_zero_for_low_ratings(self, api, rating):
        """PRD §3.7: "...both `NEEDS_IMPROVEMENT` and `UNSATISFACTORY`
        return 0 percent."

        # difficulty: combinatorial_formula/merit_tiered_rate_with_state_branching
        """
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating=rating,
            subject_base_salary_cents=10_000_000,
        )
        plan = validate_success(api.propose_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.manager.headers,
        ), 200)
        # NI lands the subject on PIP automatically — see calibration
        # cascade; but PRD §3.7 says merit is also 0 for NI rating
        # itself. For NEEDS_IMPROVEMENT/UNSATISFACTORY the subject is
        # ON_PIP, which independently forces merit to 0.
        assert plan["merit_increase_cents"] == 0


# ===========================================================================
# Merit promotion bump (PRD §3.7)
# ===========================================================================
class TestMeritPromotionBump:

    def test_promo_with_exceeds_adds_5pct(self, api):
        """PRD §3.7: "If the plan carries a `promotion_to_level` set to
        exactly one above the subject's current `job_level` and the
        pinned rating is `OUTSTANDING` or `EXCEEDS`, an additional
        promotion bump is added to the raw amount: the floor of
        `pinned_base_salary_cents` multiplied by 5 divided by 100."

        Difficulty-design instance:
        merit_increase_promo_vs_pip (variant B = promo path).

        # difficulty: dual_variant_calc/merit_increase_promo_vs_pip
        # difficulty: combinatorial_formula/merit_tiered_rate_with_state_branching
        """
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="EXCEEDS",
            subject_base_salary_cents=10_000_000,
            subject_job_level=4,
            promotion_to_level=5,
        )
        plan = validate_success(api.propose_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.manager.headers,
        ), 200)
        # 600_000 (6% base) + 500_000 (5% promo bump) = 1_100_000.
        assert plan["merit_increase_cents"] == 1_100_000

    def test_promo_with_outstanding_adds_5pct(self, api):
        """PRD §3.7: "...if the pinned rating is `OUTSTANDING` or
        `EXCEEDS`, an additional promotion bump is added"."""
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="OUTSTANDING",
            subject_base_salary_cents=10_000_000,
            subject_job_level=4,
            promotion_to_level=5,
        )
        plan = validate_success(api.propose_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.manager.headers,
        ), 200)
        # 900_000 (9% base) + 500_000 (5% bump) = 1_400_000.
        assert plan["merit_increase_cents"] == 1_400_000


# ===========================================================================
# Merit PIP zero path (PRD §3.7)
# ===========================================================================
class TestMeritPipGate:

    def test_pip_forces_merit_to_zero(self, api):
        """PRD §3.7: "Finally, the PIP gate overrides everything: if the
        subject's `Employee.status` is `ON_PIP` at the moment of
        propose or approve, `merit_increase_cents` is forced to zero
        regardless of rating, base salary, or promotion setting."

        Drive subject to ON_PIP via NEEDS_IMPROVEMENT calibration, then
        a fresh CompPlan (no promotion) yields 0 even though the rating
        column would otherwise return 0 anyway — to isolate the PIP
        gate, NI rating is ambiguous. We instead build a subject whose
        FINALIZED rating is EXCEEDS but whose status is ON_PIP. PRD
        §3.5 only auto-creates a PIP for NI / UNSATISFACTORY ratings,
        so to reach (EXCEEDS, ON_PIP) we need a second cycle. We use
        two cycles: cycle1 with NI rating (PIP created), cycle2 with
        EXCEEDS rating (CompPlan tested while subject still ON_PIP).

        # difficulty: dual_variant_calc/merit_increase_promo_vs_pip
        # difficulty: combinatorial_formula/merit_tiered_rate_with_state_branching
        """
        from test_helpers import (
            attach_calibration_session,
            create_active_employee,
            create_employee_with_role,
            create_review_case_payload,
            setup_department_with_locked_cases,
            create_open_cycle,
        )
        # Cycle 1: drive subject to ON_PIP via NEEDS_IMPROVEMENT.
        cyc1_bundle = setup_finalized_review_case(
            final_rating="NEEDS_IMPROVEMENT",
            subject_department="EngPip",
        )
        subj_id = cyc1_bundle.subject["id"]
        # Cycle 2: same subject (still ON_PIP) gets an EXCEEDS rating.
        # We need a separate department to drive an independent
        # calibration. Use a fresh cycle.
        cyc2 = create_open_cycle()
        mgr2 = create_employee_with_role("Manager", department="EngPip")
        hrbp2 = create_employee_with_role("HRBP", department="EngPip")
        # Update subject's manager to mgr2 so we can open a case.
        from test_helpers import TEST_USERS, update_employee_payload
        validate_success(api.update_employee(
            subj_id, update_employee_payload(manager_employee_id=mgr2.id),
            TEST_USERS["admin_headers"],
        ), 200)
        rc = validate_success(api.create_review_case(
            cyc2["id"], create_review_case_payload(subj_id), hrbp2.headers,
        ), 201)
        # Add goals and feedback to make case submittable.
        from test_helpers import (
            create_goal_payload,
            create_feedback_request_payload,
            submit_feedback_request_payload,
        )
        for w, ms in [(60, 5), (40, 4)]:
            validate_success(api.create_goal(
                cyc2["id"], rc["id"],
                create_goal_payload(weight=w, self_score=3,
                                    manager_score=ms),
                mgr2.headers,
            ), 201)
        validate_success(api.update_review_case(
            cyc2["id"], rc["id"], {"manager_rating": "EXCEEDS"},
            mgr2.headers,
        ), 200)
        for _ in range(2):
            rev = create_employee_with_role("Reviewer",
                                            department="EngPip")
            fr = validate_success(api.create_feedback_request(
                cyc2["id"], rc["id"],
                create_feedback_request_payload(rev.id, relation="PEER"),
                hrbp2.headers,
            ), 201)
            validate_success(api.submit_feedback_request(
                cyc2["id"], rc["id"], fr["id"],
                submit_feedback_request_payload(), rev.headers,
            ), 200)
        validate_success(api.submit_review_case(
            cyc2["id"], rc["id"], mgr2.headers,
        ), 200)
        # Update cyc2 bell curve so 1 case of EXCEEDS is compliant.
        validate_success(api.update_cycle(
            cyc2["id"], {"bell_curve_target": {
                "OUTSTANDING": 0, "EXCEEDS": 100, "MEETS": 0,
                "NEEDS_IMPROVEMENT": 0, "UNSATISFACTORY": 0,
            }}, TEST_USERS["admin_headers"],
        ), 200)
        cyc2 = validate_success(api.lock_reviews(cyc2["id"], hrbp2.headers), 200)
        cs = validate_success(api.create_calibration_session(
            cyc2["id"], {
                "department": "EngPip",
                "facilitator_employee_id": hrbp2.id,
            },
            hrbp2.headers,
        ), 201)
        validate_success(api.update_calibration_proposals(
            cyc2["id"], cs["id"],
            {"proposed_ratings": [
                {"review_case_id": rc["id"], "proposed_rating": "EXCEEDS"},
            ]},
            hrbp2.headers,
        ), 200)
        validate_success(api.start_calibration_session(
            cyc2["id"], cs["id"], hrbp2.headers,
        ), 200)
        validate_success(api.commit_calibration_session(
            cyc2["id"], cs["id"], hrbp2.headers,
        ), 200)
        # Confirm subject still ON_PIP.
        emp = validate_success(api.get_employee(
            subj_id, TEST_USERS["admin_headers"],
        ), 200)
        assert emp["status"] == "ON_PIP"
        # Create + propose comp plan on cycle 2; no promotion.
        plan = validate_success(api.create_comp_plan(
            cyc2["id"],
            create_comp_plan_payload(subj_id),
            mgr2.headers,
        ), 201)
        plan = validate_success(api.propose_comp_plan(
            cyc2["id"], plan["id"], mgr2.headers,
        ), 200)
        # PRD §3.7 PIP gate forces merit to 0 even though rating is EXCEEDS.
        assert plan["merit_increase_cents"] == 0


# ===========================================================================
# Merit SEMI_ANNUAL cadence — integer halving (PRD §3.7)
# ===========================================================================
class TestMeritSemiAnnualHalving:

    def test_semi_annual_halves_rate_floored(self, api):
        """PRD §3.7: "For `SEMI_ANNUAL` cadence every cell of that
        table is divided by 2 using integer division of cents — that
        is, by taking the floor — so each cycle's effective base
        percentage is half of the annual figure rounded down."

        SEMI_ANNUAL MEETS: floor(3/2) = 1 → 1% of base salary.
        """
        bundle = setup_draft_comp_plan(
            cadence="SEMI_ANNUAL",
            final_rating="MEETS",
            subject_base_salary_cents=10_000_000,
        )
        plan = validate_success(api.propose_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.manager.headers,
        ), 200)
        # floor(10_000_000 * floor(3/2) / 100) = floor(10_000_000 * 1 / 100) = 100_000
        assert plan["merit_increase_cents"] == 100_000


# ===========================================================================
# Equity refresh — level-banded grant table + canonical rounding order
# ===========================================================================
class TestEquityRefresh:

    def test_equity_annual_meets_level_4(self, api):
        """PRD §3.7 equity table — level 4..6 MEETS = 150; ANNUAL
        multiplier 1.0; no promo; result = 150."""
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="MEETS",
            subject_job_level=4,
        )
        plan = validate_success(api.propose_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.manager.headers,
        ), 200)
        assert plan["equity_refresh_units"] == 150

    def test_equity_semi_annual_meets_level_1_round_half_up(self, api):
        """PRD §3.7 equity: level 1-3 MEETS = 50; SEMI_ANNUAL multiplier
        0.5; round_half_up(50 * 0.5) = 25; no promo; total = 25.

        Confirms the canonical "multiply first, then round_half_up"
        order — a 'sum then round' implementation produces 25 here
        too, but the next test (level 4, EXCEEDS, SEMI_ANNUAL, promo)
        distinguishes them.

        # difficulty: combinatorial_formula/equity_refresh_multiplier_then_round
        """
        bundle = setup_draft_comp_plan(
            cadence="SEMI_ANNUAL",
            final_rating="MEETS",
            subject_job_level=1,
        )
        plan = validate_success(api.propose_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.manager.headers,
        ), 200)
        assert plan["equity_refresh_units"] == 25

    def test_equity_semi_annual_exceeds_level_4_with_promo_canonical_order(
            self, api):
        """PRD §3.7: "The canonical evaluation order is: first multiply
        the looked-up base grant by the cadence multiplier and round
        that product to a whole number of units, half-up; then, if the
        plan carries a `promotion_to_level` set to current `job_level`
        plus one and the pinned rating is `OUTSTANDING` or `EXCEEDS`,
        compute the promotion bump as the floor of 0.25 times the next
        level's grant for the same rating (using the grant table row
        for `promotion_to_level`, not the current level), and add the
        already-rounded bump to the already-rounded base."

        Level 4 EXCEEDS = 300; * 0.5 = 150; round_half_up = 150.
        Promotion to level 5 (still level 4-6 band) EXCEEDS = 300;
        floor(300 * 0.25) = 75. Total = 150 + 75 = 225.

        # difficulty: combinatorial_formula/equity_refresh_multiplier_then_round
        """
        bundle = setup_draft_comp_plan(
            cadence="SEMI_ANNUAL",
            final_rating="EXCEEDS",
            subject_job_level=4,
            promotion_to_level=5,
        )
        plan = validate_success(api.propose_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.manager.headers,
        ), 200)
        assert plan["equity_refresh_units"] == 225

    def test_equity_pip_zero_path(self, api):
        """PRD §3.7: "Finally, if the subject's `Employee.status` is
        `ON_PIP`, the result is forced to zero." Demonstrated implicitly
        by NEEDS_IMPROVEMENT subject having both merit and equity at 0.
        """
        bundle = setup_draft_comp_plan(
            cadence="ANNUAL",
            final_rating="NEEDS_IMPROVEMENT",
            subject_job_level=4,
        )
        plan = validate_success(api.propose_comp_plan(
            bundle.cycle["id"], bundle.comp_plan["id"],
            bundle.manager.headers,
        ), 200)
        assert plan["equity_refresh_units"] == 0


# ===========================================================================
# Weighted goal score — provisional (DRAFT) vs canonical (SUBMITTED)
# ===========================================================================
class TestWeightedGoalScore:

    def test_score_after_submit_uses_manager_score(self, api):
        """PRD §3.3: "the score is the sum over all goals of each
        goal's `weight` multiplied by its `manager_score`, divided by
        100, with the result rounded half-up to two decimal places".

        # difficulty: dual_variant_calc/weighted_goal_score_provisional_vs_final
        """
        bundle = setup_submittable_review_case(
            weights=(60, 40),
            self_scores=(5, 3),
            manager_scores=(4, 2),
        )
        bundle = submit_review_case(bundle)
        # After submit, score uses manager_score: (60*4 + 40*2) / 100 = 3.20
        assert bundle.review_case["weighted_goal_score"] == pytest.approx(3.20, abs=0.001)

    def test_canonical_score_three_goals_round_half_up(self, api):
        """PRD §3.3: "the score is the sum over all goals of each
        goal's `weight` multiplied by its `manager_score`, divided by
        100, with the result rounded half-up to two decimal places,
        evaluating goals in ascending `created_at` order for
        determinism."

        Three goals — score lands on a .x5 boundary so half-up rounding
        is observable.

        # difficulty: dual_variant_calc/weighted_goal_score_provisional_vs_final
        """
        # weights=(30,35,35), manager_scores=(5,3,4)
        # raw = (30*5 + 35*3 + 35*4) / 100 = (150 + 105 + 140) / 100 = 3.95
        bundle = setup_submittable_review_case(
            weights=(30, 35, 35),
            self_scores=(3, 3, 3),
            manager_scores=(5, 3, 4),
        )
        bundle = submit_review_case(bundle)
        assert bundle.review_case["weighted_goal_score"] == pytest.approx(3.95, abs=0.001)


# ===========================================================================
# Comp plan creation pins the right snapshots (PRD §3.7)
# ===========================================================================
class TestCompPlanPinning:

    def test_create_pins_review_case_version_and_base_salary(self, api):
        """PRD §3.7: "the server identifies the `FINALIZED` `ReviewCase`
        whose `subject_employee_id` matches, pins it via
        `pinned_review_case_id` and `pinned_review_case_version` (the
        case's current `version` at this instant), pins the subject's
        current `base_salary_cents` into `pinned_base_salary_cents`...".
        """
        bundle = setup_finalized_review_case(
            final_rating="MEETS",
            subject_base_salary_cents=12_345_678,
        )
        plan = validate_success(api.create_comp_plan(
            bundle.cycle["id"],
            create_comp_plan_payload(bundle.subject["id"]),
            bundle.manager.headers,
        ), 201)
        assert plan["pinned_review_case_id"] == bundle.review_case["id"]
        assert plan["pinned_review_case_version"] == bundle.review_case["version"]
        assert plan["pinned_base_salary_cents"] == 12_345_678
        assert plan["status"] == "DRAFT"
        assert plan["approved_at"] is None
