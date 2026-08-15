"""Fee ledger: provisional accrual, tiered reconciliation at billing, the
pinned statement evaluation order, waivers, and billing-run gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_enrollment,
    create_enrollment,
    decide,
    fee_statement,
    find_fee_entry,
    monthly_billing,
    present_item,
    set_clock,
    setup_open_exception,
    setup_reverse_tier_exceptions,
    validate_error,
    validate_success,
)

BANK_MGR = TEST_USERS["bank_treasury_manager_headers"]
BANK_OPS = TEST_USERS["bank_ops_headers"]


class TestProvisionalVsTieredFees:
    def _setup_and_bill(self):
        b = setup_reverse_tier_exceptions(11, default_decision="RETURN",
                                          business_name="FeeCo",
                                          account_number="900001",
                                          clock="2026-08-05T09:00:00Z")
        pre = fee_statement(b["enrollment"]["id"], "2026-08")
        set_clock("2026-09-01T00:00:00Z")
        run = monthly_billing(b["enrollment"]["id"], "2026-08")
        return b, pre, run

    def test_provisional_flat_rate_and_billing_run_receipt(self, api):
        """PRD §3.7: "every exception creation — for any reason, including
        `REVERSE_REVIEW` — accrues one `EXCEPTION_FEE` entry of 200 cents in
        `ACCRUED` status".
        PRD §3.7: "The re-rated price is 200 cents each for the first ten
        exceptions, 150 cents each for the eleventh through fortieth ... when
        the difference is non-zero a single `ADJUSTMENT` entry is created in
        `BILLED` status with `amount_cents` equal to the re-rated total minus
        the provisional total".
        PRD §3.7: "The net due is the greater of the 5000-cent monthly minimum
        and that pre-minimum figure; if the minimum exceeds the pre-minimum, a
        `MINIMUM_TOPUP` entry is created in `BILLED` status for the difference."

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_tier_reconciliation
        """
        _, pre, run = self._setup_and_bill()
        assert pre["exception_fees_cents"] == 2200, "11 x 200 provisional"
        assert pre["adjustment_cents"] == 0
        assert run["adjustment_cents"] == -50, "tiered 2150 vs provisional 2200"
        assert run["fees_billed"] == 11
        assert run["minimum_topup_cents"] == 2850

    def test_post_billing_statement_reflects_adjustment_and_topup(self, api):
        """PRD §3.7: "On that read, `net_due_cents` is the sum of the period's
        entries in `BILLED` status — which includes any `ADJUSTMENT` and
        `MINIMUM_TOPUP` — while waived amounts are excluded from the net and
        surfaced separately as `waived_cents`."

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_tier_reconciliation
        """
        b, _, _ = self._setup_and_bill()
        stmt = fee_statement(b["enrollment"]["id"], "2026-08")
        assert stmt["exception_fees_cents"] == 2200
        assert stmt["adjustment_cents"] == -50
        assert stmt["minimum_topup_cents"] == 2850
        assert stmt["net_due_cents"] == 5000
        assert stmt["entry_count"] == 13, (
            "11 exception fees + 1 adjustment + 1 minimum top-up")


class TestStatementPinnedOrder:
    def _setup_and_bill(self, api):
        b = setup_reverse_tier_exceptions(12, default_decision="PAY",
                                          business_name="OrderCo",
                                          account_number="940001",
                                          clock="2026-08-05T09:00:00Z",
                                          user_roles=("ADMIN",
                                                      "DECISION_MAKER"))
        decide(b["exception_ids"][0], "RETURN",
               b["headers"]["DECISION_MAKER"])
        rfee = find_fee_entry(exception_id=b["exception_ids"][0],
                              fee_type="RETURN_FEE")
        waived = validate_success(api.waive_fee_entry(rfee["id"], "goodwill",
                                                      BANK_OPS))
        assert waived["status"] == "WAIVED"
        set_clock("2026-09-01T00:00:00Z")
        run = monthly_billing(b["enrollment"]["id"], "2026-08")
        return b, run

    def test_billing_run_adjustment_and_topup_amounts(self, api):
        """PRD §3.7: "The pre-minimum total is the provisional exception fees
        plus the adjustment, plus the return fees net of waived return fees,
        minus the waived exception fees."
        Here: 2400 - 100 + 500 - 500 = 2300, so the top-up is 5000 - 2300 =
        2700.

        Design: Difficulty/combinatorial_formula/monthly_statement_pinned_evaluation_order
        """
        _, run = self._setup_and_bill(api)
        assert run["adjustment_cents"] == -100, "tiered 2300 vs provisional 2400"
        assert run["minimum_topup_cents"] == 2700

    def test_statement_components_follow_pinned_order(self, api):
        """PRD §3.7: "Applying the minimum before subtracting waivers is a
        forbidden alternate reading: waivers reduce the pre-minimum figure, and
        only then is the floor applied."
        The alternate order would yield net 4500 here; the pinned order yields
        5000.

        Design: Difficulty/combinatorial_formula/monthly_statement_pinned_evaluation_order
        """
        b, _ = self._setup_and_bill(api)
        stmt = fee_statement(b["enrollment"]["id"], "2026-08")
        assert stmt["exception_fees_cents"] == 2400
        assert stmt["return_fees_cents"] == 500
        assert stmt["adjustment_cents"] == -100
        assert stmt["waived_cents"] == 500
        assert stmt["minimum_topup_cents"] == 2700
        assert stmt["net_due_cents"] == 5000


class TestTierBoundary:
    def test_ten_exceptions_reconcile_to_zero_adjustment(self, api):
        """PRD §3.7: "The re-rated price is 200 cents each for the first ten
        exceptions" — exactly ten exceptions re-rate to the same 2000 cents
        they accrued, so no adjustment entry is created, and the top-up is
        5000 - 2000 = 3000.

        Design: Difficulty/boundary_precision_check/exception_fee_tier_eleventh_item_boundary
        """
        b = setup_reverse_tier_exceptions(10, default_decision="RETURN",
                                          business_name="TierCo",
                                          account_number="990003",
                                          clock="2026-08-05T09:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        run = monthly_billing(b["enrollment"]["id"], "2026-08")
        assert run["adjustment_cents"] == 0
        assert run["minimum_topup_cents"] == 3000

    def test_eleventh_exception_rerates_to_150(self, api):
        """PRD §3.7: "150 cents each for the eleventh through fortieth" — the
        eleventh exception re-rates 200 -> 150, so adjustment is -50 and the
        top-up is 5000 - 2150 = 2850.

        Design: Difficulty/boundary_precision_check/exception_fee_tier_eleventh_item_boundary
        """
        b = setup_reverse_tier_exceptions(10, default_decision="RETURN",
                                          business_name="TierCo2",
                                          account_number="990013",
                                          clock="2026-08-05T09:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        monthly_billing(b["enrollment"]["id"], "2026-08")
        set_clock("2026-09-05T09:00:00Z")
        for i in range(11):
            item = present_item(b["account"]["id"], str(21 + i), 100,
                                f"Q{i + 1}")
            assert item["status"] == "EXCEPTION_HELD"
        set_clock("2026-10-01T00:00:00Z")
        run = monthly_billing(b["enrollment"]["id"], "2026-09")
        assert run["adjustment_cents"] == -50
        assert run["minimum_topup_cents"] == 2850


class TestWaiveReinstateInvariant:
    def _setup_billed_with_return_fee(self):
        b = setup_reverse_tier_exceptions(2, default_decision="PAY",
                                          business_name="GrossCo",
                                          account_number="990008",
                                          clock="2026-08-05T09:00:00Z",
                                          user_roles=("ADMIN",
                                                      "DECISION_MAKER"))
        decide(b["exception_ids"][0], "RETURN",
               b["headers"]["DECISION_MAKER"])
        rfee = find_fee_entry(exception_id=b["exception_ids"][0],
                              fee_type="RETURN_FEE")
        set_clock("2026-09-01T00:00:00Z")
        run = monthly_billing(b["enrollment"]["id"], "2026-08")
        return b, rfee, run

    def test_billing_baseline_with_topup(self, api):
        """PRD §3.7: "The net due is the greater of the 5000-cent monthly
        minimum and that pre-minimum figure" — two exception fees (400) plus
        one return fee (500) give pre-minimum 900, so the top-up is 4100 and
        the net due is 5000.

        Design: Difficulty/compensating_invariant/waive_reinstate_pair_preserves_period_gross_fees
        """
        b, _, run = self._setup_billed_with_return_fee()
        assert run["minimum_topup_cents"] == 4100
        stmt = fee_statement(b["enrollment"]["id"], "2026-08")
        assert stmt["exception_fees_cents"] == 400
        assert stmt["return_fees_cents"] == 500
        assert stmt["waived_cents"] == 0
        assert stmt["net_due_cents"] == 5000

    def test_waive_then_reinstate_conserves_period_gross_and_net(self, api):
        """PRD §3.7: "A successful waiver moves the entry to `WAIVED` and
        records `waived_from_status` (the `ACCRUED` or `BILLED` status it came
        from), `waived_by`, and `waiver_reason` from the submitted reason.
        Reinstatement is manager-only: a `WAIVED` entry returns to whatever
        status `waived_from_status` recorded — `ACCRUED` or `BILLED` — and the
        three waiver fields are cleared to null".

        Design: Difficulty/compensating_invariant/waive_reinstate_pair_preserves_period_gross_fees
        """
        b, rfee, _ = self._setup_billed_with_return_fee()
        waived = validate_success(api.waive_fee_entry(rfee["id"], "goodwill",
                                                      BANK_OPS))
        assert waived["status"] == "WAIVED"
        assert waived["waived_from_status"] == "BILLED"
        mid = fee_statement(b["enrollment"]["id"], "2026-08")
        assert mid["waived_cents"] == 500
        assert mid["net_due_cents"] == 4500
        assert mid["exception_fees_cents"] == 400
        assert mid["return_fees_cents"] == 500, "waiver mutates status, not amount"
        reinstated = validate_success(api.reinstate_fee_entry(rfee["id"],
                                                              BANK_MGR))
        assert reinstated["status"] == "BILLED"
        final = fee_statement(b["enrollment"]["id"], "2026-08")
        assert final["exception_fees_cents"] == 400
        assert final["return_fees_cents"] == 500
        assert final["waived_cents"] == 0
        assert final["net_due_cents"] == 5000, (
            "the waive+reinstate pair leaves period gross and net conserved")


class TestWaiverRules:
    def test_double_waive_rejected(self, api):
        """PRD §3.7: "waiving an `ADJUSTMENT` entry or an already-`WAIVED` entry
        is rejected with `ERR_FEE_ENTRY_NOT_WAIVABLE`".

        Design: Corner/state_machines/fee_double_waive_rejected
        """
        b = setup_open_exception(tier="REVERSE_POSITIVE_PAY",
                                 default_decision="PAY", business_name="WavCo",
                                 account_number="810010", user_roles=("ADMIN",))
        fee = find_fee_entry(exception_id=b["exception_id"],
                             fee_type="EXCEPTION_FEE")
        waived = validate_success(api.waive_fee_entry(fee["id"], "first",
                                                      BANK_OPS))
        assert waived["status"] == "WAIVED"
        resp = api.waive_fee_entry(fee["id"], "second", BANK_OPS)
        validate_error(resp, ApiErrorId.ERR_FEE_ENTRY_NOT_WAIVABLE)

    def test_waiver_authority_cap_boundary(self, api):
        """PRD §3.7: "a `BankOps` operator may waive amounts of at most 1000
        cents, while anything larger requires a `BankTreasuryManager`, and an
        over-authority attempt is rejected with `ERR_WAIVER_EXCEEDS_AUTHORITY`
        (HTTP 422); the manager's waiver authority is uncapped."

        Design: Corner/rbac/waiver_authority_cap_boundary
        """
        b = setup_reverse_tier_exceptions(2, default_decision="RETURN",
                                          business_name="CapWCo",
                                          account_number="850004",
                                          clock="2026-08-05T09:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        run = monthly_billing(b["enrollment"]["id"], "2026-08")
        assert run["minimum_topup_cents"] == 4600, "5000 minimum - 400 fees"
        topup = find_fee_entry(enrollment_id=b["enrollment"]["id"],
                               fee_type="MINIMUM_TOPUP")
        resp = api.waive_fee_entry(topup["id"], "ops-over-cap", BANK_OPS)
        validate_error(resp, ApiErrorId.ERR_WAIVER_EXCEEDS_AUTHORITY)
        waived = validate_success(api.waive_fee_entry(topup["id"],
                                                      "manager-override",
                                                      BANK_MGR))
        assert waived["status"] == "WAIVED"
        stmt = fee_statement(b["enrollment"]["id"], "2026-08")
        assert stmt["waived_cents"] == 4600
        assert stmt["net_due_cents"] == 400, (
            "only the two billed exception fees remain in the net")


class TestBillingRunGates:
    def test_billing_unclosed_period_rejected(self, api):
        """PRD §3.9: "A billing run requires the period to be fully elapsed —
        its last day must be entirely behind the logical clock, otherwise
        `ERR_PERIOD_NOT_CLOSED`".

        Design: Corner/endpoints/monthly_billing_current_period_rejected
        """
        enr = create_enrollment("EarlyCo", "POSITIVE_PAY", "PAY")
        set_clock("2026-08-15T00:00:00Z")
        resp = api.create_ops_run({"kind": "MONTHLY_BILLING",
                                   "enrollment_id": enr["id"],
                                   "period": "2026-08"}, BANK_OPS)
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSED)

    def test_billing_same_period_twice_rejected(self, api):
        """PRD §3.9: "refuses to run twice for the same enrollment and period:
        if any `BILLED` entries already exist for that pair, the run is rejected
        with `ERR_PERIOD_ALREADY_BILLED`."

        Design: Corner/endpoints/monthly_billing_twice_rejected
        """
        b = setup_reverse_tier_exceptions(1, default_decision="PAY",
                                          business_name="TwiceCo",
                                          account_number="840007",
                                          clock="2026-08-05T09:00:00Z")
        set_clock("2026-09-01T00:00:00Z")
        run = monthly_billing(b["enrollment"]["id"], "2026-08")
        assert run["fees_billed"] == 1
        resp = api.create_ops_run({"kind": "MONTHLY_BILLING",
                                   "enrollment_id": b["enrollment"]["id"],
                                   "period": "2026-08"}, BANK_OPS)
        validate_error(resp, ApiErrorId.ERR_PERIOD_ALREADY_BILLED)

    def test_statement_of_empty_period_is_zero(self, api):
        """PRD §3.7: "On that read, `net_due_cents` is the sum of the period's
        entries in `BILLED` status" — a period with no entries sums to zero and
        no top-up exists outside a billing run.

        Design: Corner/calculations/fee_statement_empty_period
        """
        enr = create_enrollment("EmptyCo", "POSITIVE_PAY", "PAY")
        stmt = fee_statement(enr["id"], "2026-08")
        assert stmt["net_due_cents"] == 0
        assert stmt["entry_count"] == 0
