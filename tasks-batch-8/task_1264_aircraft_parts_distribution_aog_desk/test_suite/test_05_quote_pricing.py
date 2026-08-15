"""Quote pricing: per-line rounding, handling-fee brackets, freight formula."""
from test_helpers import (
    validate_success,
    create_customer, create_part, create_aog_request, create_quote,
    make_quote_line, TEST_USERS,
)

AGENT = TEST_USERS["aog_desk_agent_headers"]


def _draft_quote(customer_name, part_number, part_overrides, lines, **quote_kw):
    customer = create_customer(name=customer_name)
    part = create_part(part_number=part_number, **(part_overrides or {}))
    aog = create_aog_request(customer["id"], part["id"])
    return create_quote(aog["id"], customer["id"], lines, **quote_kw)


class TestPerLineRoundingThenSum:
    def test_subtotal_rounds_each_line_before_summing(self, api):
        """PRD §3.4: "Each line's total is the `unit_price_cents` multiplied by
        the line `quantity` and by one minus `discount_pct`, rounded half-up to
        whole cents per line; `subtotal_cents` is then the sum of those
        already-rounded line totals. Rounding each line first and only then
        summing is mandatory — summing unrounded products and rounding once is
        forbidden, because the two orders can differ by at least one cent."

        Two lines of 19995 x 3 x (1 - 0.10): per-line rounding gives
        53987 + 53987 = 107974; sum-then-round would give 107973.

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum
        """
        line = make_quote_line(
            None, quantity=3, sale_type="OUTRIGHT", unit_price_cents=19_995,
            discount_pct=0.10, condition_required="NEW",
        )
        customer = create_customer(name="RoundAir")
        part = create_part(part_number="PN-A", list_price_cents=19_995)
        aog = create_aog_request(customer["id"], part["id"], quantity=6)
        line["part_id"] = part["id"]
        quote = create_quote(aog["id"], customer["id"], [dict(line), dict(line)])
        assert quote["subtotal_cents"] == 107_974

    def test_fees_and_total_built_on_rounded_subtotal(self, api):
        """PRD §3.4: "a subtotal from 100,000 up to and including 1,000,000
        cents draws 4,500"; "Then `tier_fee_cents` is the subtotal plus the
        handling fee, multiplied by the tier percentage — six percent for
        `STANDARD`, three percent for `PRIORITY`, zero percent for `PLATINUM`
        — rounded half-up to whole cents."; "Finally, `total_cents` is the
        subtotal plus the handling fee plus the tier fee — freight is never
        part of the total."

        107974 subtotal -> handling 4500, tier fee round(112474 * 0.06) = 6748,
        total 119222.

        Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum
        """
        line = make_quote_line(
            None, quantity=3, sale_type="OUTRIGHT", unit_price_cents=19_995,
            discount_pct=0.10, condition_required="NEW",
        )
        customer = create_customer(name="RoundAir")
        part = create_part(part_number="PN-A", list_price_cents=19_995)
        aog = create_aog_request(customer["id"], part["id"], quantity=6)
        line["part_id"] = part["id"]
        quote = create_quote(aog["id"], customer["id"], [dict(line), dict(line)])
        assert quote["handling_fee_cents"] == 4_500
        assert quote["tier_fee_cents"] == 6_748
        assert quote["total_cents"] == 119_222


class TestHandlingFeeBracketPreFee:
    def test_bracket_read_on_pre_fee_subtotal(self, api):
        """PRD §3.4: "Next, the small-order handling fee is bracketed on the
        pre-fee subtotal alone: a subtotal strictly below 100,000 cents draws a
        `handling_fee_cents` of 9,500; a subtotal from 100,000 up to and
        including 1,000,000 cents draws 4,500; anything above 1,000,000 draws
        none. The bracket is never evaluated on a post-fee amount."

        Subtotal 99500 is strictly below 100000 even though adding the fee
        would land in the mid bracket.

        Design: Difficulty/combinatorial_formula/handling_fee_bracket_evaluated_pre_fee
        """
        customer = create_customer(name="CircAir")
        part = create_part(part_number="PN-B", list_price_cents=99_500)
        aog = create_aog_request(customer["id"], part["id"],
                                 min_trace_doc="TRACE_MISSING")
        quote = create_quote(
            aog["id"], customer["id"],
            [make_quote_line(part["id"], unit_price_cents=99_500)],
        )
        assert quote["subtotal_cents"] == 99_500
        assert quote["handling_fee_cents"] == 9_500

    def test_tier_fee_and_total_from_pre_fee_bracket(self, api):
        """PRD §3.4: "Then `tier_fee_cents` is the subtotal plus the handling
        fee, multiplied by the tier percentage — six percent for `STANDARD` —
        rounded half-up to whole cents." and "Finally, `total_cents` is the
        subtotal plus the handling fee plus the tier fee".

        99500 + 9500 = 109000; tier fee round(109000 * 0.06) = 6540; total
        115540 (post-fee bracketing would give 110240).

        Design: Difficulty/combinatorial_formula/handling_fee_bracket_evaluated_pre_fee
        """
        customer = create_customer(name="CircAir")
        part = create_part(part_number="PN-B", list_price_cents=99_500)
        aog = create_aog_request(customer["id"], part["id"],
                                 min_trace_doc="TRACE_MISSING")
        quote = create_quote(
            aog["id"], customer["id"],
            [make_quote_line(part["id"], unit_price_cents=99_500)],
        )
        assert quote["tier_fee_cents"] == 6_540
        assert quote["total_cents"] == 115_540


