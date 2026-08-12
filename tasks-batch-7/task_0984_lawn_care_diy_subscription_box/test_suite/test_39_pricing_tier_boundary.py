"""Shipment pricing tier boundary: 500 sqm belongs to tier t2 (PRD 3.1, 3.6)."""
import test_helpers as th


def test_pricing_tier_boundary_exactly_500sqm(api):
    """PRD 3.1: "Because shipment pricing scales with lawn size, each product also carries three per-unit tier rates: `tier_t1_cents` for lawns under 500 square meters, `tier_t2_cents` for lawns of at least 500 but under 2,000 square meters, and `tier_t3_cents` for lawns of 2,000 square meters or more."
    PRD 3.6: "Each product line contributes its `qty_units` multiplied by the tier rate of that sku for the lawn's size tier — `tier_t1_cents` under 500 square meters, `tier_t2_cents` from 500 up to but under 2,000, `tier_t3_cents` at 2,000 or more."

    Design: Corner/calculations/pricing_tier_boundary_exactly_500sqm
    """
    ctx = th.setup_active_subscription(
        email="tier@x.com",
        lawn_size_sqm=500,
        plan_lines=[th.plan_line("FERT-01", qty_units=10, target_month=6)],
    )
    # Exactly 500 sqm is "at least 500 but under 2,000": the t2 rate applies.
    box = th.create_box(
        ctx["subscription"]["id"],
        lines=[th.shipment_line("FERT-01", 10)],
        ship_date="2026-06-10T00:00:00Z",
    )
    assert box["provisional_charge_cents"] == 7000, (
        f"10 x t2 700 = 7000 (t1's 800 must not apply at 500 sqm), got {box['provisional_charge_cents']}"
    )
