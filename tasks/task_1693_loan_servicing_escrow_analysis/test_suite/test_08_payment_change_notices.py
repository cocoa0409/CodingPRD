"""Payment change notices: effective-date gate, shortage options, idempotency."""
from test_helpers import (
    EA1,
    ApiErrorId,
    acknowledge_notice,
    get_account,
    get_success_data,
    make_borrower_headers,
    post_deposit,
    send_notice,
    set_clock,
    setup_effective_analysis,
    validate_error,
    validate_success,
)

# Surplus-scenario expense picture: annual 120000, cushion 20000, base 10000.
SURPLUS_LINE_ITEMS = [
    {"expense_type": "PROPERTY_TAX", "expected_annual_amount_cents": 60_000,
     "installments_per_year": 1, "first_due_date": "2027-08-10"},
    {"expense_type": "HAZARD_INSURANCE", "expected_annual_amount_cents": 60_000,
     "installments_per_year": 1, "first_due_date": "2027-07-10"},
]


class TestEffectiveDateGate:
    def test_apply_before_effective_date_rejected_then_applies(self, api):
        """PRD: "it derives the notice's `effective_date` as the first day of
        the second month after the finalize month — finalizing in September
        2026 yields 2026-11-01 — and its `send_by_date` as 30 days before the
        effective date."
        PRD: "The current date must be on or after the notice's
        `effective_date`, else `ERR_EFFECTIVE_DATE_NOT_REACHED`"
        PRD: "Applying from `SENT` when shortage plus deficiency is positive
        and the borrower never chose an option treats the choice as a
        `SPREAD_12` default."
        PRD: "A successful apply moves the notice to the terminal `APPLIED` and
        replaces the account's `monthly_escrow_cents` with the notice's
        `new_monthly_escrow_cents`, incrementing both versions."

        Design: Corner/validations/apply_before_effective_date_rejected
        """
        # Finalized at the default clock (2026-08): effective 2026-10-01.
        ctx = setup_effective_analysis(loan_number="LN-VAL-6")
        notice = send_notice(ctx["notice"]["id"])
        assert notice["effective_date"] == "2026-10-01"
        assert notice["send_by_date"] == "2026-09-01"
        assert notice["timeliness"] == "ON_TIME", (
            "sent 2026-08-01, on or before send_by 2026-09-01")

        set_clock("2026-09-30T00:00:00Z")
        resp = api.apply_notice(notice["id"], EA1)
        validate_error(resp, ApiErrorId.ERR_EFFECTIVE_DATE_NOT_REACHED)

        set_clock("2026-10-01T00:00:00Z")
        applied = validate_success(api.apply_notice(notice["id"], EA1), 200)
        assert applied["status"] == "APPLIED"
        account = get_account(ctx["account"]["id"])
        assert account["monthly_escrow_cents"] == 35_000, (
            "SENT apply with no chosen option treats the choice as SPREAD_12: "
            "base 30000 + spread 5000")


