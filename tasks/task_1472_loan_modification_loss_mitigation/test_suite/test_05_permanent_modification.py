"""Permanent modification: dual-variant terms, record cascade, rescission."""
import pytest

from test_helpers import (
    OPS,
    UW,
    ApiErrorId,
    get_application,
    get_escrow_analysis,
    get_loan,
    get_modification,
    get_success_data,
    set_clock,
    setup_completed_trial,
    setup_modification,
    create_modification_for,
    validate_error,
    validate_success,
)


class TestDualVariantTerms:
    def _fixture_a_modification(self, api):
        """Fixture A walked through evaluation OFFER and a completed trial;
        returns (scenario, modification) with the modification in DRAFT."""
        scenario = setup_completed_trial(
            economics="A",
            complete_at="2026-08-05T00:00:00Z",
            eval_at="2026-08-06T00:00:00Z",
        )
        return scenario, create_modification_for(scenario)

    def test_provisional_variant_frozen_on_evaluation(self, api):
        """PRD §3.6: "1. **Capitalized base** — `eval_base_cents` is the loan's
        `unpaid_principal_balance_cents` plus its `arrears_cents` as they stand
        at evaluation time (before any trial-suspense application)."
        PRD §3.6: "**OFFER** — `result` is `OFFER`, `selected_program_id` is set,
        and the offered terms are frozen onto the evaluation as
        `offered_rate_bp`, `offered_term_months`, `offered_forbearance_cents`,
        and `offered_pi_cents`."

        Design: Difficulty/dual_variant_calc/waterfall_provisional_vs_final_modification_terms
        """
        scenario, _mod = self._fixture_a_modification(api)
        ev = scenario["evaluation"]
        # Provisional base: 20000000 + 1200000 = 21200000 (pre-suspense).
        assert ev["eval_base_cents"] == 21_200_000
        assert ev["offered_rate_bp"] == 575
        assert ev["offered_term_months"] == 240
        assert ev["offered_pi_cents"] == 148_842

    def test_final_variant_diverges_after_suspense_application(self, api):
        """PRD §3.10: "The modification is created in `DRAFT` with the **final
        variant** of the waterfall calculation: the base is the loan's
        `unpaid_principal_balance_cents` plus its `arrears_cents` **as of
        modification creation** — that is, after the trial-suspense application
        has already reduced arrears. Because the provisional variant used the
        pre-suspense arrears, the final base (and therefore `final_pi_cents` and
        `final_forbearance_cents`) diverges from the provisional numbers even for
        identical program and income."

        Design: Difficulty/dual_variant_calc/waterfall_provisional_vs_final_modification_terms
        """
        scenario, mod = self._fixture_a_modification(api)
        ev = scenario["evaluation"]
        # Final base: 20000000 + 663474 = 20663474 (post-suspense arrears).
        assert mod["final_base_cents"] == 20_663_474
        assert mod["capitalized_arrears_cents"] == 663_474
        assert mod["final_rate_bp"] == 600
        assert mod["final_pi_cents"] == 148_040
        assert mod["final_pi_cents"] != ev["offered_pi_cents"], (
            "same program and income, but the final base diverges from provisional"
        )


