"""Foreclosure cases, sale scheduling gates, and dual-tracking compliance."""
import pytest

from test_helpers import (
    OPS,
    UW,
    ApiErrorId,
    FIXTURE_A_LOAN,
    FIXTURE_A_STATED_INCOME,
    FIXTURE_A_DOCS,
    FIXTURE_B_LOAN,
    FIXTURE_C_DOCS,
    FIXTURE_C_STATED_INCOME,
    acknowledge,
    board_loan,
    create_foreclosure_case_payload,
    create_schedule_sale_payload,
    create_std_mod_program,
    decide,
    get_application,
    get_foreclosure_case,
    get_loan,
    get_success_data,
    make_borrower,
    refer_and_schedule,
    refer_only,
    run_waterfall,
    set_clock,
    setup_appeal,
    setup_complete_application,
    setup_denial,
    submit_and_accept_documents,
    submit_application,
    validate_error,
    validate_success,
)


class TestReferralDelinquencyBoundary:
    def test_day_120_rejected(self, api, counsel_headers):
        """PRD §3.9: "The loan's `delinquency_days` must be strictly greater than
        120 — day 120 fails with `ERR_REFERRAL_TOO_EARLY`, day 121 passes."

        Design: Difficulty/boundary_precision_check/referral_delinquency_day_120_vs_121
        """
        borrower = make_borrower(full_name="Pam P", email="pam@x.com")
        loan = board_loan(
            borrower["id"], loan_number="LN-BP3A", arrears_cents=1_000_000,
            escrow_balance_cents=0, escrow_monthly_cents=0, delinquency_days=120,
            property_state_code="AZ",
        )
        res = api.create_foreclosure_case(
            loan["id"], create_foreclosure_case_payload(docket_number="FC-600"),
            counsel_headers,
        )
        validate_error(res, ApiErrorId.ERR_REFERRAL_TOO_EARLY, expected_status=422)

    def test_day_121_passes(self, api, counsel_headers):
        """PRD §3.9: "The loan's `delinquency_days` must be strictly greater than
        120 — day 120 fails with `ERR_REFERRAL_TOO_EARLY`, day 121 passes."

        Design: Difficulty/boundary_precision_check/referral_delinquency_day_120_vs_121
        """
        borrower = make_borrower(full_name="Pam P2", email="pam2@x.com")
        loan = board_loan(
            borrower["id"], loan_number="LN-BP3B", arrears_cents=1_000_000,
            escrow_balance_cents=0, escrow_monthly_cents=0, delinquency_days=121,
            property_state_code="AZ",
        )
        case = validate_success(
            api.create_foreclosure_case(
                loan["id"], create_foreclosure_case_payload(docket_number="FC-601"),
                counsel_headers,
            ),
            201,
        )
        assert case["status"] == "REFERRED"


