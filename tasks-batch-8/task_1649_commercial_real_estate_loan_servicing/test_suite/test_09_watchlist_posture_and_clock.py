"""The watchlist risk score, payment-dimension transitions, escalation and
reinstatement cascades, and the deterministic clock sweep."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    appraise_property,
    approve_draw,
    complete_inspection,
    create_borrower,
    create_draw,
    create_extension_option,
    create_inspector,
    create_loan,
    create_property,
    create_reserve_account,
    deposit_reserve,
    get_draw_by_id,
    get_loan,
    get_reserve,
    get_success_data,
    list_watchlist_entries,
    make_borrower_headers,
    schedule_inspection,
    set_clock,
    set_payment_status,
    setup_special_servicing_loan,
    setup_watchlist_via_dscr_breach,
    single_watchlist_entry,
    submit_and_accept_statement,
    submit_statement,
    validate_error,
    validate_paginated,
    validate_success,
    waive_assessment,
)

MS = TEST_USERS["master_servicer_headers"]
SS = TEST_USERS["special_servicer_headers"]

Q2_2026 = ("2026-04-01T00:00:00Z", "2026-06-30T00:00:00Z")


def _option_status(api, loan_id, option_id):
    rows, _meta = validate_paginated(api.list_extension_options(loan_id, MS))
    for row in rows:
        if row["id"] == option_id:
            return row["status"]
    raise AssertionError(f"extension option {option_id} not found")


class TestRiskScoreWithSynergy:
    def _setup_risk_loan(self):
        """DSCR 0.9500 OPEN breach + LTV 0.7000, then DELINQUENT at the
        2026-08-01 clock and a sweep to 2026-08-31 (30 days)."""
        borrower = create_borrower(legal_name="Risk Holdings", tax_id="TX-RSK-1",
                                   contact_email="risk@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-RSK",
                           original_principal_cents=1_000_000_000,
                           current_balance_cents=700_000_000, note_rate=0.06,
                           origination_date="2026-04-01T00:00:00Z",
                           dscr_covenant_threshold=1.20,
                           ltv_covenant_threshold=0.90,
                           dscr_basis="T3_ANNUALIZED")
        prop = create_property(loan["id"], address="9 Risk Ave",
                               property_type="RETAIL",
                               appraised_value_cents=1_000_000_000)
        # A fresh appraisal at the same value forces the LTV computation.
        appraise_property(prop["id"], 1_000_000_000, "2026-06-01T00:00:00Z")
        submit_and_accept_statement(loan["id"], borrower["id"], "RENT_ROLL",
                                    *Q2_2026, occupancy_pct=92.5)
        # T3: 14,250,000 x 4 = 57,000,000 / 60,000,000 = 0.9500 < 1.20 -> OPEN.
        submit_and_accept_statement(loan["id"], borrower["id"],
                                    "OPERATING_STATEMENT", *Q2_2026,
                                    net_operating_income_cents=14_250_000)
        # Delinquent at 2026-08-01: 0 days -> no synergy yet, score 60 < 70.
        set_payment_status(loan["id"], "DELINQUENT")
        # 30 days delinquent: sweep re-eval scores 45+20+5+10+10 = 90 >= 70.
        set_clock("2026-08-31T00:00:00Z")
        # A FAIR inspection afterwards keeps the inspection component at 5.
        inspector = create_inspector(full_name="Rita Spector", license_no="LIC-RSK")
        insp = schedule_inspection(prop["id"], inspector["id"],
                                   scheduled_start="2026-08-31T09:00:00Z",
                                   scheduled_end="2026-08-31T10:00:00Z")
        complete_inspection(insp["id"], inspector["id"], "FAIR")
        return borrower, loan

    def test_risk_score_entry_created_with_tiered_score_90(self, api):
        """PRD §3.6: "The coverage component reads the loan's `current_dscr`: 0
        when it is at least 1.25, 15 when below 1.25 but at least 1.10, 30 when
        below 1.10 but at least 1.00, 45 when below 1.00, and 10 when no DSCR has
        ever been computed. The delinquency component reads `days_delinquent`: 0
        when the loan is not delinquent, 10 from one through twenty-nine days, 20
        from thirty through fifty-nine days, and 35 at sixty days or more. The
        property component reads the most recently completed inspection across the
        loan's properties: 0 for `GOOD`, 5 for `FAIR`, 15 for `POOR`, 25 for
        `CRITICAL`, and 5 when no completed inspection exists. The collateral
        component reads `current_ltv`: 0 when below 0.65, 10 when at least 0.65
        but below 0.75, 20 when at least 0.75 but below 0.85, 30 at 0.85 or above,
        and 10 when no LTV has ever been computed. Finally, a synergy supplement
        of 10 points is added whenever the loan is at least thirty days delinquent
        and its current DSCR is below 1.00."
        PRD §3.6: "Whenever the total reaches 70 or more and the loan has no
        currently `ACTIVE` risk-score entry, the system opens an entry with
        criterion `RISK_SCORE`, recording the score in `risk_score_at_creation`
        and flagging `escalation_review` when the score is 85 or higher."

        Design: Difficulty/combinatorial_formula/watchlist_risk_score_tiered_with_synergy
        """
        _b, loan = self._setup_risk_loan()
        # 45 (DSCR 0.95 < 1.00) + 20 (30 days) + 5 (FAIR/none) + 10 (LTV 0.70)
        # + 10 (synergy: >= 30 days and DSCR < 1.00) = 90.
        entry = single_watchlist_entry(loan["id"], criterion="RISK_SCORE",
                                       status="ACTIVE")
        assert entry["risk_score_at_creation"] == 90
        assert entry["escalation_review"] is True, "90 >= 85 flags escalation review"

    def test_risk_score_inputs_reconcile_on_loan(self, api):
        """PRD §3.6: "The loan's `days_delinquent` is derived on read — the whole
        days elapsed since `delinquent_since`, meaning the elapsed seconds divided
        by 86,400 and rounded down, while the loan stands `DELINQUENT` or
        `DEFAULT`, and zero otherwise."
        PRD §3.6: "Whenever the total reaches 70 or more and the loan has no
        currently `ACTIVE` risk-score entry, the system opens an entry with
        criterion `RISK_SCORE`" (an already-ACTIVE entry suppresses duplicates).

        Design: Difficulty/combinatorial_formula/watchlist_risk_score_tiered_with_synergy
        """
        _b, loan = self._setup_risk_loan()
        rows, meta = validate_paginated(api.list_watchlist_entries(
            loan["id"], MS, params={"criterion": "RISK_SCORE"}))
        assert meta["total_count"] == 1, (
            "re-evaluation after the FAIR completion creates no duplicate entry")
        loan_after = get_loan(loan["id"])
        assert loan_after["days_delinquent"] == 30, (
            "2026-08-01 to 2026-08-31 is 30 whole days")
        assert loan_after["payment_status"] == "DELINQUENT"
        assert loan_after["servicing_status"] == "WATCHLIST"
        assert loan_after["current_dscr"] == pytest.approx(0.95, abs=1e-9)
        assert loan_after["current_ltv"] == pytest.approx(0.70, abs=1e-9)


class TestParallelDimensions:
    def test_payment_dimension_moves_without_touching_servicing(self, api):
        """PRD §2.9: "Every loan carries two independent status dimensions. The
        payment dimension, `payment_status`, moves among `CURRENT`, `DELINQUENT`,
        `DEFAULT`, and `MATURITY_DEFAULT` under operator action and the clock
        sweep. The servicing dimension, `servicing_status`, moves among
        `PERFORMING`, `WATCHLIST`, and `SPECIAL_SERVICING` and is derived rather
        than written directly: the system recomputes it whenever covenant
        assessments or watchlist entries change."
        PRD §3.6: "Marking a loan delinquent stamps `delinquent_since` with the
        clock time; curing back to `CURRENT` clears it to null."

        Design: Difficulty/non_linear_state_machine/loan_parallel_dimensions_move_independently
        """
        ctx = setup_watchlist_via_dscr_breach(tax_id="TX-PAR", reviewer_id="ms_user_1")
        loan = ctx["loan"]
        assert get_loan(loan["id"])["servicing_status"] == "WATCHLIST"

        delinquent = set_payment_status(loan["id"], "DELINQUENT")
        assert delinquent["payment_status"] == "DELINQUENT"
        assert delinquent["servicing_status"] == "WATCHLIST", (
            "the payment dimension moves without touching the servicing dimension")
        assert delinquent["delinquent_since"] is not None

        cured = set_payment_status(loan["id"], "CURRENT")
        assert cured["payment_status"] == "CURRENT"
        assert cured["delinquent_since"] is None
        assert cured["servicing_status"] == "WATCHLIST", (
            "the OPEN assessment still holds the posture at WATCHLIST")

    def test_waiver_releases_servicing_independently(self, api):
        """PRD §3.2: "A `SpecialServicer` may waive an `OPEN` assessment,
        supplying a `waiver_reason`; the assessment moves to `WAIVED` and records
        the operator in `waived_by_user_id`, which stays null on every non-waived
        assessment."
        PRD §3.2: "A waiver re-evaluates the servicing posture and may let a
        `WATCHLIST` loan de-escalate to `PERFORMING`, de-elevating its reserves in
        the process."
        PRD §3.2: "for a DSCR assessment the acting `X-User-ID` must differ from
        the source statement's `reviewed_by_user_id`"

        Design: Difficulty/non_linear_state_machine/loan_parallel_dimensions_move_independently
        """
        ctx = setup_watchlist_via_dscr_breach(tax_id="TX-PARB",
                                              reviewer_id="ms_user_1")
        loan = ctx["loan"]
        set_payment_status(loan["id"], "DELINQUENT")
        set_payment_status(loan["id"], "CURRENT")
        # The reviewer was ms_user_1; a different operator (ss_user_1) passes SoD.
        waived = waive_assessment(ctx["assessment"]["id"], "one-time leasing dip",
                                  waver_id="ss_user_1")
        assert waived["status"] == "WAIVED"
        assert waived["waived_by_user_id"] == "ss_user_1"
        loan_after = get_loan(loan["id"])
        assert loan_after["servicing_status"] == "PERFORMING", (
            "clearing the last open item lets the posture fall back")
        assert loan_after["payment_status"] == "CURRENT"


class TestEscalationCascade:
    def test_escalate_to_special_servicing_cascades(self, api):
        """PRD §3.6: "Escalation is the point of transfer into workout. The entry
        becomes `ESCALATED`, the loan moves `WATCHLIST` → `SPECIAL_SERVICING`, and
        the cascade is exact: every reserve account of the loan sets
        `disbursement_frozen` to true while `elevated_retainage` stays on; every
        still-`SUBMITTED` draw request on those reserves moves to `REJECTED`,
        having never held funds; every `APPROVED` draw moves to `CANCELLED` with
        its hold released back out of `held_cents`; and every `AVAILABLE`
        extension option moves to `SUSPENDED`."

        Design: Corner/state_machines/escalate_to_special_servicing_cascades
        """
        borrower = create_borrower(legal_name="Esc Co", tax_id="TX-ESC",
                                   contact_email="esc@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-ESC",
                           original_principal_cents=100_000_000, note_rate=0.05,
                           maturity_date="2027-06-30T00:00:00Z")
        prop = create_property(loan["id"], address="1 Esc St")
        reserve = create_reserve_account(loan["id"])
        reserve = deposit_reserve(reserve["id"], 1_000_000)
        draw1 = create_draw(reserve["id"], borrower["id"], "CAPITAL_REPAIR",
                            [{"description": "d1", "amount_cents": 100_000}])
        draw2 = create_draw(reserve["id"], borrower["id"], "TENANT_IMPROVEMENT",
                            [{"description": "d2", "amount_cents": 200_000}])
        approve_draw(draw2["id"])  # hold 200,000
        option = create_extension_option(
            loan["id"], option_seq=1,
            exercise_window_start="2026-12-01T00:00:00Z",
            exercise_window_end="2027-03-01T00:00:00Z")
        inspector = create_inspector(full_name="Esc Spect", license_no="LIC-ESC")
        insp = schedule_inspection(prop["id"], inspector["id"],
                                   scheduled_start="2026-08-01T09:00:00Z",
                                   scheduled_end="2026-08-01T10:00:00Z")
        complete_inspection(insp["id"], inspector["id"], "POOR")
        entry = single_watchlist_entry(loan["id"], criterion="POOR_INSPECTION",
                                       status="ACTIVE")

        escalated = get_success_data(
            api.escalate_watchlist_entry(entry["id"], MS))
        assert escalated["status"] == "ESCALATED"
        assert get_loan(loan["id"])["servicing_status"] == "SPECIAL_SERVICING"

        reserve_after = get_reserve(reserve["id"])
        assert reserve_after["disbursement_frozen"] is True
        assert reserve_after["elevated_retainage"] is True, "elevation stays on"
        assert reserve_after["held_cents"] == 0, "the 200,000 hold is released"
        assert reserve_after["balance_cents"] == 1_000_000, "no cash moves"

        assert get_draw_by_id(reserve["id"], draw1["id"])["status"] == "REJECTED"
        assert get_draw_by_id(reserve["id"], draw2["id"])["status"] == "CANCELLED"
        assert _option_status(api, loan["id"], option["id"]) == "SUSPENDED"


class TestReinstatement:
    def test_reinstate_restores_performing_and_unsuspends(self, api):
        """PRD §3.6: "Reinstatement returns the loan to `PERFORMING`, unfreezes
        and de-elevates every reserve, and restores each suspended extension
        option to `AVAILABLE` when its exercise window end is still at or beyond
        the current clock, lapsing it to `EXPIRED` when the window has already
        passed."
        PRD §3.6: "Coming back from special servicing is a `SpecialServicer` act
        guarded by four gates, evaluated in the pipeline order of §2.10"

        Design: Corner/state_machines/reinstate_restores_performing_and_unsuspends
        """
        ctx = setup_special_servicing_loan(
            tax_id="TX-REI",
            loan_overrides={"maturity_date": "2027-06-30T00:00:00Z"},
            option={"option_seq": 1,
                    "exercise_window_start": "2026-12-01T00:00:00Z",
                    "exercise_window_end": "2027-03-01T00:00:00Z"})
        assert ctx["loan"]["servicing_status"] == "SPECIAL_SERVICING"

        reinstated = get_success_data(api.reinstate_loan(ctx["loan"]["id"], SS))
        assert reinstated["servicing_status"] == "PERFORMING"
        reserve = get_reserve(ctx["reserve"]["id"])
        assert reserve["disbursement_frozen"] is False
        assert reserve["elevated_retainage"] is False
        assert _option_status(api, ctx["loan"]["id"],
                              ctx["option"]["id"]) == "AVAILABLE", (
            "window end 2027-03-01 is still beyond the 2026-08-01 clock")

    def test_reinstate_reserve_shortfall_rejected(self, api):
        """PRD §3.6: "every reserve account of the loan must be funded to target —
        `balance_cents` at least `target_balance_cents` — else
        `ERR_RESERVE_TARGET_SHORTFALL` (HTTP 422)."

        Design: Corner/validations/reinstate_reserve_shortfall_rejected
        """
        ctx = setup_special_servicing_loan(
            tax_id="TX-SHR", rating="CRITICAL", reserve_deposit_cents=100_000,
            reserve_target_cents=500_000)
        resp = api.reinstate_loan(ctx["loan"]["id"], SS)
        validate_error(resp, ApiErrorId.ERR_RESERVE_TARGET_SHORTFALL)
        assert get_loan(ctx["loan"]["id"])["servicing_status"] == "SPECIAL_SERVICING"

    def test_reinstate_with_active_entry_rejected(self, api):
        """PRD §3.6: "no `ACTIVE` watchlist entry may remain (else
        `ERR_ACTIVE_WATCHLIST_ENTRIES`)"

        Design: Corner/validations/reinstate_with_active_entry_rejected
        """
        borrower = create_borrower(legal_name="Two Ent Co", tax_id="TX-TWE",
                                   contact_email="twe@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-TWE",
                           original_principal_cents=100_000_000, note_rate=0.05)
        prop = create_property(loan["id"], address="1 Twe St")
        inspector = create_inspector(full_name="Twe Spect", license_no="LIC-TWE")
        insp1 = schedule_inspection(prop["id"], inspector["id"],
                                    scheduled_start="2026-08-01T09:00:00Z",
                                    scheduled_end="2026-08-01T10:00:00Z")
        insp2 = schedule_inspection(prop["id"], inspector["id"],
                                    scheduled_start="2026-08-01T10:00:00Z",
                                    scheduled_end="2026-08-01T11:00:00Z")
        complete_inspection(insp1["id"], inspector["id"], "POOR")
        complete_inspection(insp2["id"], inspector["id"], "POOR")
        entries = list_watchlist_entries(loan["id"],
                                         params={"status": "ACTIVE"})
        assert len(entries) == 2
        get_success_data(api.escalate_watchlist_entry(entries[0]["id"], MS))

        resp = api.reinstate_loan(loan["id"], SS)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_WATCHLIST_ENTRIES, )
        assert get_loan(loan["id"])["servicing_status"] == "SPECIAL_SERVICING", (
            "the second entry is still ACTIVE, so the loan stays in workout")


class TestResolutionGate:
    def test_reporting_delinquency_resolution_gated(self, api):
        """PRD §3.6: "an entry with criterion `REPORTING_DELINQUENCY`, however,
        can be resolved only once an `ACCEPTED` statement exists for the entry's
        period and statement type — an earlier attempt is refused with
        `ERR_RESOLUTION_BLOCKED`."
        PRD §3.7: "4. Reporting delinquency: for every expected statement — every
        calendar quarter of every loan whose `period_start` is on or after the
        loan's `origination_date` and whose computed `due_date` has passed — that
        has no `ACCEPTED` statement and no existing `ACTIVE` reporting-delinquency
        entry for that loan, quarter, and statement type, a
        `REPORTING_DELINQUENCY` entry is created."

        Design: Corner/validations/reporting_delinquency_resolution_gated
        """
        borrower = create_borrower(legal_name="Rep Co", tax_id="TX-REP",
                                   contact_email="rep@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-REP",
                           origination_date="2026-04-01T00:00:00Z")
        # Accept the Q2'26 rent roll up front so only the operating-statement
        # delinquency entry appears in the sweep (OS due 2026-08-14).
        submit_and_accept_statement(loan["id"], borrower["id"], "RENT_ROLL",
                                    *Q2_2026, occupancy_pct=91)
        set_clock("2026-08-16T00:00:00Z")
        entry = single_watchlist_entry(loan["id"],
                                       criterion="REPORTING_DELINQUENCY",
                                       status="ACTIVE")
        assert get_loan(loan["id"])["servicing_status"] == "WATCHLIST"

        blocked = api.resolve_watchlist_entry(entry["id"], MS)
        validate_error(blocked, ApiErrorId.ERR_RESOLUTION_BLOCKED)

        # TTM basis: one accepted quarter is not computable, so this acceptance
        # creates no assessment — only the delinquency gate is satisfied.
        submit_and_accept_statement(loan["id"], borrower["id"],
                                    "OPERATING_STATEMENT", *Q2_2026,
                                    net_operating_income_cents=20_000_000)
        resolved = get_success_data(api.resolve_watchlist_entry(entry["id"], MS))
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_at"] is not None
        assert get_loan(loan["id"])["servicing_status"] == "PERFORMING", (
            "resolving the last active item lets the posture fall back")


class TestClockSweep:
    def test_maturity_sweep_creates_risk_entry_then_maturity_default(self, api):
        """PRD §3.7: "5. Maturity risk: any loan whose maturity lies between zero
        and 180 days ahead of the clock inclusive, with `current_balance_cents`
        still positive, no `EXERCISED` extension option, and no `ACTIVE`
        maturity-risk entry, gains a `MATURITY_RISK` entry."
        PRD §3.7: "6. Maturity default: loans at or past `maturity_date` with
        `current_balance_cents` still positive and a payment status of `CURRENT`
        or `DELINQUENT` move to `MATURITY_DEFAULT`."
        PRD §3.7: "Entry creation throughout the sweep is idempotent per loan,
        criterion, and originating source: advancing the clock across the same
        conditions twice never duplicates an entry."

        Design: Corner/state_machines/maturity_sweep_creates_risk_entry_then_maturity_default
        """
        borrower = create_borrower(legal_name="Mat Co", tax_id="TX-MAT",
                                   contact_email="mat@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-MAT",
                           original_principal_cents=500_000_000, note_rate=0.05,
                           origination_date="2026-08-01T00:00:00Z",
                           maturity_date="2026-08-10T00:00:00Z")

        set_clock("2026-08-05T00:00:00Z")  # 5 days to maturity: inside the window
        entry = single_watchlist_entry(loan["id"], criterion="MATURITY_RISK",
                                       status="ACTIVE")
        assert entry["criterion"] == "MATURITY_RISK"

        set_clock("2026-08-15T00:00:00Z")  # at/past maturity with balance > 0
        assert get_loan(loan["id"])["payment_status"] == "MATURITY_DEFAULT"
        _rows, meta = validate_paginated(api.list_watchlist_entries(
            loan["id"], MS, params={"criterion": "MATURITY_RISK"}))
        assert meta["total_count"] == 1, "the second sweep creates no duplicate"

    def test_default_requires_sixty_days_delinquent(self, api):
        """PRD §3.6: "Declaring `DEFAULT` is gated: the loan must have been
        delinquent for at least sixty days, otherwise the transition is refused
        with `ERR_DELINQUENCY_THRESHOLD` (HTTP 422)."
        PRD §3.6: "`DEFAULT` and `MATURITY_DEFAULT` are terminal for this
        dimension, and a maturity default leaves the servicing dimension
        untouched."

        Design: Corner/validations/default_requires_sixty_days_delinquent
        """
        borrower = create_borrower(legal_name="Sixty Co", tax_id="TX-SIX",
                                   contact_email="six@x.com")
        loan = create_loan(borrower["id"], loan_number="LN-SIX",
                           original_principal_cents=100_000_000, note_rate=0.05,
                           origination_date="2026-08-01T00:00:00Z")
        set_payment_status(loan["id"], "DELINQUENT")  # at the 2026-08-01 clock

        set_clock("2026-09-29T00:00:00Z")  # 59 days delinquent
        early = api.set_payment_status(loan["id"], "DEFAULT", MS)
        validate_error(early, ApiErrorId.ERR_DELINQUENCY_THRESHOLD)
        assert get_loan(loan["id"])["payment_status"] == "DELINQUENT"

        set_clock("2026-09-30T00:00:00Z")  # exactly 60 days: inclusive boundary
        defaulted = set_payment_status(loan["id"], "DEFAULT")
        assert defaulted["payment_status"] == "DEFAULT"

        cure = api.set_payment_status(loan["id"], "CURRENT", MS)
        validate_error(cure, ApiErrorId.ERR_INVALID_STATE)
        assert get_loan(loan["id"])["payment_status"] == "DEFAULT", (
            "DEFAULT is terminal for the payment dimension")