class TestRecordCascade:
    def test_record_rewrites_loan_terms_and_approves_application(self, api):
        """PRD §3.10: "**L1 — loan terms rewritten.** `unpaid_principal_balance_cents`
        becomes `final_base_cents` minus `final_forbearance_cents`;
        `deferred_principal_cents` becomes `final_forbearance_cents` (the
        forborne principal is non-interest-bearing); `interest_rate_bp` becomes
        `final_rate_bp`; `remaining_term_months` becomes `final_term_months`;
        `arrears_cents` is zeroed (the arrears were capitalized into the base);
        `current_pi_cents` is recomputed from the new terms; and
        `workout_status` moves to `PERMANENTLY_MODIFIED`."
        PRD §3.10: "**L2 — application approved.** Caused by the workout
        dimension reaching `PERMANENTLY_MODIFIED`, the application moves from
        `TRIAL_PASSED` to the terminal `APPROVED`."

        Design: Difficulty/transitive_cascade/modification_record_three_level_cascade
        """
        scenario = setup_modification(
            status="RECORDED", economics="A",
            eval_at="2026-08-06T00:00:00Z", record_at="2026-11-15T00:00:00Z",
        )
        loan = scenario["loan"]
        assert loan["workout_status"] == "PERMANENTLY_MODIFIED"
        assert loan["unpaid_principal_balance_cents"] == 20_663_474
        assert loan["deferred_principal_cents"] == 0
        assert loan["arrears_cents"] == 0
        assert loan["interest_rate_bp"] == 600
        assert loan["remaining_term_months"] == 240
        assert loan["current_pi_cents"] == 148_040
        assert scenario["application"]["status"] == "APPROVED"
        mod = scenario["modification"]
        assert mod["status"] == "RECORDED"
        assert mod["recorded_at"] is not None

    def test_record_auto_creates_post_modification_escrow_analysis(self, api):
        """PRD §3.10: "**L3 — escrow analysis auto-created.** Caused by the
        application reaching `APPROVED`, the system creates an `EscrowAnalysis`
        of type `POST_MODIFICATION` in `DRAFT`, with `modification_id` set to the
        modification, `comp_year_start_month` equal to the calendar month of
        `recorded_at` in `YYYY-MM` form, `comp_year_months` equal to thirteen
        minus the month number of `recorded_at` (so a March recording yields a
        ten-month window covering March through December), and
        `projected_annual_disbursements_cents` equal to the loan's
        `escrow_monthly_cents` multiplied by twelve."

        Design: Difficulty/transitive_cascade/modification_record_three_level_cascade
        """
        scenario = setup_modification(
            status="RECORDED", economics="A",
            eval_at="2026-08-06T00:00:00Z", record_at="2026-11-15T00:00:00Z",
        )
        analyses = get_success_data(
            api.list_loan_escrow_analyses(scenario["loan"]["id"], OPS)
        )
        assert len(analyses) == 1
        analysis = analyses[0]
        assert analysis["analysis_type"] == "POST_MODIFICATION"
        assert analysis["status"] == "DRAFT"
        assert analysis["modification_id"] == scenario["modification"]["id"]
        # Recorded 2026-11-15: start month 2026-11, months = 13 - 11 = 2.
        assert analysis["comp_year_start_month"] == "2026-11"
        assert analysis["comp_year_months"] == 2
        # Disbursements = escrow_monthly 30000 * 12 = 360000; cushion 60000;
        # balance snapshot 30000 -> shortage 30000 spread over 2 months.
        assert analysis["projected_annual_disbursements_cents"] == 360_000
        assert analysis["cushion_cents"] == 60_000
        assert analysis["balance_at_analysis_cents"] == 30_000
        assert analysis["shortage_cents"] == 30_000
        assert analysis["monthly_spread_cents"] == 15_000
        assert analysis["new_monthly_escrow_cents"] == 45_000