class TestShortageOptionGate:
    def test_option_required_when_shortage_positive(self, api):
        """PRD: "The `shortage_option` field is required when the analysis's
        shortage plus deficiency is positive — omitting it is
        `ERR_SHORTAGE_OPTION_REQUIRED` (HTTP 422)"

        Design: Corner/validations/shortage_option_required_vs_not_applicable
        """
        # Standard scenario: shortage 60000, deficiency 0.
        ctx = setup_effective_analysis(loan_number="LN-VAL-7A")
        notice = send_notice(ctx["notice"]["id"])

        resp = api.acknowledge_notice(notice["id"], {},
                                      make_borrower_headers(ctx["loan"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SHORTAGE_OPTION_REQUIRED)

    def test_option_forbidden_when_no_shortage_or_deficiency(self, api):
        """PRD: "and forbidden when that sum is zero, where supplying it is
        `ERR_SHORTAGE_OPTION_NOT_APPLICABLE` (HTTP 422)."
        PRD: "`SURPLUS` when `surplus_cents` is positive with shortage and
        deficiency both zero"

        Design: Corner/validations/shortage_option_required_vs_not_applicable
        """
        # Surplus scenario: deposit 25000 against a 20000 cushion target.
        ctx = setup_effective_analysis(loan_number="LN-VAL-7B",
                                       line_items=SURPLUS_LINE_ITEMS,
                                       deposits=[(25_000, "2026-08-10")])
        notice = send_notice(ctx["notice"]["id"])
        assert notice["notice_type"] == "SURPLUS"

        resp = api.acknowledge_notice(notice["id"], {"shortage_option": "SPREAD_12"},
                                      make_borrower_headers(ctx["loan"]["id"]))
        validate_error(resp, ApiErrorId.ERR_SHORTAGE_OPTION_NOT_APPLICABLE)


class TestDeficiencySpreadMandatory:
    def test_deficiency_equal_to_one_month_forbids_lump_sum(self, api):
        """PRD: "`LUMP_SUM` is rejected with `ERR_DEFICIENCY_SPREAD_MANDATORY`
        (HTTP 422) when the analysis's `deficiency_cents` is at least one full
        month of escrow — measured against `old_monthly_escrow_cents`, the
        payment pinned at finalize time — because a deficiency that large must
        be spread over at least 12 months."
        PRD: "`DEFICIENCY` whenever `deficiency_cents` is positive"

        Design: Corner/validations/deficiency_equal_one_month_requires_spread
        """
        # Deposit 30000 -> projection trough -30000 -> deficiency 30000, which
        # equals the 30000 monthly escrow pinned at finalize.
        ctx = setup_effective_analysis(loan_number="LN-VAL-9A",
                                       deposits=[(30_000, "2026-08-10")])
        analysis = get_success_data(api.get_analysis(ctx["analysis"]["id"], EA1))
        assert analysis["deficiency_cents"] == 30_000
        assert analysis["shortage_cents"] == 60_000
        notice = send_notice(ctx["notice"]["id"])
        assert notice["notice_type"] == "DEFICIENCY"

        resp = api.acknowledge_notice(notice["id"], {"shortage_option": "LUMP_SUM"},
                                      make_borrower_headers(ctx["loan"]["id"]))
        validate_error(resp, ApiErrorId.ERR_DEFICIENCY_SPREAD_MANDATORY)

        acknowledged = acknowledge_notice(notice["id"], ctx["loan"]["id"],
                                          shortage_option="SPREAD_12")
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged["new_monthly_escrow_cents"] == 37_500, (
            "base 30000 + spread floor(90000 / 12) = 7500")

    def test_deficiency_one_cent_below_one_month_allows_lump_sum(self, api):
        """PRD: "`LUMP_SUM` is rejected with `ERR_DEFICIENCY_SPREAD_MANDATORY`
        (HTTP 422) when the analysis's `deficiency_cents` is at least one full
        month of escrow — measured against `old_monthly_escrow_cents`, the
        payment pinned at finalize time"
        PRD: "Choosing `LUMP_SUM` recomputes the notice's
        `new_monthly_escrow_cents` down to `base_monthly_escrow_cents` alone,
        dropping the spread"

        Design: Corner/validations/deficiency_equal_one_month_requires_spread
        """
        # Deposit 30001 -> deficiency 29999 < 30000: LUMP_SUM is allowed.
        ctx = setup_effective_analysis(loan_number="LN-VAL-9B",
                                       deposits=[(30_001, "2026-08-10")])
        analysis = get_success_data(api.get_analysis(ctx["analysis"]["id"], EA1))
        assert analysis["deficiency_cents"] == 29_999
        notice = send_notice(ctx["notice"]["id"])

        acknowledged = acknowledge_notice(notice["id"], ctx["loan"]["id"],
                                          shortage_option="LUMP_SUM")
        assert acknowledged["status"] == "ACKNOWLEDGED"
        assert acknowledged["new_monthly_escrow_cents"] == 30_000, (
            "LUMP_SUM drops the spread, leaving the base payment alone")


class TestLumpSumDepositGate:
    def test_lump_sum_apply_requires_covering_deposit_since_sent(self, api):
        """PRD: "Applying from `ACKNOWLEDGED` under `LUMP_SUM` demands proof of
        the borrower's lump payment: the sum of `DEPOSIT` ledger entries with
        `effective_date` on or after the notice's sent date and on or before
        today must be at least the shortage plus deficiency, else
        `ERR_SHORTAGE_LUMP_SUM_MISSING` (HTTP 422)."
        PRD: "Choosing `LUMP_SUM` recomputes the notice's
        `new_monthly_escrow_cents` down to `base_monthly_escrow_cents` alone,
        dropping the spread"

        Design: Corner/validations/lump_sum_missing_then_satisfied
        """
        # The funding deposit is effective 2026-07-10, BEFORE the notice's sent
        # date, so it does not count toward the lump-sum proof. The analysis
        # still computes shortage 60000 (deficiency 0) off the posted 60000.
        ctx = setup_effective_analysis(loan_number="LN-VAL-8",
                                       deposits=[(60_000, "2026-07-10")])
        notice = send_notice(ctx["notice"]["id"])  # sent at 2026-08-01
        acknowledged = acknowledge_notice(notice["id"], ctx["loan"]["id"],
                                          shortage_option="LUMP_SUM")
        assert acknowledged["new_monthly_escrow_cents"] == 30_000, (
            "LUMP_SUM drops the 5000 spread, leaving base 30000")

        set_clock("2026-10-01T00:00:00Z")
        resp = api.apply_notice(notice["id"], EA1)
        validate_error(resp, ApiErrorId.ERR_SHORTAGE_LUMP_SUM_MISSING)

        # A 60000 deposit effective inside [sent date, today] satisfies the gate.
        post_deposit(ctx["account"]["id"], 60_000, "2026-09-15")
        applied = validate_success(api.apply_notice(notice["id"], EA1), 200)
        assert applied["status"] == "APPLIED"
        assert applied["new_monthly_escrow_cents"] == 30_000
        account = get_account(ctx["account"]["id"])
        assert account["monthly_escrow_cents"] == 30_000


class TestNoticeAcknowledgeIdempotency:
    def test_second_acknowledge_rejected_first_write_kept(self, api):
        """PRD: "Acknowledgment moves `SENT` → `ACKNOWLEDGED`."
        PRD: "then from-state validity for the attempted transition
        (`ERR_INVALID_STATE_TRANSITION`, HTTP 409)"

        Design: Corner/state_machines/notice_double_acknowledge_rejected
        """
        ctx = setup_effective_analysis(loan_number="LN-SM-4")
        notice = send_notice(ctx["notice"]["id"])
        acknowledged = acknowledge_notice(notice["id"], ctx["loan"]["id"],
                                          shortage_option="SPREAD_12")
        assert acknowledged["status"] == "ACKNOWLEDGED"

        resp = api.acknowledge_notice(notice["id"], {"shortage_option": "LUMP_SUM"},
                                      make_borrower_headers(ctx["loan"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api.get_notice(notice["id"], EA1), 200)
        assert after["status"] == "ACKNOWLEDGED"
        assert after["shortage_option"] == "SPREAD_12", "the first write is kept"