class TestReferralGates:
    def test_second_referral_blocked_by_active_case(self, api, counsel_headers):
        """PRD §3.9: "One active case per loan: a referral while another
        non-terminal case exists is rejected with `ERR_FORECLOSURE_CASE_ACTIVE`."

        Design: Corner/errors/error_foreclosure_case_active_on_second_referral
        """
        borrower = make_borrower(full_name="Yusuf Y", email="yusuf@x.com")
        loan = board_loan(
            borrower["id"], loan_number="LN-ERR3", arrears_cents=1_000_000,
            escrow_balance_cents=0, escrow_monthly_cents=0, delinquency_days=150,
            property_state_code="AZ",
        )
        scenario = {"borrower": borrower, "loan": loan}
        refer_only(scenario, docket_number="FC-150")
        res = api.create_foreclosure_case(
            loan["id"], create_foreclosure_case_payload(docket_number="FC-151"),
            counsel_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORECLOSURE_CASE_ACTIVE, expected_status=409)

    def test_dual_tracking_beats_active_case_constraint(self, api, counsel_headers):
        """PRD §2.7: "When multiple validation rules could fire on a single
        request, the server evaluates them in this fixed priority order,
        returning the first failure:" — priority 8 is "**Compliance gates** —
        referral timing, dual-tracking blocks, sale-vs-appeal-window conflicts,
        segregation of duties: `ERR_REFERRAL_TOO_EARLY`,
        `ERR_DUAL_TRACKING_BLOCKED`, `ERR_SALE_WITHIN_APPEAL_WINDOW`,
        `ERR_SEGREGATION_OF_DUTIES`." while priority 10 is "**Structural
        constraints** — program rank uniqueness, one-active-foreclosure-case,
        escrow window overlap, escrow void ordering, computation-month bounds:
        `ERR_PROGRAM_RANK_DUPLICATE`, `ERR_FORECLOSURE_CASE_ACTIVE`,
        `ERR_ESCROW_YEAR_OVERLAP`, `ERR_ANALYSIS_VOID_BLOCKED`,
        `ERR_INVALID_COMP_MONTHS`."

        Design: Difficulty/priority_pair_validation_conflict/referral_dual_tracking_beats_active_case_constraint
        """
        borrower = make_borrower(full_name="Leo L", email="leo@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-PP2", **FIXTURE_A_LOAN)
        scenario = {"borrower": borrower, "loan": loan}
        refer_only(scenario, county="Clark", docket_number="FC-400")
        # A COMPLETE_PACKAGE application is a blocking state (violation of the
        # dual-tracking gate) AND a case already exists (one-active-case).
        app = submit_application(
            loan, borrower["id"], hardship_type="MEDICAL",
            stated_income=FIXTURE_A_STATED_INCOME,
        )
        acknowledge(app["id"])
        submit_and_accept_documents(app["id"], borrower["id"], FIXTURE_A_DOCS)
        res = api.create_foreclosure_case(
            loan["id"], create_foreclosure_case_payload(
                county="Clark", docket_number="FC-401"),
            counsel_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUAL_TRACKING_BLOCKED, expected_status=422)

    def test_dual_tracking_priority_leaves_case_register_untouched(self, api, counsel_headers):
        """PRD §3.9: "Dual tracking: no application for the loan may be in any
        blocking state (`COMPLETE_PACKAGE`, `EVALUATED_OFFER`, `APPEAL_REVIEW`,
        `TRIAL_ACTIVE`, `TRIAL_PASSED`); violation yields
        `ERR_DUAL_TRACKING_BLOCKED`." — the rejected referral must not persist.

        Design: Difficulty/priority_pair_validation_conflict/referral_dual_tracking_beats_active_case_constraint
        """
        borrower = make_borrower(full_name="Leo L2", email="leo2@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-PP2B", **FIXTURE_A_LOAN)
        scenario = {"borrower": borrower, "loan": loan}
        refer_only(scenario, county="Clark", docket_number="FC-400")
        app = submit_application(
            loan, borrower["id"], hardship_type="MEDICAL",
            stated_income=FIXTURE_A_STATED_INCOME,
        )
        acknowledge(app["id"])
        submit_and_accept_documents(app["id"], borrower["id"], FIXTURE_A_DOCS)
        res = api.create_foreclosure_case(
            loan["id"], create_foreclosure_case_payload(
                county="Clark", docket_number="FC-401"),
            counsel_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUAL_TRACKING_BLOCKED, expected_status=422)
        cases = get_success_data(api.list_loan_foreclosure_cases(loan["id"], counsel_headers))
        assert len(cases) == 1
        assert cases[0]["status"] == "REFERRED"
        assert cases[0]["docket_number"] == "FC-400"


