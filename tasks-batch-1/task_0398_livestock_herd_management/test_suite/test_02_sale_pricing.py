"""Weight-ticket and sale-lot pricing: tier selection, shrink, commission, rounding order."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_herd,
    create_weighed_animal,
    create_sale_lot,
    add_ticket,
    setup_lot_with_one_ticket,
    ApiErrorId,
    TEST_USERS,
)

CLERK = TEST_USERS["sale_clerk_headers"]


class TestAuctionVsPrivateTreaty:
    def test_auction_lot_charges_commission(self, api):
        """PRD §3.10: "The `commission_amount` is that gross sale amount multiplied
        by the lot's `commission_pct`, rounded to two decimal places, and applied once
        at the lot level rather than per ticket. The `net_proceeds` is the gross sale
        amount minus the commission amount, rounded to two decimal places."

        Design: Difficulty/dual_variant_calc/sale_pricing_auction_vs_private_treaty
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_weighed_animal(herd["id"], 500.0, weighed_at="2026-03-15",
                                       birth_date="2024-01-01")
        lot, _ = setup_lot_with_one_ticket(
            herd["id"], animal["id"], 500.0,
            channel="AUCTION", pencil_shrink_pct=0, commission_pct=0.04,
        )
        sold = validate_success(api.sell_lot(lot["id"], CLERK))
        assert sold["gross_sale_amount"] == 2200.00
        assert sold["commission_amount"] == 88.00
        assert sold["net_proceeds"] == 2112.00

    def test_private_treaty_net_equals_gross(self, api):
        """PRD §3.10: "for a private-treaty lot, where the commission percentage was
        forced to zero, the net proceeds equal the gross sale amount."

        Design: Difficulty/dual_variant_calc/sale_pricing_auction_vs_private_treaty
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_weighed_animal(herd["id"], 500.0, weighed_at="2026-03-15",
                                       birth_date="2024-01-01")
        lot, _ = setup_lot_with_one_ticket(
            herd["id"], animal["id"], 500.0,
            channel="PRIVATE_TREATY", pencil_shrink_pct=0, commission_pct=0,
        )
        sold = validate_success(api.sell_lot(lot["id"], CLERK))
        assert sold["commission_amount"] == 0.00
        assert sold["net_proceeds"] == 2200.00


class TestTicketPricingFormula:
    def test_heavy_tier_with_shrink_gross_line(self, api):
        """PRD §3.9: "At ticket creation, the ticket's `net_weight_kg` is the
        `gross_weight_kg` multiplied by one minus the lot's `pencil_shrink_pct`,
        rounded to three decimal places."
        PRD §3.9: "a net weight of 400 kilograms or more is the heavy class priced
        at 440.00 per 100 kilograms."
        PRD §3.9: "The ticket's `gross_line_amount` is its `net_weight_kg` divided by
        100 and multiplied by `price_per_100kg`, rounded to two decimal places."

        Design: Difficulty/combinatorial_formula/ticket_pricing_tier_shrink_commission_mode_a
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_weighed_animal(herd["id"], 460.0, weighed_at="2026-03-20",
                                       birth_date="2024-06-01", birth_weight_kg=45.0)
        lot = create_sale_lot(herd["id"], channel="AUCTION",
                              pencil_shrink_pct=0.03, commission_pct=0.05)
        ticket = add_ticket(lot["id"], animal["id"], 460.0, lot["version"])
        assert ticket["net_weight_kg"] == 446.2
        assert ticket["price_per_100kg"] == 440.00
        assert ticket["gross_line_amount"] == 1963.28

    def test_medium_tier_selected_at_shrunk_net_weight(self, api):
        """PRD §3.9: "a net weight of at least 250 but below 400 kilograms is the
        medium class priced at 480.00 per 100 kilograms."

        Design: Difficulty/combinatorial_formula/ticket_pricing_tier_shrink_commission_mode_a
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        animal = create_weighed_animal(herd["id"], 270.0, weighed_at="2026-03-20",
                                       birth_date="2024-06-01")
        lot = create_sale_lot(herd["id"], channel="PRIVATE_TREATY",
                              pencil_shrink_pct=0.03, commission_pct=0)
        ticket = add_ticket(lot["id"], animal["id"], 261.0, lot["version"])
        assert ticket["net_weight_kg"] == 253.17
        assert ticket["price_per_100kg"] == 480.00
        assert ticket["gross_line_amount"] == 1215.22


class TestLotRoundingOrder:
    def test_lot_sums_already_rounded_per_ticket_amounts(self, api):
        """PRD §3.10: "The lot totals are computed at the moment of sale, and the
        rounding order is pinned to sum-then-commission. The lot's `gross_sale_amount`
        is the sum of the already-rounded per-ticket `gross_line_amount` values, itself
        rounded to two decimal places."

        Design: Difficulty/combinatorial_formula/lot_total_rounding_order_mode_b
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        a1 = create_weighed_animal(herd["id"], 270.0, weighed_at="2026-03-20",
                                   birth_date="2024-06-01")
        a2 = create_weighed_animal(herd["id"], 270.0, weighed_at="2026-03-20",
                                   birth_date="2024-06-01")
        lot = create_sale_lot(herd["id"], channel="PRIVATE_TREATY",
                              pencil_shrink_pct=0.03, commission_pct=0)
        tk1 = add_ticket(lot["id"], a1["id"], 261.0, lot["version"])
        lot_v1 = validate_success(api.get_sale_lot(lot["id"], CLERK))["version"]
        tk2 = add_ticket(lot["id"], a2["id"], 261.0, lot_v1)
        assert tk1["gross_line_amount"] == 1215.22
        assert tk2["gross_line_amount"] == 1215.22

        sold = validate_success(api.sell_lot(lot["id"], CLERK))
        assert sold["gross_sale_amount"] == 2430.44, (
            f"per-ticket-round-then-sum gives 2430.44, got {sold['gross_sale_amount']}"
        )

    def test_lot_gross_sum_then_round_two_decimals(self, api):
        """PRD §3.10: "The lot's `gross_sale_amount` is the sum of the already-rounded
        per-ticket `gross_line_amount` values, itself rounded to two decimal places."

        Design: Difficulty/combinatorial_formula/lot_total_rounding_order_mode_b
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        a1 = create_weighed_animal(herd["id"], 270.0, weighed_at="2026-03-20",
                                   birth_date="2024-06-01")
        a2 = create_weighed_animal(herd["id"], 270.0, weighed_at="2026-03-20",
                                   birth_date="2024-06-01")
        lot = create_sale_lot(herd["id"], channel="PRIVATE_TREATY",
                              pencil_shrink_pct=0.03, commission_pct=0)
        add_ticket(lot["id"], a1["id"], 261.0, lot["version"])
        lot_v1 = validate_success(api.get_sale_lot(lot["id"], CLERK))["version"]
        add_ticket(lot["id"], a2["id"], 261.0, lot_v1)
        sold = validate_success(api.sell_lot(lot["id"], CLERK))
        assert sold["gross_sale_amount"] == 2430.44


class TestCommissionValidation:
    def test_private_treaty_with_commission_rejected(self, api):
        """PRD §3.9: "A private-treaty sale takes no commission: if the `channel` is
        `PRIVATE_TREATY` and a non-zero `commission_pct` is supplied, the lot creation
        is rejected with `ERR_COMMISSION_NOT_ALLOWED`."

        Design: Corner/validations/private_treaty_with_commission_returns_422
        """
        set_clock("2026-04-01T00:00:00Z")
        herd = create_herd(species="CATTLE")
        resp = api.create_sale_lot(
            {"herd_id": herd["id"], "channel": "PRIVATE_TREATY",
             "pencil_shrink_pct": 0, "commission_pct": 0.05},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_COMMISSION_NOT_ALLOWED.value)
