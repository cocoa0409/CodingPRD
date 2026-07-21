"""Sale checkout/payment dimensions, refund conservation, cross-entity register
gate, and validation-priority conflicts at finalize / add-line."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_approved_vendor, create_product, create_posted_lot,
    create_open_register, open_sale, add_line,
    setup_finalized_paid_sale, setup_building_sale,
    assert_inventory_lot, TEST_USERS,
)

INVENTORY = TEST_USERS["inventory_manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]


class TestPaymentIndependentOfCheckout:
    """payment_status and checkout_status advance independently (PRD §3.5)."""

    def test_pay_building_sale_advances_payment_only(self, api):
        """PRD §3.5: "These two dimensions advance independently — paying and finalizing
        are separate transitions that do not gate one another except where explicitly
        stated." Paying a BUILDING sale sets payment PAID while checkout stays BUILDING.

        Design: Difficulty/non_linear_state_machine/nlsm_sale_parallel_payment_independent_of_checkout
        """
        register = create_open_register()
        sale = open_sale(register["id"])
        paid = validate_success(api.pay_sale(sale["id"], CASHIER), 200)
        assert paid["payment_status"] == "PAID"
        assert paid["checkout_status"] == "BUILDING"

    def test_paid_sale_can_still_finalize(self, api):
        """PRD §3.5: "paying and finalizing are separate transitions that do not gate
        one another". A sale paid while BUILDING still finalizes to FINALIZED, and its
        payment_status remains PAID — the two axes are orthogonal.

        Design: Difficulty/non_linear_state_machine/nlsm_sale_parallel_payment_independent_of_checkout
        """
        ctx = setup_building_sale(register_open=True)
        add_line(ctx["sale"]["id"], ctx["product"]["id"], ctx["lot"]["id"], quantity=1)
        api.pay_sale(ctx["sale"]["id"], CASHIER)
        finalized = validate_success(api.finalize_sale(ctx["sale"]["id"], CASHIER), 200)
        assert finalized["checkout_status"] == "FINALIZED"
        assert finalized["payment_status"] == "PAID"


class TestInventoryConservedOnRefund:
    """Refund reverses the finalize movements exactly (PRD §2.7, §3.5)."""

    def test_refund_restocks_lot_units(self, api):
        """PRD §3.5: "A refund reverses the finalize movements exactly: for each line the
        lot's `qty_sold` is decreased and its `qty_on_hand` increased by the line's
        `units`".

        Design: Difficulty/compensating_invariant/ci_inventory_units_conserved_on_sale_refund
        """
        sale, lot = setup_finalized_paid_sale(received_qty=10, quantity=3)
        assert lot["qty_on_hand"] == 7 and lot["qty_sold"] == 3
        validate_success(api.refund_sale(sale["id"], CASHIER), 200)
        lot_after = validate_success(api.get_inventory_lot(lot["id"], INVENTORY), 200)
        assert lot_after["qty_on_hand"] == 10
        assert lot_after["qty_sold"] == 0

    def test_refund_preserves_unit_conservation_invariant(self, api):
        """PRD §2.7: "For every posted inventory lot, the received quantity equals the
        sum of the units still on hand, the units sold, and the units shrunk."

        Design: Difficulty/compensating_invariant/ci_inventory_units_conserved_on_sale_refund
        """
        sale, lot = setup_finalized_paid_sale(received_qty=10, quantity=3)
        validate_success(api.refund_sale(sale["id"], CASHIER), 200)
        lot_after = validate_success(api.get_inventory_lot(lot["id"], INVENTORY), 200)
        assert lot_after["received_qty"] == 10
        assert lot_after["qty_shrunk"] == 0
        assert_inventory_lot(lot_after)


class TestFinalizeRequiresRegisterOpen:
    """A sale cannot finalize while its register is CLOSED (PRD §3.5)."""

    def _built_sale(self, api):
        vendor = create_approved_vendor()
        product = create_product(vendor["id"], sku="APL", name="Apples",
                                 department="PRODUCE", base_price_cents=150,
                                 reorder_point=0, reorder_qty=10)
        lot = create_posted_lot(product["id"], vendor["id"], received_qty=10, unit_cost_cents=80)
        register = create_open_register()
        sale = open_sale(register["id"])
        add_line(sale["id"], product["id"], lot["id"], quantity=1)
        return register, sale

    def test_finalize_with_closed_register_rejected(self, api):
        """PRD §3.5: "the sale's register must be `OPEN` (else `ERR_REGISTER_CLOSED`)".

        Design: Difficulty/cross_entity_state_dependency/cesd_sale_finalize_requires_register_open
        """
        register, sale = self._built_sale(api)
        api.set_register_open(register["id"], {"is_open": False}, CASHIER)
        res = api.finalize_sale(sale["id"], CASHIER)
        validate_error(res, "ERR_REGISTER_CLOSED", expected_status=409)

    def test_finalize_with_open_register_succeeds(self, api):
        """PRD §3.5: "Finalizing a sale is a `Cashier` action moving `checkout_status`
        from `BUILDING` to `FINALIZED`." With the register OPEN the same in-stock sale
        finalizes, confirming register state is the gate.

        Design: Difficulty/cross_entity_state_dependency/cesd_sale_finalize_requires_register_open
        """
        _register, sale = self._built_sale(api)
        finalized = validate_success(api.finalize_sale(sale["id"], CASHIER), 200)
        assert finalized["checkout_status"] == "FINALIZED"


class TestStateBeatsFiscalOnFinalize:
    """Priority: state (register closed) outranks fiscal (insufficient inv) (PRD §2.9)."""

    def test_register_closed_reported_over_insufficient_inventory(self, api):
        """PRD §2.9: "(4) the target resource and any gating resource are in the correct
        state for the transition, else the applicable state error".
        PRD §2.9: "and finally (9) fiscal scarcity — sufficient inventory, sufficient
        equity, and a present declared rate."
        A finalize violating both returns the state error ERR_REGISTER_CLOSED.

        Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_fiscal_on_finalize
        """
        vendor = create_approved_vendor()
        product = create_product(vendor["id"], sku="NUTS", name="Cashews",
                                 department="BULK", base_price_cents=400,
                                 reorder_point=0, reorder_qty=10)
        lot = create_posted_lot(product["id"], vendor["id"], received_qty=3, unit_cost_cents=200)
        register = create_open_register()
        sale = open_sale(register["id"])
        add_line(sale["id"], product["id"], lot["id"], quantity=5)  # exceeds on-hand 3
        api.set_register_open(register["id"], {"is_open": False}, CASHIER)
        res = api.finalize_sale(sale["id"], CASHIER)
        validate_error(res, "ERR_REGISTER_CLOSED", expected_status=409)

    def test_insufficient_inventory_fires_when_register_open(self, api):
        """PRD §3.5: "for every line the referenced lot's `qty_on_hand` must be at least
        the line's `units` (else `ERR_INSUFFICIENT_INVENTORY`)." With the state gate
        satisfied (register OPEN), the fiscal-scarcity leg surfaces.

        Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_fiscal_on_finalize
        """
        vendor = create_approved_vendor()
        product = create_product(vendor["id"], sku="NUTS2", name="Cashews",
                                 department="BULK", base_price_cents=400,
                                 reorder_point=0, reorder_qty=10)
        lot = create_posted_lot(product["id"], vendor["id"], received_qty=3, unit_cost_cents=200)
        register = create_open_register()
        sale = open_sale(register["id"])
        add_line(sale["id"], product["id"], lot["id"], quantity=5)
        res = api.finalize_sale(sale["id"], CASHIER)
        validate_error(res, "ERR_INSUFFICIENT_INVENTORY", expected_status=422)


class TestSafetyBeatsReferentialOnAddLine:
    """Priority: safety (recalled) outranks referential (lot mismatch) (PRD §2.9)."""

    def _recalled_p1_and_p2_lot(self, api):
        vendor = create_approved_vendor()
        p1 = create_product(vendor["id"], sku="P1", name="Spinach", department="PRODUCE",
                            base_price_cents=300, reorder_point=0, reorder_qty=10)
        p2 = create_product(vendor["id"], sku="P2", name="Kale", department="PRODUCE",
                            base_price_cents=300, reorder_point=0, reorder_qty=10)
        l2 = create_posted_lot(p2["id"], vendor["id"], received_qty=10, unit_cost_cents=100)
        register = create_open_register()
        sale = open_sale(register["id"])
        return p1, p2, l2, sale

    def test_recalled_product_reported_over_lot_mismatch(self, api):
        """PRD §2.9: "(5) business-safety — no line references a recalled product".
        PRD §2.9: "(7) business-referential integrity — an approved vendor, a matching
        lot-and-product, an eligible voter".
        A line whose product is RECALLED and whose lot belongs to another product
        returns the safety error ERR_PRODUCT_RECALLED.

        Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_beats_referential_on_add_line
        """
        p1, _p2, l2, sale = self._recalled_p1_and_p2_lot(api)
        api.update_product(p1["id"], {"status": "RECALLED"}, INVENTORY)
        res = api.add_sale_line(sale["id"],
                                {"product_id": p1["id"], "inventory_lot_id": l2["id"],
                                 "quantity": 1}, CASHIER)
        validate_error(res, "ERR_PRODUCT_RECALLED", expected_status=422)

    def test_lot_product_mismatch_fires_when_product_active(self, api):
        """PRD §3.5: "The referenced `inventory_lot_id` must belong to the same product
        named by `product_id`, else `ERR_LOT_PRODUCT_MISMATCH`." With the safety leg
        satisfied (product ACTIVE), the referential leg surfaces.

        Design: Difficulty/priority_pair_validation_conflict/ppvc_safety_beats_referential_on_add_line
        """
        p1, _p2, l2, sale = self._recalled_p1_and_p2_lot(api)
        res = api.add_sale_line(sale["id"],
                                {"product_id": p1["id"], "inventory_lot_id": l2["id"],
                                 "quantity": 1}, CASHIER)
        validate_error(res, "ERR_LOT_PRODUCT_MISMATCH", expected_status=409)


def test_finalize_already_finalized_sale_rejected(api):
    """PRD §3.5: "the sale must be `BUILDING` (else `ERR_SALE_NOT_BUILDING`)". A second
    finalize on an already-FINALIZED sale is refused.

    Design: Corner/state_machines/finalize_already_finalized_rejected
    """
    ctx = setup_building_sale(register_open=True)
    add_line(ctx["sale"]["id"], ctx["product"]["id"], ctx["lot"]["id"], quantity=1)
    validate_success(api.finalize_sale(ctx["sale"]["id"], CASHIER), 200)
    res = api.finalize_sale(ctx["sale"]["id"], CASHIER)
    validate_error(res, "ERR_SALE_NOT_BUILDING", expected_status=409)
