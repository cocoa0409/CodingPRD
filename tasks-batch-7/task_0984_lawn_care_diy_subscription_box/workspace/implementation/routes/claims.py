from datetime import timedelta

from flask import Blueprint, request

from db import store, now, next_seq, new_id, touch, Rec
from errors import (
    raise_err, ERR_SUBSCRIPTION_NOT_FOUND, ERR_SHIPMENT_NOT_FOUND, ERR_CLAIM_NOT_FOUND,
    ERR_CUSTOMER_SUSPENDED, ERR_SHIPMENT_NOT_DELIVERED, ERR_CLAIM_WINDOW_EXPIRED,
    ERR_CLAIM_NOT_FILED, ERR_SHIPMENT_NOT_PAID, ERR_INVALID_REQUEST,
)
from middleware import get_body, authenticate, check_ownership, paginate, sort_items
from response import ok, ok_list
from serializers import ser_claim
from services import (
    create_box, post_ledger, lawn_of_subscription, invoice_for_box,
    SATISFACTION_CREDIT_CAP_CENTS, CLAIM_WINDOW_DAYS, AUTO_SHIP_WINDOW_DAYS,
)
from util import req_str, req_enum, fmt_dt3

bp = Blueprint("claims", __name__)

READ_ROLES = ["Customer", "Agronomist", "PlatformAdmin"]
CLAIM_REASONS = {"INEFFECTIVE", "DAMAGED", "WRONG_PRODUCT", "OTHER"}
RESOLUTION_TYPES = {"RESHIP", "CREDIT", "REFUND", "DENY"}


def _get_claim_or_404(cid):
    rec = store.claims.get(cid)
    if rec is None:
        raise_err(ERR_CLAIM_NOT_FOUND, "Claim not found")
    return rec


def _owner_of_claim(claim):
    sub = store.subscriptions.get(claim.subscription_id)
    return sub.customer_id if sub else None


@bp.route("/api/claims", methods=["POST"])
def create_claim():
    body = get_body()
    subscription_id = req_str(body, "subscription_id")
    shipment_id = req_str(body, "shipment_id")
    claim_reason = req_enum(body, "claim_reason", CLAIM_REASONS)
    evidence_url = body.get("evidence_url")
    if evidence_url is not None and not isinstance(evidence_url, str):
        raise_err(ERR_INVALID_REQUEST, "Field 'evidence_url' must be a string")

    uid, role = authenticate(["Customer"])
    sub = store.subscriptions.get(subscription_id)
    if sub is None:
        raise_err(ERR_SUBSCRIPTION_NOT_FOUND, "Subscription not found")
    check_ownership(uid, role, sub.customer_id)
    box = store.shipments.get(shipment_id)
    if box is None:
        raise_err(ERR_SHIPMENT_NOT_FOUND, "Shipment not found")
    if box.subscription_id != subscription_id:
        raise_err(ERR_SHIPMENT_NOT_FOUND, "Shipment does not belong to the subscription")
    cust = store.customers.get(sub.customer_id)
    if cust is not None and cust.status == "SUSPENDED":
        raise_err(ERR_CUSTOMER_SUSPENDED, "Customer is SUSPENDED; creates are blocked")
    if box.fulfillment_status != "DELIVERED":
        raise_err(ERR_SHIPMENT_NOT_DELIVERED, "Claims require a DELIVERED shipment")
    ts = now()
    if box.delivered_at is not None and ts - box.delivered_at > timedelta(days=CLAIM_WINDOW_DAYS):
        raise_err(ERR_CLAIM_WINDOW_EXPIRED, "Claim filed more than 30 days after delivery")

    rec = Rec(
        id=new_id(), created_at=ts, updated_at=ts, version=1, seq=next_seq(),
        subscription_id=subscription_id, shipment_id=shipment_id,
        claim_reason=claim_reason, evidence_url=evidence_url, status="FILED",
        resolution_type=None, credit_amount_cents=None, filed_at=ts,
    )
    rec.raw["created_at"] = fmt_dt3(ts)
    rec.raw["updated_at"] = fmt_dt3(ts)
    rec.raw["filed_at"] = fmt_dt3(ts)
    store.claims[rec.id] = rec
    return ok(ser_claim(rec), 201)


