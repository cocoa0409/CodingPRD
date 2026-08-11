"""Cross-entity gate: PAST_DUE subscription blocks fulfillment advance
(PRD 3.5, 3.6, 3.8)."""
import test_helpers as th

ADMIN = th.TEST_USERS["platform_admin_headers"]
OPS = th.TEST_USERS["fulfillment_ops_headers"]


def _setup_past_due(api, email="pd@x.com"):
    """ACTIVE subscription; box1 SHIPPED with invoice ISSUED; box2 SCHEDULED;
    then a FAILED payment pushes the subscription to PAST_DUE."""
    ctx = th.setup_active_subscription(email=email)
    sub_id = ctx["subscription"]["id"]
    box1 = th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)])
    th.advance_box_to(box1["id"], "SHIPPED")
    invoice = th.get_box_invoice(box1["id"])
    box2 = th.create_box(sub_id, lines=[th.shipment_line("FERT-01", 1)],
                         ship_date="2026-06-20T00:00:00Z")
    th.get_success_data(
        api.record_payment(invoice["id"], {"outcome": "FAILED"}, ADMIN)
    )
    return ctx, box1, box2, invoice


def test_shipment_advance_blocked_when_subscription_past_due(api):
    """PRD 3.5: "When a payment failure lands on one of the subscription's invoices, an `ACTIVE` subscription moves to `PAST_DUE`; unlike a pause, boxes are not held — instead, any attempt to advance fulfillment on the subscription's boxes is rejected with `ERR_SUBSCRIPTION_NOT_ACTIVE`."
    PRD 3.8: "A `FAILED` outcome moves the invoice to `FAILED`, flips the box's `billing_status` to `FAILED`, and pushes an `ACTIVE` subscription to `PAST_DUE`."

    Design: Difficulty/cross_entity_state_dependency/shipment_advance_blocked_when_subscription_past_due
    """
    ctx, _, box2, _ = _setup_past_due(api)

    sub = th.validate_success(api.get_subscription(ctx["subscription"]["id"], ADMIN))
    assert sub["status"] == "PAST_DUE"

    th.validate_error(
        api.advance_fulfillment(box2["id"], {"to_status": "PICKING"}, OPS),
        th.ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE,
    )
    # The box itself was never HELD — the cross-entity gate, not a box state
    # change, produced the rejection.
    box2_after = th.validate_success(api.get_shipment(box2["id"], ADMIN))
    assert box2_after["fulfillment_status"] == "SCHEDULED"


def test_past_due_recovers_when_failed_invoice_is_settled(api):
    """PRD 3.5: "When the failed invoice is later settled, the subscription returns from `PAST_DUE` to `ACTIVE`."
    PRD 3.8: "A `SUCCEEDED` outcome moves the invoice to `PAID`, flips the box's `billing_status` to `PAID`, and, if the subscription was `PAST_DUE`, returns it to `ACTIVE`; it also runs the referral qualification check of Section 3.9."

    Design: Difficulty/cross_entity_state_dependency/shipment_advance_blocked_when_subscription_past_due
    """
    ctx, _, box2, invoice = _setup_past_due(api, email="pd-recover@x.com")

    th.validate_error(
        api.advance_fulfillment(box2["id"], {"to_status": "PICKING"}, OPS),
        th.ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE,
    )

    th.validate_success(
        api.record_payment(invoice["id"], {"outcome": "SUCCEEDED"}, ADMIN)
    )
    sub = th.validate_success(api.get_subscription(ctx["subscription"]["id"], ADMIN))
    assert sub["status"] == "ACTIVE", "settling the failed invoice recovers ACTIVE"

    advanced = th.validate_success(
        api.advance_fulfillment(box2["id"], {"to_status": "PICKING"}, OPS)
    )
    assert advanced["fulfillment_status"] == "PICKING"
