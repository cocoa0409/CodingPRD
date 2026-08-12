"""Invoice totals: pinned per-line rounding order (PRD 3.8)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def _setup_seeded_invoice(api):
    """100 sqm lawn (tier t1); box with SEED-A x1 + SEED-B x1 shipped on
    2026-04-10 (early-season window, 10% per-line discount)."""
    ctx = th.setup_active_subscription(
        email="inv@x.com",
        plan_lines=[
            th.plan_line("SEED-A", qty_units=1, target_month=4),
            th.plan_line("SEED-B", qty_units=1, target_month=4),
        ],
        seed_skus=("SEED-A", "SEED-B"),
    )
    box = th.create_box(
        ctx["subscription"]["id"],
        lines=[th.shipment_line("SEED-A", 1), th.shipment_line("SEED-B", 1)],
        ship_date="2026-04-10T00:00:00Z",
    )
    th.advance_box_to(box["id"], "SHIPPED")
    invoice = th.get_box_invoice(box["id"])
    return ctx, box, invoice


def test_invoice_total_per_line_rounding_order(api):
    """PRD 3.8: "The rounding order on invoice lines is pinned: each line's total is computed as `qty_units` multiplied by `unit_price_cents` multiplied by one minus `line_discount_pct`, rounded half up to whole cents, and only then are the rounded line totals summed into `subtotal_cents`."
    PRD 3.8: "The alternative order — summing exact values and rounding once at the end — yields different cents and is non-conformant."

    Design: Difficulty/combinatorial_formula/invoice_total_per_line_rounding_order
    """
    _, _, invoice = _setup_seeded_invoice(api)
    # Per line: round_half_up(333 x 0.90) = 300; round_half_up(555 x 0.90) = 500.
    # Pinned order sums to 800; sum-then-round would yield 799.
    assert invoice["subtotal_cents"] == 800, (
        f"per-line rounding then sum must give 800, got {invoice['subtotal_cents']}"
    )
    assert invoice["credit_applied_cents"] == 0
    assert invoice["total_cents"] == 800


def test_invoice_line_items_carry_unit_price_discount_and_line_total(api):
    """PRD 3.8: "The invoice's `line_items` array is built from the box's product lines plus every attached `CONFIRMED` add-on, one invoice line each, with `product_sku`, `qty_units`, `unit_price_cents`, `line_discount_pct`, and `line_total_cents` on every line."
    PRD 3.8: "The unit price is the sku's tier rate for the lawn's tier on product lines, or the sku's `add_on_flat_price_cents` on add-on lines. The line discount is ten percent when the box's `ship_date` falls in the early-season window — month-and-day on or after March 1 and before June 1 — and zero otherwise."

    Design: Difficulty/combinatorial_formula/invoice_total_per_line_rounding_order
    """
    _, _, invoice = _setup_seeded_invoice(api)
    lines = {line["product_sku"]: line for line in invoice["line_items"]}
    assert set(lines) == {"SEED-A", "SEED-B"}
    line_a = lines["SEED-A"]
    assert line_a["qty_units"] == 1
    assert line_a["unit_price_cents"] == 333
    assert line_a["line_discount_pct"] == 0.10
    assert line_a["line_total_cents"] == 300
    line_b = lines["SEED-B"]
    assert line_b["unit_price_cents"] == 555
    assert line_b["line_discount_pct"] == 0.10
    assert line_b["line_total_cents"] == 500