class TestSaleSchedulingGates:
    def test_min_notice_clean_trigger_and_boundary(self, api, counsel_headers):
        """PRD §3.9: "**Minimum notice** — `sale_date` must be at least fourteen
        days after `referred_at`; otherwise `ERR_SALE_MIN_NOTICE`."

        Design: Corner/errors/error_sale_min_notice_clean_trigger
        """
        borrower = make_borrower(full_name="Xiu X", email="xiu@x.com")
        loan = board_loan(
            borrower["id"], loan_number="LN-ERR2", arrears_cents=1_000_000,
            escrow_balance_cents=0, escrow_monthly_cents=0, delinquency_days=150,
            property_state_code="AZ",
        )
        scenario = {"borrower": borrower, "loan": loan}
        refer_only(scenario, docket_number="FC-140")  # referred 2026-08-01
        case_id = scenario["case"]["id"]

        res = api.schedule_sale(case_id, {"sale_date": "2026-08-10"}, counsel_headers)
        validate_error(res, ApiErrorId.ERR_SALE_MIN_NOTICE, expected_status=422)

        # Exactly referred_at + 14 days: the boundary is inclusive ("at least").
        scheduled = validate_success(
            api.schedule_sale(case_id, {"sale_date": "2026-08-15"}, counsel_headers), 200
        )
        assert scheduled["status"] == "SALE_SCHEDULED"
        assert scheduled["sale_date"] == "2026-08-15"

    def test_sale_37_days_after_completion_blocked(self, api, counsel_headers):
        """PRD §3.9: "**37-day dual-tracking** — no blocking-state application
        may have its `completed_at` at least 37 days before `sale_date`;
        otherwise `ERR_DUAL_TRACKING_BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/sale_schedule_gated_by_blocking_application
        """
        borrower = make_borrower(full_name="Quinn Q", email="quinn@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-CE1", property_state_code="CO",
                          **{k: v for k, v in FIXTURE_A_LOAN.items() if k != "property_state_code"})
        scenario = {"borrower": borrower, "loan": loan}
        refer_only(scenario, county="Denver", docket_number="FC-700")
        app = submit_application(
            loan, borrower["id"], hardship_type="MEDICAL",
            stated_income=FIXTURE_A_STATED_INCOME,
        )
        acknowledge(app["id"])
        submit_and_accept_documents(
            app["id"], borrower["id"], FIXTURE_A_DOCS,
            complete_at="2026-08-05T00:00:00Z",
        )
        # 2026-09-11 is exactly 37 days after the 2026-08-05 completion.
        res = api.schedule_sale(
            scenario["case"]["id"], {"sale_date": "2026-09-11"}, counsel_headers
        )
        validate_error(res, ApiErrorId.ERR_DUAL_TRACKING_BLOCKED, expected_status=422)

    def test_sale_36_days_after_completion_allowed(self, api, counsel_headers):
        """PRD §3.9: "**37-day dual-tracking** — no blocking-state application
        may have its `completed_at` at least 37 days before `sale_date`;
        otherwise `ERR_DUAL_TRACKING_BLOCKED`." — 36 days is below the threshold.

        Design: Difficulty/cross_entity_state_dependency/sale_schedule_gated_by_blocking_application
        """
        borrower = make_borrower(full_name="Quinn Q2", email="quinn2@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-CE1B", property_state_code="CO",
                          **{k: v for k, v in FIXTURE_A_LOAN.items() if k != "property_state_code"})
        scenario = {"borrower": borrower, "loan": loan}
        refer_only(scenario, county="Denver", docket_number="FC-700")
        app = submit_application(
            loan, borrower["id"], hardship_type="MEDICAL",
            stated_income=FIXTURE_A_STATED_INCOME,
        )
        acknowledge(app["id"])
        submit_and_accept_documents(
            app["id"], borrower["id"], FIXTURE_A_DOCS,
            complete_at="2026-08-05T00:00:00Z",
        )
        scheduled = validate_success(
            api.schedule_sale(
                scenario["case"]["id"], {"sale_date": "2026-09-10"}, counsel_headers
            ),
            200,
        )
        assert scheduled["status"] == "SALE_SCHEDULED"
        assert scheduled["sale_date"] == "2026-09-10"

    def test_sale_on_appeal_deadline_day_collides(self, api, counsel_headers):
        """PRD §3.9: "**Appeal-window exclusion** — `sale_date` must not fall
        inside the closed interval from `issued_at` through `appeal_deadline` of
        any `ISSUED` or `APPEALED` denial notice for the loan; otherwise
        `ERR_SALE_WITHIN_APPEAL_WINDOW`." — the closed interval includes the
        deadline day itself.

        Design: Difficulty/resource_temporal_overlap/sale_date_closed_appeal_window_collision
        """
        scenario = self._denial_with_referred_case(api)
        # Notice window [2026-08-10, 2026-08-24]; the deadline day collides.
        res = api.schedule_sale(
            scenario["case"]["id"], {"sale_date": "2026-08-24"}, counsel_headers
        )
        validate_error(res, ApiErrorId.ERR_SALE_WITHIN_APPEAL_WINDOW, expected_status=422)

    def test_sale_day_after_appeal_deadline_free(self, api, counsel_headers):
        """PRD §3.9: "**Appeal-window exclusion** — `sale_date` must not fall
        inside the closed interval from `issued_at` through `appeal_deadline` of
        any `ISSUED` or `APPEALED` denial notice for the loan; otherwise
        `ERR_SALE_WITHIN_APPEAL_WINDOW`." — the day after the deadline is outside
        the closed interval.

        Design: Difficulty/resource_temporal_overlap/sale_date_closed_appeal_window_collision
        """
        scenario = self._denial_with_referred_case(api)
        scheduled = validate_success(
            api.schedule_sale(
                scenario["case"]["id"], {"sale_date": "2026-08-25"}, counsel_headers
            ),
            200,
        )
        assert scheduled["status"] == "SALE_SCHEDULED"
        assert scheduled["sale_date"] == "2026-08-25"

    def test_appeal_window_error_beats_min_notice(self, api, counsel_headers):
        """PRD §2.7: "When multiple validation rules could fire on a single
        request, the server evaluates them in this fixed priority order,
        returning the first failure:" — priority 8 is "**Compliance gates** —
        referral timing, dual-tracking blocks, sale-vs-appeal-window conflicts,
        segregation of duties: `ERR_REFERRAL_TOO_EARLY`,
        `ERR_DUAL_TRACKING_BLOCKED`, `ERR_SALE_WITHIN_APPEAL_WINDOW`,
        `ERR_SEGREGATION_OF_DUTIES`." while priority 9 is "**Temporal gates** —
        appeal window, appeal eligibility, sale minimum notice, rescission
        window: `ERR_APPEAL_WINDOW_EXPIRED`, `ERR_APPEAL_NOT_AVAILABLE`,
        `ERR_SALE_MIN_NOTICE`, `ERR_RESCISSION_WINDOW_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/sale_appeal_window_beats_min_notice
        """
        scenario = self._denial_with_referred_case(api)
        # 2026-08-12 violates BOTH the appeal window [08-10, 08-24] (compliance,
        # priority 8) and the 14-day minimum notice (earliest 08-15; priority 9).
        res = api.schedule_sale(
            scenario["case"]["id"], {"sale_date": "2026-08-12"}, counsel_headers
        )
        validate_error(res, ApiErrorId.ERR_SALE_WITHIN_APPEAL_WINDOW, expected_status=422)

    def test_appeal_window_priority_leaves_case_referred(self, api, counsel_headers):
        """PRD §2.7: "When multiple validation rules could fire on a single
        request, the server evaluates them in this fixed priority order,
        returning the first failure:" — so the rejected scheduling attempt
        leaves the case `REFERRED`, and a later date satisfying both "**Minimum
        notice** — `sale_date` must be at least fourteen days after
        `referred_at`; otherwise `ERR_SALE_MIN_NOTICE`." and the appeal-window
        exclusion succeeds.

        Design: Difficulty/priority_pair_validation_conflict/sale_appeal_window_beats_min_notice
        """
        scenario = self._denial_with_referred_case(api)
        res = api.schedule_sale(
            scenario["case"]["id"], {"sale_date": "2026-08-12"}, counsel_headers
        )
        validate_error(res, ApiErrorId.ERR_SALE_WITHIN_APPEAL_WINDOW, expected_status=422)
        assert get_foreclosure_case(scenario["case"]["id"])["status"] == "REFERRED"
        # 2026-08-25: past the 14-day minimum notice and outside [08-10, 08-24].
        scheduled = validate_success(
            api.schedule_sale(
                scenario["case"]["id"], {"sale_date": "2026-08-25"}, counsel_headers
            ),
            200,
        )
        assert scheduled["status"] == "SALE_SCHEDULED"

    def _denial_with_referred_case(self, api):
        """Case REFERRED (2026-08-01) before the application; fixture C denial
        issued 2026-08-10 -> appeal window [2026-08-10, 2026-08-24]."""
        borrower = make_borrower()
        loan = board_loan(borrower["id"], **FIXTURE_B_LOAN)
        create_std_mod_program()
        scenario = {"borrower": borrower, "loan": loan}
        refer_only(scenario, county="Fulton", docket_number="FC-900")
        app = submit_application(
            loan, borrower["id"], hardship_type="UNEMPLOYMENT",
            stated_income=FIXTURE_C_STATED_INCOME,
        )
        acknowledge(app["id"])
        submit_and_accept_documents(app["id"], borrower["id"], FIXTURE_C_DOCS)
        set_clock("2026-08-10T00:00:00Z")
        evaluation = run_waterfall(app["id"])
        assert evaluation["result"] == "DENIAL"
        scenario["application"] = get_application(app["id"])
        scenario["evaluation"] = evaluation
        return scenario


