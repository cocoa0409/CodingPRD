"""Shipment charge: tiered rates, add-on stacking, early-season discount,
floor/ceiling clamps (PRD 3.6)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_shipment_charge_tiered_with_discount_and_addon(api):
    """PRD 3.6: "Each product line contributes its `qty_units` multiplied by the tier rate of that sku for the lawn's size tier — `tier_t1_cents` under 500 square meters, `tier_t2_cents` from 500 up to but under 2,000, `tier_t3_cents` at 2,000 or more. Each attached `CONFIRMED` add-on contributes its `qty_units` multiplied by the sku's `add_on_flat_price_cents`."
    PRD 3.6: "When the planned `ship_date` falls in the early-season window — its month-and-day on or after March 1 and before June 1 — a ten-percent discount applies; otherwise no discount applies. The discounted amount is rounded half up to whole cents, then clamped to a floor of 1,900 cents and a ceiling of 25,000 cents"

    Design: Difficulty/combinatorial_formula/shipment_charge_tiered_with_discount_floor_and_addon
    """
    ctx = th.setup_active_subscription(
        email="sc@x.com",
        lawn_size_sqm=2500,
        grass_type="MIXED",
        plan_lines=[
            th.plan_line("FERT-01", qty_units=5, target_month=4),
            th.plan_line("WEED-01", qty_units=2, target_month=5),
        ],
        seed_skus=("FERT-01", "WEED-01", "PEST-01"),
    )
    box = th.create_box(
        ctx["subscription"]["id"],
        lines=[th.shipment_line("FERT-01", 5), th.shipment_line("WEED-01", 2)],
        ship_date="2026-04-10T00:00:00Z",
    )
    # tier t3 (2500 sqm): 5x600 + 2x900 = 4800; early-season 0.90 -> 4320.
    assert box["provisional_charge_cents"] == 4320, (
        f"expected round_half_up(4800 x 0.90) = 4320, got {box['provisional_charge_cents']}"
    )

    add_on = th.quote_add_on(ctx, "PEST-01", qty_units=1)
    add_on = th.confirm_add_on(ctx, add_on["id"])
    assert add_on["attached_shipment_id"] == box["id"], (
        "the confirmed add-on must attach to the subscription's earliest SCHEDULED box"
    )

    box_after = th.validate_success(api.get_shipment(box["id"], ADMIN))
    # (4800 + 2500) x 0.90 = 6570 — inside [1900, 25000], so no clamp binds.
    assert box_after["provisional_charge_cents"] == 6570, (
        f"expected round_half_up(7300 x 0.90) = 6570, got {box_after['provisional_charge_cents']}"
    )


def test_shipment_charge_floor_and_ceiling_clamps(api):
    """PRD 3.6: "The discounted amount is rounded half up to whole cents, then clamped to a floor of 1,900 cents and a ceiling of 25,000 cents: a discounted amount below the floor charges 1,900 cents, one above the ceiling charges 25,000 cents."

    Design: Difficulty/combinatorial_formula/shipment_charge_tiered_with_discount_floor_and_addon
    """
    ctx = th.setup_active_subscription(
        email="clamp@x.com",
        plan_lines=[
            th.plan_line("FERT-01", qty_units=40, target_month=6),
            th.plan_line("SEED-A", qty_units=1, target_month=6),
        ],
        seed_skus=("FERT-01", "SEED-A"),
    )
    sub_id = ctx["subscription"]["id"]
    # Floor: 1 x 333 (tier t1) = 333 -> clamped up to 1900. No early discount
    # (ship 2026-06-10 is outside [03-01, 06-01)).
    box_low = th.create_box(
        sub_id, lines=[th.shipment_line("SEED-A", 1)],
        ship_date="2026-06-10T00:00:00Z",
    )
    assert box_low["provisional_charge_cents"] == 1900, (
        f"discounted 333 must clamp to the 1900 floor, got {box_low['provisional_charge_cents']}"
    )
    # Ceiling: 40 x 800 = 32000 -> clamped down to 25000.
    box_high = th.create_box(
        sub_id, lines=[th.shipment_line("FERT-01", 40)],
        ship_date="2026-06-20T00:00:00Z",
    )
    assert box_high["provisional_charge_cents"] == 25000, (
        f"discounted 32000 must clamp to the 25000 ceiling, got {box_high['provisional_charge_cents']}"
    )
