"""Filing obligations: calendar generation, per-line rounding, sweep transitions,
weekend roll-forward, filing payment fields, confirm SoD, and late-penalty tiers."""
from test_helpers import (
    PCL,
    ApiErrorId,
    get_employer,
    get_notices,
    get_obligations,
    get_success_data,
    make_payroll_compliance_lead_headers,
    set_clock,
    setup_monthly_or_with_late_deposit,
    setup_withholding_registration_active,
    validate_error,
    validate_success,
)


def _quarterly_or(wage=3_000_000, account_number="OR-00000020", projected=200_000):
    return setup_withholding_registration_active(
        projected=projected, account_number=account_number, employee_wages=(wage,),
    )


class TestQuarterlyDepositAmounts:
    def test_quarterly_frequency_generates_single_deposit_row(self, api):
        """PRD §3.4: "A `QUARTERLY` registration gets one deposit row for the quarter,
        due the last day of the month after the quarter ends."
        PRD §3.4: "Calendar generation produces FilingObligation rows for the full
        calendar quarter containing activation, even if the quarter is partially
        elapsed."

        Design: Difficulty/combinatorial_formula/withholding_deposit_per_line_rounding_order
        """
        out = setup_withholding_registration_active(
            projected=200_000, account_number="OR-00000002",
            employee_wages=(3_000_000, 3_000_000),
        )
        deposits = get_obligations(
            out["registration"]["id"], obligation_kind="WITHHOLDING_DEPOSIT",
        )
        assert len(deposits) == 1, (
            f"QUARTERLY frequency must produce one Q3 deposit row, got {len(deposits)}"
        )
        assert deposits[0]["period_start"] == "2026-07-01T00:00:00Z"
        assert deposits[0]["period_end"] == "2026-09-30T00:00:00Z"

    def test_withholding_deposit_per_line_rounding_order(self, api):
        """PRD §2.6: "Where a computation produces per-employee lines, each line is
        rounded half up to cents first and the rounded lines are then summed; summing
        unrounded lines and rounding once at the end produces different cents and is
        non-conformant."
        PRD §3.8: "the line is `annual_wage_cents` multiplied by the employee's
        attributed days in the period, divided by 365, multiplied by the agency's
        `withholding_rate_bp`, divided by ten thousand — each line rounded half up to
        cents, and `amount_due_cents` the sum of the rounded lines."

        Design: Difficulty/combinatorial_formula/withholding_deposit_per_line_rounding_order
        """
        out = setup_withholding_registration_active(
            projected=200_000, account_number="OR-00000002",
            employee_wages=(3_000_000, 3_000_000),
        )
        deposits = get_obligations(
            out["registration"]["id"], obligation_kind="WITHHOLDING_DEPOSIT",
        )
        assert len(deposits) == 1
        # Per line: round_half_up(3,000,000 * 61 / 365 * 500 / 10,000) = 25,068;
        # 2 x 25,068 = 50,136 (sum-then-round would give 50,137).
        assert deposits[0]["amount_due_cents"] == 50_136

    def test_withholding_deposit_quarterly_literal(self, api):
        """PRD §3.8: "A withholding deposit or return for a state charges each employee
        with at least one attributed day in that state during the period: the line is
        `annual_wage_cents` multiplied by the employee's attributed days in the period,
        divided by 365, multiplied by the agency's `withholding_rate_bp`, divided by
        ten thousand — each line rounded half up to cents, and `amount_due_cents` the
        sum of the rounded lines."

        Design: Corner/calculations/withholding_deposit_quarterly_literal
        """
        out = _quarterly_or(wage=9_125_000, account_number="OR-00000009")
        deposits = get_obligations(
            out["registration"]["id"], obligation_kind="WITHHOLDING_DEPOSIT",
        )
        assert len(deposits) == 1
        deposit = deposits[0]
        assert deposit["period_start"] == "2026-07-01T00:00:00Z"
        assert deposit["period_end"] == "2026-09-30T00:00:00Z"
        # round_half_up(9,125,000 * 61 / 365 * 0.05) = 76,250 exactly; the July
        # portion contributes 0 days (hired 2026-08-01).
        assert deposit["amount_due_cents"] == 76_250

    def test_quarterly_due_date_weekend_rollforward(self, api):
        """PRD §3.4: "Every withholding registration additionally gets one
        `WITHHOLDING_RETURN` per quarter, due the last day of the month after the
        quarter"
        PRD §3.4: "A due date landing on a Saturday rolls forward two days to Monday;
        one landing on a Sunday rolls forward one day to Monday; no holiday calendar is
        observed."

        Design: Corner/calculations/quarterly_due_date_weekend_rollforward
        """
        out = _quarterly_or(wage=3_000_000, account_number="OR-00000010")
        returns = get_obligations(
            out["registration"]["id"], obligation_kind="WITHHOLDING_RETURN",
        )
        assert len(returns) == 1
        # 2026-10-31 (last day of the month after Q3) is a Saturday -> +2 days.
        assert returns[0]["due_date"] == "2026-11-02T00:00:00Z"