class TestFreightCombinatorial:
    def test_hot_shot_hazmat_escalated_freight(self, api):
        """PRD §3.4: "For `STANDARD` freight the base is the per-kilogram rate
        times the chargeable weight times the distance multiplier, with no
        premium; `HOT_SHOT` adds a flat 250,000-cent premium to the same base"
        and "Base plus premium forms the freight subtotal, which is then
        multiplied by 1.25 when any line's part carries a hazmat class other
        than `NONE`, and multiplied by 1.25 again when the originating request
        has been escalated. The result is rounded half-up to whole cents
        exactly once, at the very end."

        12 kg at 900/kg, 2500 km at 1.35, +250000 premium, then x1.25 x1.25:
        (14580 + 250000) * 1.5625 = 413406.25 -> 413406.

        Design: Difficulty/combinatorial_formula/freight_combinatorial_hot_shot_hazmat_escalated
        """
        customer = create_customer(name="JetSet Cargo")
        part = create_part(part_number="PN-HAZ", hazmat_class="CLASS_3",
                           list_price_cents=75_000, warranty_months=6)
        aog = create_aog_request(customer["id"], part["id"], aircraft_tail="N400JS",
                                 airport_code="MIA")
        validate_success(api.escalate_aog_request(aog["id"], AGENT))
        quote = create_quote(
            aog["id"], customer["id"],
            [make_quote_line(part["id"], unit_price_cents=75_000)],
            freight_mode="HOT_SHOT", distance_km=2_500, chargeable_weight_kg=12,
        )
        assert quote["freight_cost_cents"] == 413_406

    def test_hazmat_without_escalation_drops_one_multiplier(self, api):
        """PRD §3.4: "Base plus premium forms the freight subtotal, which is
        then multiplied by 1.25 when any line's part carries a hazmat class
        other than `NONE`, and multiplied by 1.25 again when the originating
        request has been escalated."

        Same routing without escalation: (900*12*1.35 + 250000) * 1.25 =
        330725 — removing one surcharge changes the result, so the inputs
        interact rather than acting independently.

        Design: Difficulty/combinatorial_formula/freight_combinatorial_hot_shot_hazmat_escalated
        """
        customer = create_customer(name="JetSet Cargo")
        part = create_part(part_number="PN-HAZ", hazmat_class="CLASS_3",
                           list_price_cents=75_000, warranty_months=6)
        aog = create_aog_request(customer["id"], part["id"], aircraft_tail="N400JS",
                                 airport_code="MIA")
        quote = create_quote(
            aog["id"], customer["id"],
            [make_quote_line(part["id"], unit_price_cents=75_000)],
            freight_mode="HOT_SHOT", distance_km=2_500, chargeable_weight_kg=12,
        )
        assert quote["freight_cost_cents"] == 330_725


def test_charter_flat_floor_binds(api):
    """PRD §3.4: "`CHARTER` ignores weight entirely and takes the greater of
    750,000 cents or 2,900 cents per kilometer as its base, again with no
    premium."

    At 100 km the per-km term is 290000, below the 750000 floor; the 500 kg
    chargeable weight is irrelevant in CHARTER mode.

    Design: Corner/calculations/charter_flat_floor_binds
    """
    customer = create_customer(name="FloorAir")
    part = create_part(part_number="PN-CF")
    aog = create_aog_request(customer["id"], part["id"], aircraft_tail="N3CF")
    quote = create_quote(
        aog["id"], customer["id"],
        [make_quote_line(part["id"], unit_price_cents=100_000)],
        freight_mode="CHARTER", distance_km=100, chargeable_weight_kg=500,
    )
    assert quote["freight_cost_cents"] == 750_000