class TestParallelDimensions:
    def test_application_moves_workout_dimension_only(self, api):
        """PRD §3.9: "The two loan dimensions evolve independently except at
        explicit gates."
        PRD §3.2: "The submission also bumps the loan's `version` by one and
        transitions the loan's `workout_status` from `DELINQUENT` to
        `LOSS_MIT_REVIEW`."

        Design: Difficulty/non_linear_state_machine/loan_parallel_workout_foreclosure_dimensions
        """
        borrower = make_borrower(full_name="Frank F", email="frank@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-NL2", property_state_code="FL",
                          **{k: v for k, v in FIXTURE_A_LOAN.items() if k != "property_state_code"})
        scenario = {"borrower": borrower, "loan": loan}
        refer_and_schedule(scenario, "2026-12-01", county="Miami-Dade",
                           docket_number="FC-100")
        submit_application(
            loan, borrower["id"], hardship_type="MEDICAL", stated_income=400_000
        )
        after = get_loan(loan["id"])
        assert after["workout_status"] == "LOSS_MIT_REVIEW"
        assert after["foreclosure_status"] == "SALE_SCHEDULED"

    def test_foreclosure_case_untouched_by_application(self, api, counsel_headers):
        """PRD §3.9: "A loan's `foreclosure_status` is a computed mirror of its
        latest non-`CANCELLED` `ForeclosureCase`: `NONE` when no active case
        exists, otherwise one of `REFERRED`, `SALE_SCHEDULED`, `SALE_HOLD`,
        `SALE_COMPLETED`. The two loan dimensions evolve independently except at
        explicit gates."

        Design: Difficulty/non_linear_state_machine/loan_parallel_workout_foreclosure_dimensions
        """
        borrower = make_borrower(full_name="Frank F2", email="frank2@x.com")
        loan = board_loan(borrower["id"], loan_number="LN-NL2B", property_state_code="FL",
                          **{k: v for k, v in FIXTURE_A_LOAN.items() if k != "property_state_code"})
        scenario = {"borrower": borrower, "loan": loan}
        refer_and_schedule(scenario, "2026-12-01", county="Miami-Dade",
                           docket_number="FC-100")
        submit_application(
            loan, borrower["id"], hardship_type="MEDICAL", stated_income=400_000
        )
        case = get_foreclosure_case(scenario["case"]["id"])
        assert case["status"] == "SALE_SCHEDULED"
        assert case["sale_date"] == "2026-12-01"