@bp.route("/api/claims/<cid>", methods=["GET"])
def get_claim(cid):
    uid, role = authenticate(READ_ROLES)
    rec = _get_claim_or_404(cid)
    check_ownership(uid, role, _owner_of_claim(rec))
    return ok(ser_claim(rec))


@bp.route("/api/claims", methods=["GET"])
def list_claims():
    uid, role = authenticate(READ_ROLES)
    items = list(store.claims.values())
    if role == "Customer":
        own_subs = {s.id for s in store.subscriptions.values() if s.customer_id == uid}
        items = [c for c in items if c.subscription_id in own_subs]
    for param in ("subscription_id", "shipment_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if getattr(c, param) == v]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_claim(c) for c in page], total, limit, offset)


@bp.route("/api/claims/<cid>/resolve", methods=["POST"])
def resolve_claim(cid):
    body = get_body()
    resolution_type = req_enum(body, "resolution_type", RESOLUTION_TYPES)
    authenticate(["Agronomist"])
    rec = _get_claim_or_404(cid)
    if rec.status != "FILED":
        raise_err(ERR_CLAIM_NOT_FILED, "resolve requires claim FILED")

    sub = store.subscriptions.get(rec.subscription_id)
    box = store.shipments.get(rec.shipment_id)

    if resolution_type == "DENY":
        rec.status = "DENIED"
        touch(rec)
        return ok(ser_claim(rec))

    if resolution_type == "REFUND" and box.billing_status != "PAID":
        # precondition must be checked before any mutation (atomicity)
        raise_err(ERR_SHIPMENT_NOT_PAID, "REFUND requires the shipment's billing_status PAID")

    rec.resolution_type = resolution_type
    rec.status = "RESOLVED"

    if resolution_type == "RESHIP":
        # replacement box: lines copied, ship_date = logical clock, attaches
        # unattached CONFIRMED add-ons, one AWAITING_DELIVERY task per line
        ts = now()
        lines = [{"product_sku": l["product_sku"], "qty_units": l["qty_units"]} for l in box.lines]
        new_box = create_box(
            rec.subscription_id, "REPLACEMENT", ts, ts,
            ts + timedelta(days=AUTO_SHIP_WINDOW_DAYS), lines,
            source_claim_id=rec.id,
        )
        lawn = lawn_of_subscription(sub)
        for line in lines:
            task = Rec(
                id=new_id(), created_at=now(), updated_at=now(), version=1, seq=next_seq(),
                lawn_id=lawn.id if lawn else None,
                subscription_id=rec.subscription_id, shipment_id=new_box.id,
                product_sku=line["product_sku"], scheduled_date=None,
                status="AWAITING_DELIVERY", window_start_date=None, window_end_date=None,
                snooze_count=0, applied_at=None,
            )
            task.raw["created_at"] = fmt_dt3(task.created_at)
            task.raw["updated_at"] = fmt_dt3(task.updated_at)
            store.applications[task.id] = task
    elif resolution_type == "CREDIT":
        final_charge = box.final_charge_cents if box.final_charge_cents is not None else 0
        rec.credit_amount_cents = min(final_charge, SATISFACTION_CREDIT_CAP_CENTS)
        post_ledger(sub.customer_id, "EARN_SATISFACTION", rec.credit_amount_cents,
                    reference_id=rec.id)
    else:  # REFUND
        box.billing_status = "VOID"
        touch(box)
        inv = invoice_for_box(box.id)
        if inv is not None and inv.credit_applied_cents > 0:
            post_ledger(sub.customer_id, "RESTORE_VOID_INVOICE", inv.credit_applied_cents,
                        reference_id=inv.id)

    touch(rec)
    return ok(ser_claim(rec))
