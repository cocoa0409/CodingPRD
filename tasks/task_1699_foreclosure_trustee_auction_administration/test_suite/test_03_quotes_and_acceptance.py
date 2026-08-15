"""Quote variants, per-diem rounding order, expiry surface, and acceptance cascades."""
from test_helpers import (
    CM,
    ApiErrorId,
    add_bidding_instruction,
    approve_advance,
    create_beneficiary,
    create_case,
    get_case,
    issue_quote,
    qualify_bidder,
    record_nod,
    register_bidder,
    set_clock,
    setup_case_at_sale_scheduled,
    submit_cost_advance,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_quote_case():
    """Beneficiary + case LN-Q1 + RECORDED NOD + 35000/12000 APPROVED advances
    and one 99999 advance left SUBMITTED."""
    ben = create_beneficiary("BEN-Q1")
    case = create_case(
        ben["id"],
        loan_reference="LN-Q1",
        prepayment_penalty_applies=True,
    )
    record_nod(case["id"])
    a1 = submit_cost_advance(case["id"], ben["id"],
                             category="PUBLICATION", amount_cents=35_000)
    a2 = submit_cost_advance(case["id"], ben["id"],
                             category="RECORDING", amount_cents=12_000)
    submit_cost_advance(case["id"], ben["id"],
                        category="LEGAL", amount_cents=99_999)
    approve_advance(a1["id"])
    approve_advance(a2["id"])
    return {"beneficiary": ben, "case": get_case(case["id"])}


class TestQuoteVariantDivergence:
    def test_reinstatement_quote_line_items(self, api):
        """PRD §3.6: "`arrears_cents` — for a `REINSTATEMENT` quote, the `monthly_payment_cents` multiplied by `months_in_arrears`; for a `PAYOFF` quote, zero."
        PRD §3.6: "`costs_cents` — for both variants, the sum of `amount_cents` over the case's cost advances in `APPROVED` status at issuance; advances in `SUBMITTED`, `DENIED`, or `REIMBURSED` status are excluded."
        PRD §3.6: "`interest_cents` — for `REINSTATEMENT`, per-diem interest on the sum of the arrears and late-fees lines, accruing from the recording date of the case's `RECORDED` notice of default through the `good_through_date`; for `PAYOFF`, per-diem interest on the `unpaid_principal_balance_cents`, accruing from the `last_interest_paid_date` through the `good_through_date`."
        PRD §3.6: "`trustee_fee_cents` — a flat five hundred dollars (50000 cents) for `REINSTATEMENT`, a flat two hundred fifty dollars (25000 cents) for `PAYOFF`."

        Design: Difficulty/dual_variant_calc/quote_reinstatement_vs_payoff_divergence
        """
        ctx = _setup_quote_case()
        q = issue_quote(ctx["case"]["id"], "REINSTATEMENT", "2026-09-15")
        assert q["arrears_cents"] == 1_000_000  # 250000 x 4 months
        assert q["late_fees_cents"] == 50_000  # 12500 x 4 months
        assert q["costs_cents"] == 47_000, (
            "the 99999-cent SUBMITTED advance must be excluded"
        )
        # per-diem round(1050000*7.2/100/365) == 207; 45 days 2026-08-01 -> 2026-09-15
        assert q["interest_cents"] == 9_315
        assert q["trustee_fee_cents"] == 50_000
        assert q["prepayment_penalty_cents"] == 0
        assert q["total_cents"] == 1_156_315

    def test_payoff_quote_diverges_and_supersede_is_same_type_only(self, api):
        """PRD §3.6: "`prepayment_penalty_cents` — for `PAYOFF` only, when the case's `prepayment_penalty_applies` is true: two percent of the `unpaid_principal_balance_cents`, rounded half-up to whole cents; otherwise zero."
        PRD §3.6: "Per-diem interest, wherever it is used, is computed identically: the daily amount in cents is the base in cents multiplied by the `note_rate_pct`, divided by one hundred, divided by three hundred sixty-five, and rounded half-up to whole cents; that rounded daily amount is then multiplied by the number of calendar days in the accrual window, counting from the day after the start date through the end date inclusive."
        PRD §3.6: "On success, the prior `ISSUED` quote of the same `quote_type` on the case becomes `SUPERSEDED`, the new quote is created in `ISSUED` status with all six line items computed and stored, and the case's `version` increments."

        Design: Difficulty/dual_variant_calc/quote_reinstatement_vs_payoff_divergence
        """
        ctx = _setup_quote_case()
        case_id = ctx["case"]["id"]
        q_re = issue_quote(case_id, "REINSTATEMENT", "2026-09-15")
        q_po = issue_quote(case_id, "PAYOFF", "2026-09-15")

        # per-diem round(40000000*7.2/100/365) == 7890; 76 days 2026-07-01 -> 2026-09-15
        assert q_po["arrears_cents"] == 0
        assert q_po["late_fees_cents"] == 0
        assert q_po["costs_cents"] == 47_000
        assert q_po["interest_cents"] == 599_640
        assert q_po["trustee_fee_cents"] == 25_000
        assert q_po["prepayment_penalty_cents"] == 800_000
        assert q_po["total_cents"] == 41_471_640

        rows, _meta = validate_paginated(api.list_quotes(case_id, CM))
        re_row = next(r for r in rows if r["id"] == q_re["id"])
        assert re_row["status"] == "ISSUED", (
            "a PAYOFF issuance must not supersede the REINSTATEMENT quote"
        )


class TestPerDiemRoundingOrder:
    def _payoff_quote(self, api):
        ben = create_beneficiary("BEN-R2")
        case = create_case(
            ben["id"],
            loan_reference="LN-R2",
            unpaid_principal_balance_cents=10_000_000,
            monthly_payment_cents=100_000,
            months_in_arrears=1,
            late_fee_per_month_cents=5_000,
            note_rate_pct=4.5,
            last_interest_paid_date="2026-07-20",
        )
        return issue_quote(case["id"], "PAYOFF", "2026-08-11")

    def test_per_diem_rounds_before_multiplying(self, api):
        """PRD §2.6: "Per-diem interest rounds the daily amount to whole cents first and only then multiplies by the day count. Rounding after multiplication is forbidden."
        PRD §3.6: "`interest_cents` — for `REINSTATEMENT`, per-diem interest on the sum of the arrears and late-fees lines, accruing from the recording date of the case's `RECORDED` notice of default through the `good_through_date`; for `PAYOFF`, per-diem interest on the `unpaid_principal_balance_cents`, accruing from the `last_interest_paid_date` through the `good_through_date`."

        Design: Difficulty/combinatorial_formula/quote_per_diem_round_then_multiply_order
        """
        q = self._payoff_quote(api)
        # round(10000000*4.5/100/365) == 1233 first, then 1233 x 22 days == 27126.
        # Multiply-then-round would yield 27123 — exactly 3 cents off.
        assert q["interest_cents"] == 27_126, (
            f"round-then-multiply order is pinned; got {q['interest_cents']}"
        )

    def test_quote_total_sums_rounded_lines(self, api):
        """PRD §2.6: "Quote line items are each computed and rounded to integer cents first, and the quote total is a single sum of those six integer lines. Summing unrounded values and rounding the total is forbidden."
        PRD §3.6: "`costs_cents` — for both variants, the sum of `amount_cents` over the case's cost advances in `APPROVED` status at issuance; advances in `SUBMITTED`, `DENIED`, or `REIMBURSED` status are excluded."

        Design: Difficulty/combinatorial_formula/quote_per_diem_round_then_multiply_order
        """
        q = self._payoff_quote(api)
        assert q["costs_cents"] == 0
        assert q["total_cents"] == 10_052_126, (
            f"10000000 principal + 27126 interest + 25000 fee; got {q['total_cents']}"
        )


class TestQuoteExpiryPrecedence:
    def _expired_payoff_quote(self, api):
        ben = create_beneficiary("BEN-V2")
        case = create_case(
            ben["id"],
            loan_reference="LN-V2",
            unpaid_principal_balance_cents=10_000_000,
            monthly_payment_cents=100_000,
            months_in_arrears=1,
            late_fee_per_month_cents=5_000,
            note_rate_pct=4.5,
            last_interest_paid_date="2026-07-20",
        )
        quote = issue_quote(case["id"], "PAYOFF", "2026-08-10")
        set_clock("2026-08-11T00:00:00Z")
        return case, quote

    def test_expired_quote_accept_reports_expiry_not_shortfall(self, api):
        """PRD §3.6: "Five checks run in order: the case must be in a status that permits the acceptance for the quote's type (`ERR_INVALID_CASE_STATE`); the quote's stored status must be `ISSUED` (`ERR_INVALID_QUOTE_STATE`); the clock date must not have passed the `good_through_date` (`ERR_QUOTE_EXPIRED`); for a `REINSTATEMENT` quote with a sale pending, the reinstatement cutoff must not have passed (`ERR_REINSTATEMENT_CUTOFF_PASSED`, HTTP 422); and the tendered amount must equal the quote's `total_cents` exactly — a tender even one cent short or one cent over is rejected with `ERR_PAYMENT_SHORTFALL` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/quote_expired_beats_payment_shortfall
        """
        _case, quote = self._expired_payoff_quote(api)
        resp = api.accept_quote(quote["id"], {"tendered_amount_cents": 1}, CM)
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED, 422)

    def test_expired_quote_reads_expired_and_case_untouched(self, api):
        """PRD §3.6: "A quote's `EXPIRED` status is derived, never stored. While the stored status remains `ISSUED`, any read of the quote — and any acceptance attempt — made when the clock date has passed the `good_through_date` surfaces the status as `EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/quote_expired_beats_payment_shortfall
        """
        case, quote = self._expired_payoff_quote(api)
        api.accept_quote(quote["id"], {"tendered_amount_cents": 1}, CM)
        rows, _meta = validate_paginated(api.list_quotes(case["id"], CM))
        row = next(r for r in rows if r["id"] == quote["id"])
        assert row["status"] == "EXPIRED", (
            f"derived expiry must surface on read, got {row['status']}"
        )
        assert get_case(case["id"])["lifecycle_status"] == "REFERRED"

    def test_quote_lazy_expiry_visible_on_read(self, api):
        """PRD §3.6: "A quote's `EXPIRED` status is derived, never stored. While the stored status remains `ISSUED`, any read of the quote — and any acceptance attempt — made when the clock date has passed the `good_through_date` surfaces the status as `EXPIRED`."

        Design: Corner/cross_cutting_complexity_layers/quote_lazy_expiry_visible_on_read
        """
        ben = create_beneficiary("BEN-L6")
        case = create_case(
            ben["id"],
            loan_reference="LN-L6",
            unpaid_principal_balance_cents=10_000_000,
            monthly_payment_cents=100_000,
            months_in_arrears=1,
            late_fee_per_month_cents=5_000,
            note_rate_pct=4.5,
            last_interest_paid_date="2026-07-20",
        )
        quote = issue_quote(case["id"], "PAYOFF", "2026-08-10")
        assert quote["status"] == "ISSUED"
        set_clock("2026-08-11T00:00:00Z")
        rows, _meta = validate_paginated(
            api.list_quotes(case["id"], CM, params={"quote_type": "PAYOFF"})
        )
        assert rows[0]["status"] == "EXPIRED"


