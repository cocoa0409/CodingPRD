"""Subscription cancellation cascade: boxes, invoices, ledger restore, tasks,
add-ons (PRD 3.5, 3.8)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]


def test_cancel_cascade_voids_invoice_and_restores_credit(api):
    """PRD 3.5: "Cancellation fans out into a full cascade: every shipment box not already in `DELIVERED`, `SKIPPED`, or `CANCELLED` flips to `CANCELLED`; each such box cancellation flips its `ISSUED` invoice to `VOID` and posts a `RESTORE_VOID_INVOICE` ledger entry returning that invoice's `credit_applied_cents` to the customer; every application task not in `APPLIED` or `CANCELLED` flips to `CANCELLED`; and every `QUOTED` or `CONFIRMED` add-on order flips to `CANCELLED`, with the detach compensation for attached confirmed add-ons described in Section 3.9."
    PRD 3.8: "Compensating pairs leave the balance unchanged: an `EARN_REFERRAL` of some amount followed by a `REVOKE_REFERRAL` of its negation restores the prior balance, and a `REDEEM_INVOICE` followed by a `RESTORE_VOID_INVOICE` of the same magnitude does the same."

    Design: Difficulty/transitive_cascade/subscription_cancel_cascade_invoice_void_credit_restore
    """
    ctx = th.setup_active_subscription(
        email="cx@x.com",
        plan_lines=[th.plan_line("FERT-01", qty_units=3, target_month=6)],
        credit_adjust_cents=1000,
    )
    sub_id = ctx["subscription"]["id"]
    # box1: 3 x 800 = 2400 subtotal; credit 1000 redeemed at issue.
    box1 = th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 3)])
    th.advance_box_to(box1["id"], "SHIPPED")
    invoice = th.get_box_invoice(box1["id"])
    assert invoice["subtotal_cents"] == 2400
    assert invoice["credit_applied_cents"] == 1000
    assert invoice["total_cents"] == 1400
    assert th.get_customer_balance(ctx["customer"]["id"]) == 0

    box2 = th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)],
                         ship_date="2026-06-20T00:00:00Z")

    th.validate_success(api.cancel_subscription(sub_id, ctx["customer_headers"]))

    box1_after = th.validate_success(api.get_shipment(box1["id"], ADMIN))
    box2_after = th.validate_success(api.get_shipment(box2["id"], ADMIN))
    assert box1_after["fulfillment_status"] == "CANCELLED"
    assert box2_after["fulfillment_status"] == "CANCELLED"

    # The invoice is voided by the box cancellation, not by the cancel call.
    invoice_after = th.validate_success(api.get_invoice(invoice["id"], ADMIN))
    assert invoice_after["status"] == "VOID"

    restores = th.list_ledger(customer_id=ctx["customer"]["id"],
                              entry_type="RESTORE_VOID_INVOICE")
    assert len(restores) == 1
    assert restores[0]["amount_cents"] == 1000
    # Redeem-then-restore conserves the balance.
    assert th.get_customer_balance(ctx["customer"]["id"]) == 1000


def test_cancel_cascade_covers_tasks_and_add_ons_but_not_delivered_boxes(api):
    """PRD 3.5: "Cancellation fans out into a full cascade: every shipment box not already in `DELIVERED`, `SKIPPED`, or `CANCELLED` flips to `CANCELLED`; each such box cancellation flips its `ISSUED` invoice to `VOID` and posts a `RESTORE_VOID_INVOICE` ledger entry returning that invoice's `credit_applied_cents` to the customer; every application task not in `APPLIED` or `CANCELLED` flips to `CANCELLED`; and every `QUOTED` or `CONFIRMED` add-on order flips to `CANCELLED`, with the detach compensation for attached confirmed add-ons described in Section 3.9."

    Design: Difficulty/transitive_cascade/subscription_cancel_cascade_invoice_void_credit_restore
    """
    ctx = th.setup_active_subscription(email="cx2@x.com",
                                       seed_skus=("FERT-01", "PEST-01"))
    sub_id = ctx["subscription"]["id"]
    # A DELIVERED box with a SCHEDULED task, plus a SCHEDULED box and a
    # QUOTED add-on.
    delivered_box, _ = th.setup_delivered_box(
        ctx, lines=[th.shipment_line("FERT-01", 1)]
    )
    task = th.validate_success(
        api.create_application(
            th.application_payload(sub_id, delivered_box["id"],
                                   product_sku="FERT-01",
                                   scheduled_date="2026-06-10"),
            ctx["customer_headers"],
        ),
        201,
    )
    scheduled_box = th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)],
                                  ship_date="2026-06-20T00:00:00Z")
    add_on = th.quote_add_on(ctx, "PEST-01", qty_units=1)

    th.validate_success(api.cancel_subscription(sub_id, ctx["customer_headers"]))

    assert th.get_box(delivered_box["id"])["fulfillment_status"] == "DELIVERED", (
        "DELIVERED boxes are not touched by the cancel cascade"
    )
    assert th.get_box(scheduled_box["id"])["fulfillment_status"] == "CANCELLED"
    task_after = th.validate_success(api.get_application(task["id"], ADMIN))
    assert task_after["status"] == "CANCELLED"
    add_on_after = th.validate_success(api.get_add_on(add_on["id"], ADMIN))
    assert add_on_after["status"] == "CANCELLED"
