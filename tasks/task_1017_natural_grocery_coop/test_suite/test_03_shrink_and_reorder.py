"""Shrink FIFO write-off vs weighted-average valuation, and the reorder-flag
boundary reached via sale finalize."""
import pytest
from test_helpers import (
    api_client, validate_success,
    create_approved_vendor, create_product, create_posted_lot,
    create_open_register, open_sale, add_line,
    setup_two_lot_product_for_shrink, TEST_USERS,
)

INVENTORY = TEST_USERS["inventory_manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]


class TestShrinkFifoWriteoff:
    """A 12-unit shrink across lots 10@100 then 10@200 (PRD §3.3)."""

    def test_fifo_writeoff_cost_and_lot_depletion(self, api):
        """PRD §3.3: "The write-off consumes on-hand units from the product's posted
        lots oldest first — first-in, first-out, ordered by lot `created_at` ascending,
        never by identifier." PRD §3.3: "The accumulated cost becomes the product's
        `last_shrink_cost_cents`."

        Design: Difficulty/dual_variant_calc/dvc_shrink_fifo_vs_weighted_average_on_lot
        """
        p_id, lot_a, lot_b = setup_two_lot_product_for_shrink()
        product = validate_success(api.shrink_product(p_id, {"quantity": 12}, INVENTORY), 200)
        assert product["last_shrink_cost_cents"] == 1400

        lot_a_after = validate_success(api.get_inventory_lot(lot_a, INVENTORY), 200)
        lot_b_after = validate_success(api.get_inventory_lot(lot_b, INVENTORY), 200)
        assert lot_a_after["qty_on_hand"] == 0
        assert lot_a_after["qty_shrunk"] == 10
        assert lot_b_after["qty_on_hand"] == 8
        assert lot_b_after["qty_shrunk"] == 2

    def test_inventory_value_uses_weighted_average_basis(self, api):
        """PRD §3.3: "The reported `inventory_value_cents` metric, by contrast, is a
        weighted-average reference: it values on-hand units at the pooled cost across
        posted lots." After the shrink only 8 units of the 200-cost lot remain (1600).

        Design: Difficulty/dual_variant_calc/dvc_shrink_fifo_vs_weighted_average_on_lot
        """
        p_id, _lot_a, _lot_b = setup_two_lot_product_for_shrink()
        product = validate_success(api.shrink_product(p_id, {"quantity": 12}, INVENTORY), 200)
        assert product["inventory_value_cents"] == 1600


class TestReorderCascadeOnFinalize:
    """Sale finalize depletes a lot and flips needs_reorder at the reorder point."""

    def test_finalize_depletes_lot_and_recomputes_product_total(self, api):
        """PRD §3.5: "On finalize, for each line the lot's `qty_sold` is increased and
        its `qty_on_hand` decreased by the line's `units`, and every affected product's
        `qty_on_hand_total`, `needs_reorder`, and `inventory_value_cents` are recomputed
        as the reorder cascade propagates from lot depletion."

        Design: Difficulty/transitive_cascade/tc_sale_finalize_depletes_lot_flags_reorder
        """
        vendor = create_approved_vendor()
        product = create_product(vendor["id"], sku="RICE", name="Brown Rice",
                                 department="BULK", base_price_cents=400,
                                 reorder_point=8, reorder_qty=20)
        lot = create_posted_lot(product["id"], vendor["id"], received_qty=10, unit_cost_cents=200)
        register = create_open_register()
        sale = open_sale(register["id"])
        add_line(sale["id"], product["id"], lot["id"], quantity=2)
        validate_success(api.finalize_sale(sale["id"], CASHIER), 200)

        lot_after = validate_success(api.get_inventory_lot(lot["id"], INVENTORY), 200)
        product_after = validate_success(api.get_product(product["id"], INVENTORY), 200)
        assert lot_after["qty_on_hand"] == 8
        assert product_after["qty_on_hand_total"] == 8

    def test_needs_reorder_flips_true_when_total_reaches_point(self, api):
        """PRD §3.2: "`needs_reorder` is true precisely when that total is at or below
        the product's `reorder_point` — the boundary flags at the point itself, not
        only below it."

        Design: Difficulty/transitive_cascade/tc_sale_finalize_depletes_lot_flags_reorder
        """
        vendor = create_approved_vendor()
        product = create_product(vendor["id"], sku="RICE2", name="Brown Rice",
                                 department="BULK", base_price_cents=400,
                                 reorder_point=8, reorder_qty=20)
        lot = create_posted_lot(product["id"], vendor["id"], received_qty=10, unit_cost_cents=200)
        register = create_open_register()
        sale = open_sale(register["id"])
        add_line(sale["id"], product["id"], lot["id"], quantity=2)
        validate_success(api.finalize_sale(sale["id"], CASHIER), 200)

        product_after = validate_success(api.get_product(product["id"], INVENTORY), 200)
        assert product_after["needs_reorder"] is True


class TestReorderPointBoundary:
    """Boundary precision on the reorder flag: <= flags at the point (PRD §3.2)."""

    def _sell(self, api, reorder_point, received_qty, quantity):
        vendor = create_approved_vendor()
        product = create_product(vendor["id"], sku="BEAN", name="Black Beans",
                                 department="BULK", base_price_cents=250,
                                 reorder_point=reorder_point, reorder_qty=20)
        lot = create_posted_lot(product["id"], vendor["id"], received_qty=received_qty,
                                unit_cost_cents=100)
        register = create_open_register()
        sale = open_sale(register["id"])
        add_line(sale["id"], product["id"], lot["id"], quantity=quantity)
        validate_success(api.finalize_sale(sale["id"], CASHIER), 200)
        return validate_success(api.get_product(product["id"], INVENTORY), 200)

    def test_exactly_at_reorder_point_flags(self, api):
        """PRD §3.2: "`needs_reorder` is true precisely when that total is at or below
        the product's `reorder_point` — the boundary flags at the point itself, not
        only below it." At on_hand 8 == reorder_point 8 the flag is set.

        Design: Difficulty/boundary_precision_check/bpc_reorder_point_at_threshold_via_finalize
        """
        product = self._sell(api, reorder_point=8, received_qty=10, quantity=2)
        assert product["qty_on_hand_total"] == 8
        assert product["needs_reorder"] is True

    def test_one_above_reorder_point_does_not_flag(self, api):
        """PRD §3.2: "`needs_reorder` is true precisely when that total is at or below
        the product's `reorder_point` — the boundary flags at the point itself, not
        only below it." At on_hand 9 > reorder_point 8 the flag stays false.

        Design: Difficulty/boundary_precision_check/bpc_reorder_point_at_threshold_via_finalize
        """
        product = self._sell(api, reorder_point=8, received_qty=10, quantity=1)
        assert product["qty_on_hand_total"] == 9
        assert product["needs_reorder"] is False
