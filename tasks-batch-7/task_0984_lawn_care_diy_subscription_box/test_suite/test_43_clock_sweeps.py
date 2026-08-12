"""Logical-clock sweeps: auto-ship box generation (PRD 2.5)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_auto_ship_clock_sweep_generates_seasonal_box(api):
    """PRD 2.5: "First, the auto-ship sweep: each `ACTIVE` subscription whose `auto_ship` flag is true and whose `next_ship_date` is at or before the current logical time generates a `SEASONAL` shipment box built from the lines of that subscription's `ACTIVE` plan, with the box's `ship_date` set to the subscription's `next_ship_date`, a delivery window running from that ship date (inclusive) to seven days later (exclusive), and the subscription's `next_ship_date` then advanced by 90 days."
    PRD 2.5: "The capability's response reports `now_iso8601` (the new logical time), `boxes_generated` (how many boxes the auto-ship sweep created), and `add_ons_expired` (how many quotes the expiry sweep retired)."

    Design: Corner/cross_cutting_layers/auto_ship_clock_sweep_generates_seasonal_box
    """
    ctx = th.setup_active_subscription(
        email="x3@x.com",
        plan_lines=[th.plan_line("FERT-01", qty_units=2, target_month=6)],
        auto_ship=True,
        next_ship_date="2026-06-01T00:00:00Z",
    )
    sub_id = ctx["subscription"]["id"]

    # Crossing next_ship_date (2026-06-01) triggers exactly one box.
    sweep = th.set_clock("2026-06-02T00:00:00Z")
    assert sweep["boxes_generated"] == 1
    assert sweep["now_iso8601"].startswith("2026-06-02")

    boxes = th.list_boxes(subscription_id=sub_id)
    assert len(boxes) == 1
    generated = boxes[0]
    assert generated["box_kind"] == "SEASONAL"
    assert generated["fulfillment_status"] == "SCHEDULED"
    assert generated["ship_date"].startswith("2026-06-01")
    assert generated["delivery_window_start"].startswith("2026-06-01")
    assert generated["delivery_window_end"].startswith("2026-06-08"), (
        "delivery window runs seven days out, exclusive"
    )
    # The generated box mirrors the ACTIVE plan's lines.
    assert generated["lines"] == [{"product_sku": "FERT-01", "qty_units": 2}]

    sub = th.validate_success(api.get_subscription(sub_id, ADMIN))
    assert sub["next_ship_date"].startswith("2026-08-30"), (
        "next_ship_date advanced by 90 days"
    )
