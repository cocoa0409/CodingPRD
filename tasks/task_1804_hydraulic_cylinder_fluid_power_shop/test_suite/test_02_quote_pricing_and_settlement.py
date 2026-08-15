"""Provisional/final quote pricing, per-line rounding, and invoice settlement
(PRD §2.8, §3.3, §3.8)."""
from test_helpers import (
    ADVISOR,
    close_work_order,
    get_line_amount,
    get_success_data,
    setup_certified,
    setup_quote_draft,
    setup_quote_sent,
    validate_success,
)


class TestProvisionalPricingRounding:
    def test_quote_per_line_rounding_total_and_labor(self, api):
        """PRD §2.8: "The evaluation order is pinned: round each line first, then
        sum. Summing the raw unrounded lines and rounding once at the end is
        incorrect — the two orders disagree whenever two or more raw lines carry
        a fractional half-cent."
        PRD §3.3: "The labor line starts from a raw amount —
        `estimated_labor_hours` multiplied by `labor_rate_cents_per_hour`
        multiplied by the tier multiplier — and the line itself is that raw
        amount rounded half-up to integer cents."

        Design: Difficulty/combinatorial_formula/quote_per_line_rounding_then_sum
        """
        sc = setup_quote_draft()  # EXPEDITE, rod 500mm, honing 1, est 2.5h
        quote = validate_success(
            api.create_quote({"work_order_id": sc.work_order["id"]}, ADVISOR), 201
        )
        # labor_raw = 2.5 x 14500 x 1.35 = 48937.5 -> 48938 (half-up).
        assert get_line_amount(quote, "LABOR") == 48938
        # Per-line round then sum: 18500 + 22500 + 4000 + 48938 + 1958.
        assert quote["provisional_total_cents"] == 95896

    def test_quote_per_line_rounding_supplies_uses_raw_labor(self, api):
        """PRD §3.3: "The supplies line is `supplies_pct_of_labor` multiplied by
        the raw, unrounded labor amount, rounded half-up to integer cents."
        PRD §3.3: "Each entry of `line_items` carries a `kind` — one of
        `SEAL_KIT`, `ROD`, `TUBE`, `HONING`, `LABOR`, `SUPPLIES` — and an
        `amount_cents`."

        Design: Difficulty/combinatorial_formula/quote_per_line_rounding_then_sum
        """
        sc = setup_quote_draft()
        quote = validate_success(
            api.create_quote({"work_order_id": sc.work_order["id"]}, ADVISOR), 201
        )
        # supplies_raw = 0.04 x 48937.5 = 1957.5 -> 1958 (computed on RAW labor).
        assert get_line_amount(quote, "SUPPLIES") == 1958
        assert get_line_amount(quote, "SEAL_KIT") == 18500
        # ROD line: 500mm x 42c/mm + 1500c cut fee = 22500 (shop default estimate).
        assert get_line_amount(quote, "ROD") == 22500
        assert get_line_amount(quote, "HONING") == 4000
        kinds = {line["kind"] for line in quote["line_items"]}
        assert kinds == {"SEAL_KIT", "ROD", "HONING", "LABOR", "SUPPLIES"}


class TestProvisionalVsFinalDivergence:
    def test_provisional_total_at_quote_creation(self, api):
        """PRD §3.3: "Per the pinned rounding order of §2.8, each line is rounded
        half-up to integer cents first and the lines are then summed into
        `provisional_total_cents`; the provisional variant prices materials at
        the shop's default per-millimetre estimates and carries no scrap line."

        Design: Difficulty/dual_variant_calc/quote_provisional_vs_final_pricing_divergence
        """
        sc = setup_quote_sent()
        assert sc.quote["provisional_total_cents"] == 95896
        assert sc.quote["status"] == "SENT"

    def test_final_total_at_close_diverges_from_provisional(self, api):
        """PRD §3.8: "Closing computes the final pricing variant: the same line
        structure and rounding order as the provisional variant of §3.3, but the
        labor line uses `actual_labor_hours` in place of the estimate, the rod
        and tube lines price the consumed reservation's `consumed_length_mm` at
        the consumed item's actual `cost_per_mm_cents` — still plus one flat
        `cut_fee_cents` each — and a scrap line is added summing
        `scrap_charge_cents` across all of the work order's reservations."
        PRD §3.8: "Either way the work order moves to the terminal `CLOSED`
        state, and only then are `final_total_cents` (repair path) and
        `invoice_total_cents` no longer null."

        Design: Difficulty/dual_variant_calc/quote_provisional_vs_final_pricing_divergence
        """
        sc = setup_certified()
        closed = close_work_order(sc.work_order, 3.5)
        assert closed["status"] == "CLOSED"
        # Final: 18500 + (500x42+1500) + 4000 + round_half_up(3.5x14500x1.35=68512.5)
        #        + round_half_up(0.04x68512.5=2740.5) = 18500+22500+4000+68513+2741.
        assert closed["final_total_cents"] == 116254
        quote = get_success_data(api.get_quote(sc.quote["id"], ADVISOR))
        assert quote["provisional_total_cents"] == 95896
        assert closed["final_total_cents"] != quote["provisional_total_cents"]