class TestObligationSweepSequence:
    def test_obligation_scheduled_at_activation(self, api):
        """PRD §3.8: "Every obligation starts `SCHEDULED`."
        PRD §3.4: "A `QUARTERLY` registration gets one deposit row for the quarter, due
        the last day of the month after the quarter ends."

        Design: Corner/state_machines/obligation_scheduled_due_late_sweep_sequence
        """
        out = _quarterly_or(wage=3_000_000, account_number="OR-00000008")
        deposits = get_obligations(
            out["registration"]["id"], obligation_kind="WITHHOLDING_DEPOSIT",
        )
        assert len(deposits) == 1
        assert deposits[0]["status"] == "SCHEDULED"
        assert deposits[0]["due_date"] == "2026-11-02T00:00:00Z"
        assert deposits[0]["late_days"] == 0

    def test_obligation_due_then_late_on_sweeps(self, api, payroll_compliance_lead_headers):
        """PRD §3.8: "Once `period_end` has passed, `SCHEDULED` becomes `DUE`. Once the
        current date reaches the day after `due_date` while the obligation is still
        `DUE`, it becomes `LATE`, and `late_days` — calendar days counted from the day
        after `due_date` to the filing timestamp, or to the clock while unfiled, and
        zero when filed on or before the due date — recompute daily."

        Design: Corner/state_machines/obligation_scheduled_due_late_sweep_sequence
        """
        out = _quarterly_or(wage=3_000_000, account_number="OR-00000008")
        deposit = get_obligations(
            out["registration"]["id"], obligation_kind="WITHHOLDING_DEPOSIT",
        )[0]
        set_clock("2026-10-01T00:00:00Z")
        due = get_success_data(
            api.get_filing_obligation(deposit["id"], payroll_compliance_lead_headers)
        )
        assert due["status"] == "DUE", "period_end 2026-09-30 passed at 2026-10-01"
        assert due["late_days"] == 0
        set_clock("2026-11-03T00:00:00Z")
        late = get_success_data(
            api.get_filing_obligation(deposit["id"], payroll_compliance_lead_headers)
        )
        assert late["status"] == "LATE", (
            "2026-11-03 is the first date >= due_date 2026-11-02 + 1 day"
        )
        assert late["late_days"] == 1


