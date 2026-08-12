"""Fulfillment pipeline transitions, invoice payment retry loop, and payment
preconditions (PRD 3.6, 3.8)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]
OPS = th.TEST_USERS["fulfillment_ops_headers"]


def test_fulfillment_step_skip_and_terminal_lockdown(api):
    """PRD 3.6: "Fulfillment advances one step at a time along `SCHEDULED` to `PICKING` to `SHIPPED` to `DELIVERED`, and the requested `to_status` must be the immediate next state — anything else is rejected with `ERR_INVALID_FULFILLMENT_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/fulfillment_step_skip_and_terminal_lockdown
    """
    ctx = th.setup_active_subscription(email="s7@x.com")
    sub_id = ctx["subscription"]["id"]
    box1 = th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)])
    box2 = th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)],
                         ship_date="2026-06-20T00:00:00Z")
    th.advance_box_to(box2["id"], "DELIVERED")

    # Skipping PICKING on a SCHEDULED box is not the immediate next state.
    th.validate_error(
        api.advance_fulfillment(box1["id"], {"to_status": "SHIPPED"}, OPS),
        th.ApiErrorId.ERR_INVALID_FULFILLMENT_TRANSITION,
    )
    # DELIVERED is terminal for the pipeline: no further advance is accepted.
    th.validate_error(
        api.advance_fulfillment(box2["id"], {"to_status": "PICKING"}, OPS),
        th.ApiErrorId.ERR_INVALID_FULFILLMENT_TRANSITION,
    )


def test_invoice_failure_recovery_cycle(api):
    """PRD 3.8: "A `FAILED` outcome moves the invoice to `FAILED`, flips the box's `billing_status` to `FAILED`, and pushes an `ACTIVE` subscription to `PAST_DUE`. A failure recorded against an already `FAILED` invoice leaves the invoice in `FAILED`, the box billing in `FAILED`, and the subscription in `PAST_DUE`, while still incrementing the invoice's `version` by 1; a success against a `FAILED` invoice recovers exactly as a success against an `ISSUED` one, so the retry loop is safe."
    PRD 3.6: "The box's two status fields are parallel dimensions on the same row: `fulfillment_status` evolves through the pipeline above while `billing_status` evolves through invoice events (`PENDING`, `INVOICED`, `PAID`, `FAILED`, `VOID`)."

    Design: Corner/state_machines/invoice_failure_recovery_cycle
    """
    ctx = th.setup_active_subscription(email="s8@x.com")
    sub_id = ctx["subscription"]["id"]
    box = th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)])
    th.advance_box_to(box["id"], "SHIPPED")
    invoice = th.get_box_invoice(box["id"])

    failed = th.validate_success(
        api.record_payment(invoice["id"], {"outcome": "FAILED"}, ADMIN)
    )
    assert failed["status"] == "FAILED"
    sub = th.validate_success(api.get_subscription(sub_id, ADMIN))
    assert sub["status"] == "PAST_DUE"

    box_mid = th.validate_success(api.get_shipment(box["id"], ADMIN))
    assert box_mid["fulfillment_status"] == "SHIPPED", (
        "the fulfillment dimension is untouched by the payment failure"
    )
    assert box_mid["billing_status"] == "FAILED"

    paid = th.validate_success(
        api.record_payment(invoice["id"], {"outcome": "SUCCEEDED"}, ADMIN)
    )
    assert paid["status"] == "PAID"
    sub_after = th.validate_success(api.get_subscription(sub_id, ADMIN))
    assert sub_after["status"] == "ACTIVE", "the retry recovers the subscription"
    box_after = th.validate_success(api.get_shipment(box["id"], ADMIN))
    assert box_after["billing_status"] == "PAID"


def test_record_payment_on_paid_invoice_rejected(api):
    """PRD 3.8: "A PlatformAdmin records payment outcomes against an invoice. The invoice must be `ISSUED` or `FAILED` — anything else is rejected with `ERR_INVOICE_NOT_PAYABLE` (HTTP 409)."

    Design: Corner/validations/record_payment_on_paid_invoice_rejected
    """
    ctx = th.setup_active_subscription(email="v9@x.com")
    box = th.create_box(ctx["subscription"]["id"],
                        lines=[th.shipment_line("FERT-01", 1)])
    th.advance_box_to(box["id"], "SHIPPED")
    invoice = th.get_box_invoice(box["id"])
    th.get_success_data(
        api.record_payment(invoice["id"], {"outcome": "SUCCEEDED"}, ADMIN)
    )

    # PAID is terminal for payment recording.
    th.validate_error(
        api.record_payment(invoice["id"], {"outcome": "SUCCEEDED"}, ADMIN),
        th.ApiErrorId.ERR_INVOICE_NOT_PAYABLE,
    )