class TestPayoffTerminalCascade:
    def _setup_sale_scheduled_with_quote(self, api):
        ctx = setup_case_at_sale_scheduled("BEN-X2", venue_name="VEN-X2",
                                           loan_reference="LN-X2")
        case_id = ctx["case"]["id"]
        ctx["instruction"] = add_bidding_instruction(
            case_id, ctx["beneficiary"]["id"],
            opening_bid_cents=42_000_000, max_bid_cents=43_000_000,
            strategy="OPENING_ONLY",
        )
        ctx["registration"] = register_bidder(
            ctx["sale"]["id"], bidder_name="Bidder Y",
            bidder_email="by@bid.example", deposit_cents=1_000_000,
        )
        qualify_bidder(ctx["registration"]["id"])
        ctx["quote"] = issue_quote(case_id, "PAYOFF", "2026-12-31")
        return ctx

    def test_payoff_total_and_case_terminal_transition(self, api):
        """PRD §3.6: "Accepting a `PAYOFF` quote moves the case to `PAID_OFF` from any of `REFERRED`, `NOD_RECORDED`, `NOTS_RECORDED`, or `SALE_SCHEDULED`, and every payoff acceptance reimburses the beneficiary's costs inside the payoff: all of the case's cost advances in `APPROVED` status become `REIMBURSED` (decrementing the beneficiary's outstanding-advances total accordingly), and every other `ISSUED` quote on the case becomes `VOIDED`."

        Design: Difficulty/transitive_cascade/payoff_acceptance_terminal_cascade
        """
        ctx = self._setup_sale_scheduled_with_quote(api)
        quote = ctx["quote"]
        # 40000000 + (7890 x 183 days) + 25000 == 41468870
        assert quote["total_cents"] == 41_468_870
        accepted = validate_success(
            api.accept_quote(
                quote["id"], {"tendered_amount_cents": 41_468_870}, CM
            ),
            200,
        )
        assert accepted["status"] == "ACCEPTED"
        case = get_case(ctx["case"]["id"])
        assert case["lifecycle_status"] == "PAID_OFF"
        sale = validate_success(api.get_auction_sale(ctx["sale"]["id"], CM), 200)
        assert sale["status"] == "VOIDED", (
            "the case terminal transition voids the scheduled sale"
        )

    def test_payoff_cascade_settles_registration_and_instruction(self, api):
        """PRD §3.6: "From `SALE_SCHEDULED`: additionally, the `RECORDED` notice of default becomes `RESCINDED`, the notice of trustee's sale in `SALE_SCHEDULED` status becomes `CONCLUDED`, the scheduled auction sale becomes `VOIDED`, every `QUALIFIED` bidder registration becomes `REFUND_PENDING`, and the `ACTIVE` bidding instruction becomes `EXPIRED`."

        Design: Difficulty/transitive_cascade/payoff_acceptance_terminal_cascade
        """
        ctx = self._setup_sale_scheduled_with_quote(api)
        validate_success(
            api.accept_quote(
                ctx["quote"]["id"], {"tendered_amount_cents": 41_468_870}, CM
            ),
            200,
        )
        reg = validate_success(
            api.get_bidder_registration(ctx["registration"]["id"], CM), 200
        )
        assert reg["status"] == "REFUND_PENDING", (
            f"hop 3: sale void settles the room, got {reg['status']}"
        )
        nots = validate_success(api.get_nots(ctx["nots"]["id"], CM), 200)
        assert nots["status"] == "CONCLUDED"
        rows, _meta = validate_paginated(
            api.list_bidding_instructions(ctx["case"]["id"], CM)
        )
        instr = next(r for r in rows if r["id"] == ctx["instruction"]["id"])
        assert instr["status"] == "EXPIRED"


