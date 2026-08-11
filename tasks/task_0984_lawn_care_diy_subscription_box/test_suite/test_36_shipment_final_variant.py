"""Shipment charge variants: provisional (ship_date) vs final (delivered_at)
diverge when delivery crosses the early-season boundary (PRD 3.6)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_shipment_final_variant_diverges_at_delivery(api):
    """PRD 3.6: "Reaching `DELIVERED` stamps `delivered_at` from the logical clock and computes `final_charge_cents` — the same charge formula run again, except that the early-season test uses the actual `delivered_at` instead of the planned `ship_date`, and the lawn's size tier is re-read at delivery. A box planned inside the early window but delivered outside it — or the reverse — therefore yields a final charge different from its provisional charge for identical lines."

    Design: Corner/calculations/shipment_final_variant_diverges_at_delivery
    """
    ctx = th.setup_active_subscription(
        email="fv@x.com",
        plan_lines=[th.plan_line("FERT-01", qty_units=5, target_month=5)],
    )
    # ship_date 2026-05-20 is inside [03-01, 06-01): provisional gets 10% off.
    box = th.create_box(
        ctx["subscription"]["id"],
        lines=[th.shipment_line("FERT-01", 5)],
        ship_date="2026-05-20T00:00:00Z",
    )
    assert box["provisional_charge_cents"] == 3600, (
        f"round_half_up(4000 x 0.90) = 3600, got {box['provisional_charge_cents']}"
    )

    th.advance_box_to(box["id"], "SHIPPED")
    # Delivered at 2026-06-05: outside the early window, so no discount.
    delivered = th.deliver_box(box["id"], at_clock="2026-06-05T00:00:00Z")
    assert delivered["final_charge_cents"] == 4000, (
        f"final variant uses delivered_at: 5 x 800 = 4000, got {delivered['final_charge_cents']}"
    )
    assert delivered["provisional_charge_cents"] != delivered["final_charge_cents"]

    fetched = th.validate_success(api.get_shipment(box["id"], ADMIN))
    assert fetched["final_charge_cents"] == 4000
    # delivered_at is stamped from the logical clock (2026-06-05).
    assert fetched["delivered_at"].startswith("2026-06-05")
    assert th.is_iso8601_timestamp(fetched["delivered_at"])