class TestSaleHoldRescheduleCycle:
    def _overturned_with_hold(self, api):
        scenario = setup_denial(
            sale_date="2026-12-01",
            complete_at="2026-08-05T00:00:00Z",
            denied_at="2026-08-10T00:00:00Z",
        )
        scenario = setup_appeal(scenario, appeal_at="2026-08-12T00:00:00Z",
                                grounds="income miscalculated")
        set_clock("2026-08-14T00:00:00Z")
        scenario["appeal"] = decide(scenario, "OVERTURNED", reviewer_user_id="rev_1")
        return scenario

    def test_overturn_moves_scheduled_case_to_hold(self, api):
        """PRD §3.9: "A scheduled sale can be displaced automatically: when an
        appeal overturn returns an application to `COMPLETE_PACKAGE` (§3.8, L2),
        the active case moves from `SALE_SCHEDULED` to `SALE_HOLD` and the mirror
        follows."

        Design: Difficulty/non_linear_state_machine/foreclosure_sale_hold_reschedule_cycle
        """
        scenario = self._overturned_with_hold(api)
        assert get_foreclosure_case(scenario["case"]["id"])["status"] == "SALE_HOLD"
        assert get_loan(scenario["loan"]["id"])["foreclosure_status"] == "SALE_HOLD"
        assert (
            get_application(scenario["application"]["id"])["status"]
            == "COMPLETE_PACKAGE"
        )

    def test_reschedule_from_hold_after_redenial(self, api, counsel_headers):
        """PRD §3.9: "Re-scheduling from `SALE_HOLD` re-applies all three
        scheduling gates." and "Scheduling a sale moves a case from `REFERRED`
        (or re-schedules from `SALE_HOLD`) to `SALE_SCHEDULED`, taking a
        `sale_date`." — after the re-evaluation denies again, the application is
        in the non-blocking `EVALUATED_DENIAL` state and the gates pass.

        Design: Difficulty/non_linear_state_machine/foreclosure_sale_hold_reschedule_cycle
        """
        scenario = self._overturned_with_hold(api)
        # Same economics re-evaluated -> DENIAL again (non-blocking state).
        ev2 = run_waterfall(scenario["application"]["id"], underwriter_user_id="uw_2")
        assert ev2["result"] == "DENIAL"
        assert (
            get_application(scenario["application"]["id"])["status"]
            == "EVALUATED_DENIAL"
        )
        scheduled = validate_success(
            api.schedule_sale(
                scenario["case"]["id"], {"sale_date": "2026-12-05"}, counsel_headers
            ),
            200,
        )
        assert scheduled["status"] == "SALE_SCHEDULED"
        assert scheduled["sale_date"] == "2026-12-05"