class TestReinstatementCutoff:
    def test_reinstatement_cutoff_five_business_days(self, api):
        """PRD §3.6: "The reinstatement cutoff deserves precision: when an auction sale in `SCHEDULED` or `CONDUCTED` status exists on the case, a reinstatement may be accepted only while the clock date is on or before the date five business days before the scheduled sale date, computed by walking backward from the sale date one calendar day at a time and counting only Monday through Friday — weekends are skipped, and no holiday calendar is applied. Acceptance on the cutoff day itself is allowed. When no such sale exists, no cutoff applies."
        PRD §3.6: "From `NOD_RECORDED`: the `RECORDED` notice of default becomes `RESCINDED`, and the case becomes `REINSTATED`."

        Design: Corner/validations/reinstatement_cutoff_five_business_days
        """
        # Sale on Monday 2026-11-23 -> cutoff is Monday 2026-11-16 (weekend skipped).
        ctx = setup_case_at_sale_scheduled("BEN-VL3", venue_name="VEN-VL3",
                                           loan_reference="LN-VL3")
        case_id = ctx["case"]["id"]
        quote = issue_quote(case_id, "REINSTATEMENT", "2026-11-23")
        assert quote["total_cents"] == 1_123_598, (
            f"arrears 1000000 + late 50000 + interest 23598 + fee 50000; "
            f"got {quote['total_cents']}"
        )

        set_clock("2026-11-17T00:00:00Z")
        resp = api.accept_quote(
            quote["id"], {"tendered_amount_cents": 1_123_598}, CM
        )
        validate_error(resp, ApiErrorId.ERR_REINSTATEMENT_CUTOFF_PASSED, 422)

        set_clock("2026-11-16T12:00:00Z")
        accepted = validate_success(
            api.accept_quote(
                quote["id"], {"tendered_amount_cents": 1_123_598}, CM
            ),
            200,
        )
        assert accepted["status"] == "ACCEPTED"
        assert get_case(case_id)["lifecycle_status"] == "REINSTATED"
        nods, _meta = validate_paginated(api.list_nods(case_id, CM))
        assert nods[0]["status"] == "RESCINDED", (
            "reinstatement rescinds the RECORDED notice of default"
        )
