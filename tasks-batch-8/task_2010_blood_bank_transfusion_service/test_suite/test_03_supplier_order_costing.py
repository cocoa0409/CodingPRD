"""Supplier-order estimated cost: per-line rounding order and surcharge."""
from test_helpers import (
    create_supplier_order_payload,
    make_supplier,
    set_clock,
    supplier_order_line,
    validate_success,
    COORDINATOR,
)

CRYO_LINES = [
    {"product_type": "CRYO", "abo_type": "A", "rh_type": "NEG", "quantity": 10},
    {"product_type": "CRYO", "abo_type": "B", "rh_type": "NEG", "quantity": 10},
]


class TestSupplierOrderEstimatedCost:
    def test_supplier_order_cost_per_line_rounding(self, api):
        """PRD §3.2: "The rounding order is pinned: each line's cost — its unit
        price times its quantity times one-minus-the-discount — is rounded half-up
        to whole cents first, the rounded lines are summed into a subtotal, and
        only then, for an emergency order, is a twenty-five percent surcharge
        applied to that subtotal with a single half-up rounding."
        PRD §3.2: "The estimation prices each product at a fixed per-unit rate in
        cents" (CRYO at 6,495) "and grants a volume discount on the whole order:
        ten percent when the lines total at least fifty units, five percent when
        they total at least twenty, and nothing below that."

        Design: Difficulty/combinatorial_formula/supplier_order_cost_per_line_then_total_rounding
        """
        set_clock("2026-08-10T09:00:00Z")
        supplier = make_supplier()
        order = validate_success(api.create_supplier_order(
            create_supplier_order_payload(supplier["id"], CRYO_LINES),
            COORDINATOR), 201)
        # 6,495c x 10 x 0.95 = 61,702.50 -> 61,703 per line (half-up BEFORE
        # summing); two lines -> 123,406c. Sum-first would give 123,405c.
        assert order["estimated_cost_cents"] == 123406, (
            "each line is rounded half-up before the lines are summed"
        )

    def test_supplier_order_emergency_surcharge_single_rounding(self, api):
        """PRD §3.2: "only then, for an emergency order, is a twenty-five percent
        surcharge applied to that subtotal with a single half-up rounding."

        Design: Difficulty/combinatorial_formula/supplier_order_cost_per_line_then_total_rounding
        """
        set_clock("2026-08-10T09:00:00Z")
        supplier = make_supplier()
        normal = validate_success(api.create_supplier_order(
            create_supplier_order_payload(supplier["id"], CRYO_LINES),
            COORDINATOR), 201)
        emergency = validate_success(api.create_supplier_order(
            create_supplier_order_payload(supplier["id"], CRYO_LINES,
                                          is_emergency=True),
            COORDINATOR), 201)
        # Subtotal 123,406 x 1.25 = 154,257.50 -> 154,258c with one rounding.
        assert emergency["estimated_cost_cents"] == 154258, (
            "the 25% surcharge is applied once to the summed subtotal"
        )
        assert normal["estimated_cost_cents"] != emergency["estimated_cost_cents"]