class TestRecordRescindConservation:
    def test_record_conserves_total_secured_obligation(self, api):
        """PRD §3.10: "**L1 — loan terms rewritten.** `unpaid_principal_balance_cents`
        becomes `final_base_cents` minus `final_forbearance_cents`;
        `deferred_principal_cents` becomes `final_forbearance_cents` (the
        forborne principal is non-interest-bearing); ... `arrears_cents` is
        zeroed (the arrears were capitalized into the base)".

        Design: Difficulty/compensating_invariant/modification_record_rescind_obligation_conservation
        """
        scenario = setup_modification(
            status="RECORDED", economics="B", record_at="2026-11-15T00:00:00Z"
        )
        loan = scenario["loan"]
        # Post-trial arrears 6000000 - 300000 = 5700000; final base 35700000;
        # forbearance 2677697 -> UPB 33022303. Obligation conserved:
        # 33022303 + 2677697 + 0 == 35700000 == 30000000 + 5700000.
        assert loan["unpaid_principal_balance_cents"] == 33_022_303
        assert loan["deferred_principal_cents"] == 2_677_697
        assert loan["arrears_cents"] == 0
        total = (
            loan["unpaid_principal_balance_cents"]
            + loan["deferred_principal_cents"]
            + loan["arrears_cents"]
        )
        assert total == 35_700_000 == 30_000_000 + 5_700_000

    def test_rescind_restores_prior_terms_snapshot(self, api):
        """PRD §3.10: "Rescission restores the loan terms from
        `prior_terms_snapshot` (UPB, rate, term, and arrears all return), resets
        `deferred_principal_cents` to zero, moves the loan's `workout_status`
        back to `MOD_PENDING`, moves the application from `APPROVED` back to
        `TRIAL_PASSED`, and — if the auto-created escrow analysis is still in
        `DRAFT` — cancels it (`DRAFT` → `CANCELLED`)."
        PRD §3.10: "while now is at or before `rescission_deadline`, a
        `ServicingOps` operator can rescind a `RECORDED` modification, moving it
        from `RECORDED` to the terminal `RESCINDED`".

        Design: Difficulty/compensating_invariant/modification_record_rescind_obligation_conservation
        """
        scenario = setup_modification(
            status="RECORDED", economics="B", record_at="2026-11-15T00:00:00Z"
        )
        mod_id = scenario["modification"]["id"]
        set_clock("2026-11-18T00:00:00Z")  # within the inclusive 3-day window
        rescinded = validate_success(api.rescind_modification(mod_id, OPS), 200)
        assert rescinded["status"] == "RESCINDED"

        loan = get_loan(scenario["loan"]["id"])
        assert loan["unpaid_principal_balance_cents"] == 30_000_000
        assert loan["arrears_cents"] == 5_700_000
        assert loan["deferred_principal_cents"] == 0
        assert loan["interest_rate_bp"] == 600
        assert loan["remaining_term_months"] == 240
        assert loan["workout_status"] == "MOD_PENDING"
        assert (
            get_application(scenario["application"]["id"])["status"] == "TRIAL_PASSED"
        )
        analyses = get_success_data(
            api.list_loan_escrow_analyses(scenario["loan"]["id"], OPS)
        )
        assert analyses[0]["status"] == "CANCELLED"


class TestModificationStateGates:
    def test_record_requires_signed_state(self, api, ops_headers):
        """PRD §3.10: "The lifecycle then walks `DRAFT` → `DOCS_SENT` (ops sends
        the documents) → `SIGNED` (the borrower signs) → `RECORDED` (ops
        records). Each step is gated on the prior state — any other source state
        yields `ERR_MODIFICATION_STATE_INVALID`."

        Design: Corner/state_machines/modification_record_requires_signed_state
        """
        scenario = setup_modification(status="DRAFT", economics="B")
        res = api.record_modification(scenario["modification"]["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_MODIFICATION_STATE_INVALID, expected_status=409)
        mod = get_modification(scenario["modification"]["id"])
        assert mod["status"] == "DRAFT"
        loan = get_loan(scenario["loan"]["id"])
        assert loan["unpaid_principal_balance_cents"] == 30_000_000
        assert loan["arrears_cents"] == 5_700_000

    def test_rescission_window_expired(self, api, ops_headers):
        """PRD §3.10: "while now is at or before `rescission_deadline`, a
        `ServicingOps` operator can rescind a `RECORDED` modification, moving it
        from `RECORDED` to the terminal `RESCINDED`; after the deadline the call
        is rejected with `ERR_RESCISSION_WINDOW_EXPIRED`."
        PRD §3.10: "stamps `recorded_at` and `rescission_deadline` (the recording
        instant plus three days, inclusive)."

        Design: Corner/errors/error_rescission_window_expired
        """
        scenario = setup_modification(
            status="RECORDED", economics="B", record_at="2026-11-15T00:00:00Z"
        )
        # Deadline: recorded 2026-11-15 + 3 days = 2026-11-18 inclusive.
        set_clock("2026-11-19T00:00:00Z")
        res = api.rescind_modification(scenario["modification"]["id"], ops_headers)
        validate_error(res, ApiErrorId.ERR_RESCISSION_WINDOW_EXPIRED, expected_status=422)
        mod = get_modification(scenario["modification"]["id"])
        assert mod["status"] == "RECORDED"
        loan = get_loan(scenario["loan"]["id"])
        assert loan["workout_status"] == "PERMANENTLY_MODIFIED"
        assert loan["unpaid_principal_balance_cents"] == 33_022_303
