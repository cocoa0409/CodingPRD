"""Dividends: per-payment rounding order, combinatorial withholding tiers,
provisional vs final dual variants, suspended-issuer gating, the
return/reissue cycle, stale-dating cascade, and issuer reporting."""
from test_helpers import (
    ApiErrorId,
    assert_payment_money_conserved,
    create_account,
    create_declaration,
    create_issuer,
    declaration_payload,
    get_account,
    get_declaration,
    list_payments,
    make_issuer_officer_headers,
    officer_headers,
    patch_account,
    patch_issuer,
    seed_position,
    set_clock,
    setup_disbursed_payment,
    setup_mixed_residency_payments,
    setup_returned_payment,
    setup_suspended_issuer_declaration,
    setup_two_share_667_declaration,
    setup_w9_cure_payment,
    single_payment,
    validate_error,
    validate_success,
    SERVICE,
    withdraw_certificate,
)


class TestProvisionalVsFinalWithholding:
    def test_provisional_withholding_uses_record_date_tin(self, api):
        """PRD §3.5: "Each generated payment also carries a provisional
        withholding, computed against the account's tax attributes as they
        stand on the record date and stored in
        `provisional_withholding_cents`."
        PRD §3.5: "When the `tin_status` is `MISSING` or `UNCERTIFIED`, the
        backup withholding rate of 24 percent applies."

        Design: Difficulty/dual_variant_calc/withholding_provisional_vs_final_tin_cure
        """
        ctx = setup_w9_cure_payment()
        payment = ctx["payment"]
        assert payment["gross_cents"] == 500, "1000 shares x 500 millicents / 1000"
        assert payment["provisional_withholding_cents"] == 120, (
            "record-date tin_status MISSING -> 24% backup withholding"
        )

    def test_final_withholding_uses_payable_date_tin(self, api):
        """PRD §3.5: "At this point each payment's withholding is recomputed
        under the identical rate rules, but now against the account's tax
        attributes as of the payable date; the result is stored as the final
        `withholding_cents`, and the payment's `net_cents` is its `gross_cents`
        minus its `withholding_cents`."
        PRD §3.5: "When the `tin_status` is `CERTIFIED` and the `residency` is
        `US`, the rate is zero."
        PRD §3.5: "the final `withholding_cents` can legitimately diverge from
        the earlier `provisional_withholding_cents` on identical share counts."

        Design: Difficulty/dual_variant_calc/withholding_provisional_vs_final_tin_cure
        """
        ctx = setup_w9_cure_payment()
        payment = ctx["payment"]
        assert payment["status"] == "DISBURSED"
        assert payment["withholding_cents"] == 0, (
            "the W-9 cure before the payable date zeroes the final withholding"
        )
        assert payment["net_cents"] == 500
        assert payment["provisional_withholding_cents"] != payment["withholding_cents"], (
            "provisional (120) and final (0) diverge on the same payment row"
        )
        assert_payment_money_conserved(payment)


class TestPerPaymentRounding:
    def test_per_payment_gross_rounds_half_up(self, api):
        """PRD §3.5: "Consider two accounts each holding a single share against
        a declaration of 667 millicents per share: each payment's gross rounds
        to one cent, and the declaration total is two cents — summing first
        would round thirteen hundred thirty-four millicents to a single cent."

        Design: Difficulty/combinatorial_formula/per_payment_rounding_beats_sum_then_round
        """
        ctx = setup_two_share_667_declaration()
        assert len(ctx["payments"]) == 2
        for payment in ctx["payments"]:
            assert payment["gross_cents"] == 1, (
                "round_half_up(1 x 667 / 1000) = 1, per payment"
            )
            assert payment["eligible_shares"] == 1

    def test_declaration_total_sums_rounded_payments(self, api):
        """PRD §3.5: "Only then does the declaration aggregate: its
        `total_accrued_cents` is the sum of the already-rounded per-payment
        `gross_cents`, and its `total_eligible_shares` is the sum of the
        `eligible_shares` over the generated payments. Aggregating millicents
        first and rounding once at the end is forbidden, because it yields
        different cents."

        Design: Difficulty/combinatorial_formula/per_payment_rounding_beats_sum_then_round
        """
        ctx = setup_two_share_667_declaration()
        declaration = get_declaration(ctx["declaration"]["id"])
        assert declaration["status"] == "ACCRUED"
        assert declaration["total_accrued_cents"] == 2, (
            "per-payment rounding yields 2; the forbidden sum-then-round "
            "order would yield 1"
        )
        assert declaration["total_eligible_shares"] == 2