class TestFileAndConfirm:
    def test_file_action_sets_payment_fields(self, api, payroll_compliance_lead_headers):
        """PRD §3.8: "Filing sets `amount_paid_cents` equal to `amount_due_cents`,
        records `filed_by_user_id` from the caller, finalizes `late_days`, and — from
        `LATE` — triggers the final penalty recompute and Employer counter refresh
        described above; the obligation lands `FILED`."

        Design: Corner/endpoints/file_action_sets_payment_fields
        """
        out = _quarterly_or(wage=3_000_000, account_number="OR-00000020")
        set_clock("2026-10-01T00:00:00Z")
        deposit = get_obligations(
            out["registration"]["id"], obligation_kind="WITHHOLDING_DEPOSIT",
        )[0]
        res = api.file_obligation(
            deposit["id"], {"filed_at": "2026-10-01T00:00:00Z"},
            make_payroll_compliance_lead_headers("pcl-1"),
        )
        filed = validate_success(res, 200)
        assert filed["status"] == "FILED"
        assert filed["amount_due_cents"] == 25_068
        assert filed["amount_paid_cents"] == 25_068
        assert filed["late_days"] == 0, "filed on/before the 2026-11-02 due date"
        assert filed["filed_by_user_id"] == "pcl-1"
        notices = get_notices(filing_obligation_id=deposit["id"])
        assert notices == [], "an on-time filing never creates a notice"

    def test_filing_confirm_same_user_sod_rejected(self, api):
        """PRD §3.8: "Confirmation, again a `PayrollComplianceLead`, moves `FILED` to
        terminal `CONFIRMED` and requires a confirmer whose `X-User-ID` differs from
        `filed_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`), recording
        `confirmed_by_user_id`."

        Design: Corner/validations/filing_confirm_same_user_sod_rejected
        """
        out = _quarterly_or(wage=9_125_000, account_number="OR-00000012")
        set_clock("2026-10-01T00:00:00Z")
        deposit = get_obligations(
            out["registration"]["id"], obligation_kind="WITHHOLDING_DEPOSIT",
        )[0]
        filer = make_payroll_compliance_lead_headers("pcl-1")
        get_success_data(
            api.file_obligation(deposit["id"], {"filed_at": "2026-10-01T00:00:00Z"}, filer)
        )
        res = api.confirm_obligation(deposit["id"], filer)
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        confirmed = validate_success(
            api.confirm_obligation(
                deposit["id"], make_payroll_compliance_lead_headers("pcl-2")
            ),
            200,
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["confirmed_by_user_id"] == "pcl-2"


class TestLatePenaltyTiers:
    def _setup_late_quarterly_deposit(self):
        """Q3 deposit (76,250 cents, due 2026-11-02) driven LATE at 2026-11-03 with
        the provisional notice posted."""
        out = _quarterly_or(wage=9_125_000, account_number="OR-00000011")
        set_clock("2026-11-03T00:00:00Z")
        deposit = get_obligations(
            out["registration"]["id"], obligation_kind="WITHHOLDING_DEPOSIT",
        )[0]
        notices = get_notices(filing_obligation_id=deposit["id"])
        assert len(notices) == 1, "the LATE cascade posts exactly one linked notice"
        out.update(deposit=deposit, notice=notices[0])
        return out

    def test_late_penalty_provisional_min_floor(self, api):
        """PRD §3.8: "The assessed penalty is the greater of 2,500 cents (twenty-five
        dollars) and the tiered percentage of the amount due, rounded half up."
        PRD §3.8: "the late cascade posts the penalty computed at one late day"

        Design: Corner/calculations/late_penalty_provisional_then_final_tier
        """
        out = self._setup_late_quarterly_deposit()
        assert out["notice"]["notice_type"] == "PENALTY_ASSESSMENT"
        # 2% of 76,250 = 1,525 -> raised to the 2,500-cent minimum.
        assert out["notice"]["penalty_amount_cents"] == 2_500

    def test_late_penalty_final_tier_recomputed_on_file(self, api):
        """PRD §3.8: "The penalty itself is tiered on `late_days`: one through five
        late days cost two percent of `amount_due_cents`; six through fifteen cost five
        percent; more than fifteen cost ten percent."
        PRD §3.8: "filing from `LATE` recomputes the penalty at the final `late_days`
        tier — which can be higher — and updates that same notice's
        `penalty_amount_cents` in place."

        Design: Corner/calculations/late_penalty_provisional_then_final_tier
        """
        out = self._setup_late_quarterly_deposit()
        deposit, notice = out["deposit"], out["notice"]
        set_clock("2026-11-18T00:00:00Z")
        res = api.file_obligation(
            deposit["id"], {"filed_at": "2026-11-18T00:00:00Z"},
            make_payroll_compliance_lead_headers("pcl-1"),
        )
        filed = validate_success(res, 200)
        assert filed["status"] == "FILED"
        assert filed["late_days"] == 16, "2026-11-03 .. 2026-11-18"
        assert filed["amount_paid_cents"] == 76_250
        after = get_success_data(api.get_agency_notice(notice["id"], PCL))
        # >15 days -> 10% tier: round_half_up(76,250 * 0.10) = 7,625 (> 2,500 floor).
        assert after["penalty_amount_cents"] == 7_625


class TestLateCascadePosture:
    def test_late_cascade_creates_single_notice_provisional_penalty(self, api):
        """PRD §3.8: "On the transition to `LATE`, when `amount_due_cents` is greater
        than zero, the system creates an AgencyNotice of type `PENALTY_ASSESSMENT`
        linked to the obligation and its registration, with `received_date` set to the
        current date, `response_due_date` set thirty days out, and
        `penalty_amount_cents` set to the provisional penalty at one late day — the
        two-percent tier subject to the floor"
        PRD §3.8: "A zero-amount obligation goes late without penalty and without a
        notice."

        Design: Difficulty/transitive_cascade/late_obligation_notice_posture_cascade
        """
        out = setup_monthly_or_with_late_deposit(account_number="OR-00000004")
        notices = get_notices(registration_id=out["registration"]["id"])
        assert len(notices) == 1, (
            "the zero-amount July deposit went LATE without a notice; only the "
            "38,750-cent August deposit produced one"
        )
        notice = notices[0]
        assert notice["notice_type"] == "PENALTY_ASSESSMENT"
        # max(2,500, round_half_up(38,750 * 0.02) = 775) = 2,500.
        assert notice["penalty_amount_cents"] == 2_500
        assert notice["filing_obligation_id"] == out["late_obligation"]["id"]

    def test_late_cascade_employer_counters_and_posture(self, api):
        """PRD §3.8: "and the Employer's `open_notice_count`,
        `outstanding_penalty_cents`, and `compliance_posture` recompute."
        PRD §2.7: "`open_notice_count` counts AgencyNotices whose status is `RECEIVED`,
        `TRIAGED`, `RESPONSE_IN_PROGRESS`, or `ESCALATED` — these four statuses are the
        "open" notices throughout this document. `outstanding_penalty_cents` sums, over
        those open notices, each notice's `penalty_amount_cents` minus its
        `abated_amount_cents`."
        PRD §2.7: "Otherwise it is `WATCH` when any open notice exists, or any
        FilingObligation is `LATE`, or any NexusCase is `THRESHOLD_MET`."

        Design: Difficulty/transitive_cascade/late_obligation_notice_posture_cascade
        """
        out = setup_monthly_or_with_late_deposit(account_number="OR-00000004")
        employer = get_employer(out["employer"]["id"])
        assert employer["open_notice_count"] == 1
        assert employer["outstanding_penalty_cents"] == 2_500
        assert employer["compliance_posture"] == "WATCH", (
            "one open notice and one LATE obligation (late_days 1 <= 30) force WATCH, "
            "not DELINQUENT"
        )