class TestCaseTerminalTransitions:
    def test_complete_sale_requires_scheduled_state(self, api, counsel_headers):
        """PRD §3.9: "Marking the sale held requires the case to be in
        `SALE_SCHEDULED` (else `ERR_FORECLOSURE_STATE_INVALID`) and moves it to
        `SALE_COMPLETED`."

        Design: Corner/state_machines/complete_sale_requires_scheduled_state
        """
        borrower = make_borrower(full_name="Pia P", email="pia@x.com")
        loan = board_loan(
            borrower["id"], loan_number="LN-SM8", arrears_cents=1_000_000,
            escrow_balance_cents=0, escrow_monthly_cents=0, delinquency_days=150,
            property_state_code="AZ",
        )
        scenario = {"borrower": borrower, "loan": loan}
        refer_only(scenario, docket_number="FC-110")
        res = api.complete_sale(scenario["case"]["id"], counsel_headers)
        validate_error(res, ApiErrorId.ERR_FORECLOSURE_STATE_INVALID, expected_status=409)
        assert get_foreclosure_case(scenario["case"]["id"])["status"] == "REFERRED"

    def test_cancel_restores_loan_mirror_none(self, api, counsel_headers):
        """PRD §3.9: "Cancelling is allowed from `REFERRED`, `SALE_SCHEDULED`, or
        `SALE_HOLD`; the case lands in `CANCELLED` and the loan's mirror returns
        to `NONE`."

        Design: Corner/state_machines/foreclosure_cancel_restores_loan_mirror_none
        """
        borrower = make_borrower(full_name="Ray R", email="ray@x.com")
        loan = board_loan(
            borrower["id"], loan_number="LN-SM9", arrears_cents=1_000_000,
            escrow_balance_cents=0, escrow_monthly_cents=0, delinquency_days=150,
            property_state_code="AZ",
        )
        scenario = {"borrower": borrower, "loan": loan}
        refer_only(scenario, docket_number="FC-120")
        assert get_loan(loan["id"])["foreclosure_status"] == "REFERRED"
        cancelled = validate_success(
            api.cancel_foreclosure_case(scenario["case"]["id"], counsel_headers), 200
        )
        assert cancelled["status"] == "CANCELLED"
        assert get_loan(loan["id"])["foreclosure_status"] == "NONE"