class TestWithholdingTierMatrix:
    def test_treaty_tier_withholds_15_percent(self, api):
        """PRD §3.5: "When the `tin_status` is `CERTIFIED` and the `residency`
        is `FOREIGN`, the treaty tier decides: a `TREATY` tier withholds 15
        percent, and a `STANDARD` tier withholds 30 percent."
        PRD §3.5: "The withheld amount is the `gross_cents` multiplied by the
        applicable rate, rounded half-up to a whole cent."

        Design: Difficulty/combinatorial_formula/withholding_tier_branch_matrix
        """
        ctx = setup_mixed_residency_payments()
        pay_f = ctx["pay_f"]
        assert pay_f["gross_cents"] == 1000, "2000 shares x 500 millicents / 1000"
        assert pay_f["withholding_cents"] == 150, "CERTIFIED + FOREIGN + TREATY -> 15%"
        assert pay_f["net_cents"] == 850
        assert_payment_money_conserved(pay_f)

    def test_missing_tin_withholds_24_percent(self, api):
        """PRD §3.5: "When the `tin_status` is `MISSING` or `UNCERTIFIED`, the
        backup withholding rate of 24 percent applies."
        PRD §3.5: "The withholding rate is determined combinatorially from the
        account's `tin_status`, `residency`, and `treaty_tier`."

        Design: Difficulty/combinatorial_formula/withholding_tier_branch_matrix
        """
        ctx = setup_mixed_residency_payments()
        pay_m = ctx["pay_m"]
        assert pay_m["gross_cents"] == 500, "1000 shares x 500 millicents / 1000"
        assert pay_m["withholding_cents"] == 120, "MISSING -> 24% backup rate"
        assert pay_m["net_cents"] == 380
        assert pay_m["withholding_cents"] != ctx["pay_f"]["withholding_cents"], (
            "the rate differs on the same declaration, driven only by the "
            "account tax attributes"
        )


class TestUncertifiedTinArm:
    def test_uncertified_tin_withholds_24_percent(self, api):
        """PRD §3.5: "When the `tin_status` is `MISSING` or `UNCERTIFIED`, the
        backup withholding rate of 24 percent applies."
        PRD §2.4: "Each time the clock is set, the server evaluates every
        time-gated system transition at the new instant: dividend declarations
        whose `record_date` has been reached are accrued, accrued declarations
        whose `payable_date` has been reached become payable and disburse their
        payments"

        Design: Corner/calculations/uncertified_tin_withholds_24_percent
        """
        ctx = setup_disbursed_payment(
            shares=400, millicents=500, tin_status="UNCERTIFIED",
            record_date="2026-09-01T00:00:00Z",
            payable_date="2026-09-15T00:00:00Z",
            holder_name="Uncert Uma", single_clock_set=True)
        payment = ctx["payment"]
        assert payment["status"] == "DISBURSED", (
            "one clock set past both dates evaluates accrual and disbursement"
        )
        assert payment["gross_cents"] == 200
        assert payment["withholding_cents"] == 48, "24% of 200"
        assert payment["net_cents"] == 152