class TestQuoteStamps:
    def test_quote_creation_stamps_pin_and_tier_snapshot(self, api):
        """PRD §3.3: "Drafting pins the teardown report current at that moment —
        the quote records it as `teardown_report_id` and its version as
        `pinned_teardown_version` — copies the work order's `tier` into
        `tier_snapshot` so that pricing always uses the snapshot even if the tier
        is later reinterpreted, computes the priced `line_items` and
        `provisional_total_cents` under the provisional pricing variant, and
        starts the quote in `DRAFT` with `sent_at` null."

        Design: Corner/entities/quote_creation_stamps_pin_and_tier_snapshot
        """
        sc = setup_quote_draft(tier="EMERGENCY", promised_hours=12, rod_needed=False,
                               honing_passes=0, estimated_labor_hours=2.0)
        quote = validate_success(
            api.create_quote({"work_order_id": sc.work_order["id"]}, ADVISOR), 201
        )
        assert quote["teardown_report_id"] == sc.report["id"]
        assert quote["pinned_teardown_version"] == 1
        assert quote["tier_snapshot"] == "EMERGENCY"
        assert quote["status"] == "DRAFT"
        assert quote["sent_at"] is None
        # labor_raw = 2.0 x 14500 x 1.75 = 50750.0; supplies = 0.04 x 50750 = 2030.
        # total = 18500 + 50750 + 2030 = 71280.
        assert quote["provisional_total_cents"] == 71280


class TestInvoiceSettlement:
    def test_invoice_gold_tier_at_exact_threshold(self, api):
        """PRD §3.8: "The loyalty tier is tested against the customer's
        `ytd_spend_cents` before this invoice plus the pre-discount subtotal: the
        tier is `GOLD` when that sum is at least `loyalty_gold_threshold_cents`
        (500000 by default), else `SILVER` when at least
        `loyalty_silver_threshold_cents` (100000 by default), else `NONE`."

        Design: Difficulty/combinatorial_formula/invoice_evaluation_order_gold_boundary
        """
        sc = setup_certified(customer_overrides={"opening_ytd_spend_cents": 383746})
        closed = close_work_order(sc.work_order, 3.5)
        assert closed["final_total_cents"] == 116254
        # tier_test = 383746 + 116254 = 500000 exactly -> GOLD (inclusive).
        # discount = round_half_up(116254 x 0.10) = 11625; discounted = 104629;
        # env = max(500, round_half_up(104629 x 0.02) = 2093); invoice = 106722.
        assert closed["invoice_total_cents"] == 106722

    def test_invoice_gold_tier_updates_customer_ytd(self, api):
        """PRD §3.1: "thereafter `ytd_spend_cents` is always the opening value
        plus the sum of `invoice_total_cents` over that customer's `CLOSED` work
        orders."
        PRD §3.8: "The environmental fee is the greater of `env_fee_min_cents`
        (500 by default) and the discounted subtotal multiplied by `env_fee_pct`
        (0.02 by default) rounded half-up to integer cents. The
        `invoice_total_cents` is the discounted subtotal plus the environmental
        fee."

        Design: Difficulty/combinatorial_formula/invoice_evaluation_order_gold_boundary
        """
        sc = setup_certified(customer_overrides={"opening_ytd_spend_cents": 383746})
        closed = close_work_order(sc.work_order, 3.5)
        customer = get_success_data(api.get_customer(sc.customer["id"], ADVISOR))
        # ytd = 383746 + 106722 = 490468.
        assert customer["ytd_spend_cents"] == 490468
        assert closed["invoice_total_cents"] == 106722

    def test_silver_tier_applies_just_below_gold_threshold(self, api):
        """PRD §3.8: "The discount is the subtotal multiplied by the tier's
        percentage — `loyalty_gold_pct` (0.10) for `GOLD`, `loyalty_silver_pct`
        (0.05) for `SILVER`, zero for `NONE` — rounded half-up to integer cents,
        and the discounted subtotal is the subtotal minus the discount."

        Design: Corner/calculations/silver_tier_applies_just_below_gold_threshold
        """
        sc = setup_certified(customer_overrides={"opening_ytd_spend_cents": 383745})
        closed = close_work_order(sc.work_order, 3.5)
        # tier_test = 383745 + 116254 = 499999 -> one cent below GOLD -> SILVER.
        # discount = round_half_up(5812.7) = 5813; discounted = 110441;
        # env = round_half_up(2208.82) = 2209; invoice = 112650.
        assert closed["invoice_total_cents"] == 112650
        customer = get_success_data(api.get_customer(sc.customer["id"], ADVISOR))
        assert customer["ytd_spend_cents"] == 496395
