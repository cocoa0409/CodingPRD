"""Invoice credit auto-redemption capped at the customer's balance (PRD 3.8)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_credit_redeem_capped_at_balance(api):
    """PRD 3.8: "At issue, the customer's available credit is auto-redeemed: `credit_applied_cents` is the smaller of the customer's `credit_balance_cents` at that moment and the `subtotal_cents`, and `total_cents` is the subtotal minus the applied credit. When the applied credit is greater than zero, the redemption is posted as a `REDEEM_INVOICE` ledger entry against the customer."
    PRD 3.8: "The balance never goes negative, because redemption at invoice issue is capped by the minimum rule above."

    Design: Corner/calculations/credit_redeem_capped_at_balance
    """
    ctx = th.setup_active_subscription(
        email="cap@x.com",
        plan_lines=[th.plan_line("FERT-01", qty_units=3, target_month=6)],
        credit_adjust_cents=500,
    )
    assert th.get_customer_balance(ctx["customer"]["id"]) == 500

    # 3 x 800 = 2400 subtotal (ship 2026-06-10, outside the early window).
    box = th.create_box(ctx["subscription"]["id"],
                        lines=[th.shipment_line("FERT-01", 3)],
                        ship_date="2026-06-10T00:00:00Z")
    th.advance_box_to(box["id"], "SHIPPED")
    invoice = th.get_box_invoice(box["id"])

    assert invoice["subtotal_cents"] == 2400
    assert invoice["credit_applied_cents"] == 500, "min(balance 500, subtotal 2400)"
    assert invoice["total_cents"] == 1900

    redeems = th.list_ledger(customer_id=ctx["customer"]["id"],
                             entry_type="REDEEM_INVOICE")
    assert len(redeems) == 1
    assert redeems[0]["amount_cents"] == -500
    assert redeems[0]["reference_id"] == invoice["id"]
    # The balance drains to exactly zero, never negative.
    assert th.get_customer_balance(ctx["customer"]["id"]) == 0