class TestRecordDateSnapshot:
    def test_record_date_snapshot_counts_book_plus_certificated(self, api):
        """PRD §3.5: "Each payment's `eligible_shares` is a snapshot of the
        position's `total_shares` — its `book_entry_shares` plus its
        `certificated_shares` — taken at the record-lock instant."

        Design: Corner/calculations/record_date_snapshot_counts_book_plus_certificated
        """
        issuer = create_issuer(name="Theta Snapshot", cusip="000000032",
                               ticker="TSNA", shares_outstanding=100)
        account = create_account(holder_name="Snapshot Sid", postal_code="74112",
                                 tax_id="302-12-1212", tin_status="CERTIFIED")
        position = seed_position(account["id"], issuer["id"], 100)
        withdraw_certificate(position["id"], 40)  # 60 book + 40 certificated
        declaration = create_declaration(
            issuer, amount_per_share_millicents=1000)

        set_clock("2026-09-01T00:00:00Z")
        payment = single_payment(declaration["id"])
        assert payment["eligible_shares"] == 100, (
            "60 book + 40 certificated at the record-lock instant"
        )
        assert payment["gross_cents"] == 100
        assert get_declaration(declaration["id"])["total_eligible_shares"] == 100


class TestDeclarationGates:
    def test_declaration_payable_not_after_record_rejected(self, api):
        """PRD §3.5: "The `payable_date` must fall strictly after the
        `record_date`; a payable date on the record date itself, or before it,
        is refused with `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/declaration_payable_not_after_record_rejected
        """
        issuer = create_issuer(name="Lambda Dates", cusip="000000035",
                               ticker="LDAT")
        resp = api.create_dividend_declaration(
            declaration_payload(issuer["id"],
                                record_date="2026-09-01T00:00:00Z",
                                payable_date="2026-09-01T00:00:00Z"),
            make_issuer_officer_headers(issuer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_voided_declaration_never_accrues(self, api):
        """PRD §3.5: "Before the record date arrives, the officer may still
        void the declaration, moving it `DECLARED` → `VOIDED`; no payments are
        ever generated for a voided declaration, and clock evaluation skips
        `VOIDED` declarations entirely."

        Design: Corner/state_machines/voided_declaration_never_accrues
        """
        ctx_issuer = create_issuer(name="Epsilon Void", cusip="000000029",
                                   ticker="EVOI")
        account = create_account(holder_name="Void Vera", postal_code="74110",
                                 tax_id="272-12-1212")
        seed_position(account["id"], ctx_issuer["id"], 100)
        declaration = create_declaration(ctx_issuer)
        voided = validate_success(api.void_declaration(
            declaration["id"], officer_headers(ctx_issuer)))
        assert voided["status"] == "VOIDED"

        set_clock("2026-09-20T00:00:00Z")  # past both record and payable dates
        assert get_declaration(declaration["id"])["status"] == "VOIDED"
        assert list_payments(declaration["id"]) == [], (
            "a voided declaration never generates payments"
        )


class TestSuspendedIssuerAccrual:
    def test_accrual_skipped_while_issuer_suspended(self, api):
        """PRD §3.5: "When the logical clock reaches a `DECLARED` declaration's
        `record_date`, the declaration moves `DECLARED` → `ACCRUED` — provided
        the issuer is `ACTIVE` at evaluation time, since the
        `ERR_ISSUER_SUSPENDED` gate applies to clock-driven accrual just as it
        does to transfer creation and declaration creation."

        Design: Difficulty/cross_entity_state_dependency/accrual_blocked_by_suspended_issuer
        """
        ctx = setup_suspended_issuer_declaration()
        set_clock("2026-09-05T00:00:00Z")  # past the record date
        declaration = get_declaration(ctx["declaration"]["id"])
        assert declaration["status"] == "DECLARED", (
            "the suspended issuer blocks the clock-driven accrual"
        )
        assert list_payments(ctx["declaration"]["id"]) == []

    def test_accrual_resumes_after_issuer_reactivated(self, api):
        """PRD §3.5: "When the logical clock reaches a `DECLARED` declaration's
        `record_date`, the declaration moves `DECLARED` → `ACCRUED` — provided
        the issuer is `ACTIVE` at evaluation time"
        PRD §3.5: "the server walks every `ACTIVE` position of the declaring
        issuer whose owning account is not `ESCHEATED` and generates one
        `DividendPayment` per eligible position, in `ACCRUED` status."

        Design: Difficulty/cross_entity_state_dependency/accrual_blocked_by_suspended_issuer
        """
        ctx = setup_suspended_issuer_declaration()
        set_clock("2026-09-05T00:00:00Z")
        assert get_declaration(ctx["declaration"]["id"])["status"] == "DECLARED"

        patch_issuer(ctx["issuer"], {"status": "ACTIVE"})
        set_clock("2026-09-06T00:00:00Z")
        assert get_declaration(ctx["declaration"]["id"])["status"] == "ACCRUED"
        payments = list_payments(ctx["declaration"]["id"])
        assert len(payments) == 1
        assert payments[0]["eligible_shares"] == 100


class TestReturnReissueCycle:
    def test_return_reissue_preserves_row_money(self, api):
        """PRD §3.5: "the payment's `net_cents` is its `gross_cents` minus its
        `withholding_cents`."
        PRD §3.5: "A successful reissue returns the payment `RETURNED` →
        `DISBURSED` and restamps `disbursed_at` from the logical clock,
        restarting the stale-dating clock from zero; the payment may later be
        returned again, and the return-and-reissue cycle may repeat."

        Design: Difficulty/compensating_invariant/dividend_cash_conservation_return_reissue
        """
        ctx = setup_disbursed_payment(shares=1000, millicents=500,
                                      tin_status="MISSING", state_code="TX",
                                      holder_name="Walt Withheld")
        payment = ctx["payment"]
        assert payment["gross_cents"] == 500
        assert payment["withholding_cents"] == 120
        assert payment["net_cents"] == 380
        assert_payment_money_conserved(payment)

        returned = validate_success(
            api.mark_payment_returned(payment["id"], SERVICE))
        assert returned["status"] == "RETURNED"
        assert_payment_money_conserved(returned)

        patch_account(ctx["account"]["id"],
                      {"address_line1": "27 Chestnut St Ste 4"})
        reissued = validate_success(api.reissue_payment(payment["id"], SERVICE))
        assert reissued["status"] == "DISBURSED"
        assert_payment_money_conserved(reissued), (
            "return and reissue compensate; the row money does not drift"
        )

    def test_return_reissue_preserves_declaration_total(self, api):
        """PRD §3.5: "Both totals are frozen at accrual, and
        `total_accrued_cents` is immutable from `ACCRUED` onward: an invariant
        anchor against which all later disbursement activity reconciles."
        PRD §3.1: "Every such patch sets `address_verified` back to true"

        Design: Difficulty/compensating_invariant/dividend_cash_conservation_return_reissue
        """
        ctx = setup_disbursed_payment(shares=1000, millicents=500,
                                      tin_status="MISSING", state_code="TX",
                                      holder_name="Walt Withheld")
        api.mark_payment_returned(ctx["payment"]["id"], SERVICE)
        assert get_account(ctx["account"]["id"])["address_verified"] is False

        patch_account(ctx["account"]["id"],
                      {"address_line1": "27 Chestnut St Ste 4"})
        assert get_account(ctx["account"]["id"])["address_verified"] is True, (
            "the PATCH side effect is what unblocks the reissue"
        )
        api.reissue_payment(ctx["payment"]["id"], SERVICE)

        declaration = get_declaration(ctx["declaration"]["id"])
        assert declaration["total_accrued_cents"] == 500, (
            "frozen at accrual and unmoved by the return/reissue cycle"
        )

    def test_returned_payment_reissue_refreshes_disbursed_at(self, api):
        """PRD §3.5: "A successful reissue returns the payment `RETURNED` →
        `DISBURSED` and restamps `disbursed_at` from the logical clock,
        restarting the stale-dating clock from zero"
        PRD §3.5: "A `ServiceAgent` marking a disbursed payment undeliverable
        moves it `DISBURSED` → `RETURNED`, stamps its `returned_at` from the
        logical clock, and flips the account's `address_verified` to false"

        Design: Corner/state_machines/returned_payment_reissue_refreshes_disbursed_at
        """
        ctx = setup_disbursed_payment(holder_name="Reissue Ray")
        assert ctx["payment"]["disbursed_at"] == "2026-08-03T00:00:00.000Z"

        set_clock("2026-08-10T00:00:00Z")
        returned = validate_success(
            api.mark_payment_returned(ctx["payment"]["id"], SERVICE))
        assert returned["status"] == "RETURNED"

        set_clock("2026-08-12T00:00:00Z")
        patch_account(ctx["account"]["id"], {"address_line1": "7 Mail St Apt 2"})
        reissued = validate_success(
            api.reissue_payment(ctx["payment"]["id"], SERVICE))
        assert reissued["status"] == "DISBURSED"
        assert reissued["disbursed_at"] == "2026-08-12T00:00:00.000Z", (
            "the stale-dating clock restarts at the reissue instant, not the "
            "original 2026-08-03"
        )
        assert get_account(ctx["account"]["id"])["address_verified"] is True

    def test_reissue_blocked_while_address_unverified(self, api):
        """PRD §3.5: "a `RETURNED` payment may be reissued only after the
        address has been verified again, so an account whose `address_verified`
        is still false refuses the reissue with `ERR_ADDRESS_UNVERIFIED`."

        Design: Corner/validations/reissue_blocked_while_address_unverified
        """
        ctx = setup_returned_payment(holder_name="Address Amy")
        resp = api.reissue_payment(ctx["payment"]["id"], SERVICE)
        validate_error(resp, ApiErrorId.ERR_ADDRESS_UNVERIFIED)
        payment = validate_success(api.get_dividend_payment(
            ctx["payment"]["id"], SERVICE))
        assert payment["status"] == "RETURNED"
        assert get_account(ctx["account"]["id"])["address_verified"] is False


class TestIssuerReporting:
    def test_record_date_report_matches_accrual_snapshot(self, api):
        """PRD §3.5: "For issuer reporting, an `IssuerOfficer` or `AgentAdmin`
        can pull the record-date list for a declaration — the holder-of-record
        snapshot — which returns the `declaration_id`, the `record_date`, the
        `total_shares` and `total_accounts` of the eligible register, and the
        per-holder `entries` rows."

        Design: Corner/endpoints/record_date_report_matches_accrual_snapshot
        """
        issuer = create_issuer(name="Alpha Report", cusip="000000044",
                               ticker="AREP", shares_outstanding=100)
        acct1 = create_account(holder_name="Report Rob", postal_code="74124",
                               tax_id="452-12-1212", tin_status="CERTIFIED")
        acct2 = create_account(holder_name="Report Rae", postal_code="74125",
                               tax_id="462-12-1212", tin_status="CERTIFIED")
        seed_position(acct1["id"], issuer["id"], 70)
        seed_position(acct2["id"], issuer["id"], 30)
        declaration = create_declaration(issuer)
        set_clock("2026-09-01T00:00:00Z")

        report = validate_success(api.get_record_date_report(
            issuer["id"], declaration["id"],
            make_issuer_officer_headers(issuer["id"])))
        assert report["declaration_id"] == declaration["id"]
        assert report["record_date"] == "2026-09-01T00:00:00.000Z"
        assert report["total_accounts"] == 2
        assert report["total_shares"] == 100
        assert len(report["entries"]) == 2, "one row per holder of record"
