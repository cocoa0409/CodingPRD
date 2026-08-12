from flask import Blueprint, request

from db import store, now, next_seq, new_id, touch, Rec
from errors import (
    raise_err, ERR_SUBSCRIPTION_NOT_FOUND, ERR_SHIPMENT_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ERR_CUSTOMER_SUSPENDED,
    ERR_SHIPMENT_NOT_DELIVERED, ERR_APPLICATION_NOT_SCHEDULED,
    ERR_WEATHER_GATE_BLOCKED, ERR_APPLICATION_WINDOW_VIOLATION,
    ERR_APPLICATION_BUFFER_CONFLICT,
)
from middleware import get_body, authenticate, check_ownership, paginate, sort_items
from response import ok, ok_list
from serializers import ser_application
from services import (
    find_product_by_sku, lawn_of_subscription, weather_blocked, date_in_window,
    buffer_conflict, product_window_for_year,
)
from util import req_str, parse_ymd, fmt_dt3

bp = Blueprint("applications", __name__)

READ_ROLES = ["Customer", "Agronomist", "PlatformAdmin"]


def _get_task_or_404(tid):
    rec = store.applications.get(tid)
    if rec is None:
        raise_err(ERR_APPLICATION_NOT_FOUND, "Application task not found")
    return rec


def _owner_of_task(task):
    sub = store.subscriptions.get(task.subscription_id)
    return sub.customer_id if sub else None


def _run_guards(lawn, product, date_str, exclude_task_id=None):
    """weather gate (band 6) -> product window (band 7) -> category buffer (band 8)."""
    if weather_blocked(lawn.region, date_str):
        raise_err(ERR_WEATHER_GATE_BLOCKED, "Weather advisory blocks the scheduled date")
    inside, _, _ = date_in_window(product, date_str)
    if not inside:
        raise_err(ERR_APPLICATION_WINDOW_VIOLATION,
                  "Scheduled date is outside the product's application window")
    if buffer_conflict(lawn.id, product, date_str, exclude_task_id=exclude_task_id):
        raise_err(ERR_APPLICATION_BUFFER_CONFLICT,
                  "Conflicting-category application inside the min-gap buffer on this lawn")


@bp.route("/api/applications", methods=["POST"])
def create_application():
    body = get_body()
    subscription_id = req_str(body, "subscription_id")
    shipment_id = req_str(body, "shipment_id")
    product_sku = req_str(body, "product_sku")
    scheduled_date = parse_ymd(body.get("scheduled_date"), "scheduled_date").isoformat()

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
    product = find_product_by_sku(product_sku)
    if product is None:
        raise_err(ERR_PRODUCT_NOT_FOUND, "Product sku '%s' does not exist" % product_sku)
    cust = store.customers.get(sub.customer_id)
    if cust is not None and cust.status == "SUSPENDED":
        raise_err(ERR_CUSTOMER_SUSPENDED, "Customer is SUSPENDED; creates are blocked")
    if box.fulfillment_status != "DELIVERED":
        raise_err(ERR_SHIPMENT_NOT_DELIVERED, "Application requires a DELIVERED shipment")

    lawn = lawn_of_subscription(sub)
    _run_guards(lawn, product, scheduled_date)
    start, end = product_window_for_year(product, int(scheduled_date[:4]))

    ts = now()
    rec = Rec(
        id=new_id(), created_at=ts, updated_at=ts, version=1, seq=next_seq(),
        lawn_id=lawn.id, subscription_id=subscription_id, shipment_id=shipment_id,
        product_sku=product_sku, scheduled_date=scheduled_date, status="SCHEDULED",
        window_start_date=start, window_end_date=end, snooze_count=0, applied_at=None,
    )
    rec.raw["created_at"] = fmt_dt3(ts)
    rec.raw["updated_at"] = fmt_dt3(ts)
    store.applications[rec.id] = rec
    return ok(ser_application(rec), 201)


@bp.route("/api/applications/<tid>", methods=["GET"])
def get_application(tid):
    uid, role = authenticate(READ_ROLES)
    rec = _get_task_or_404(tid)
    check_ownership(uid, role, _owner_of_task(rec))
    return ok(ser_application(rec))


@bp.route("/api/applications", methods=["GET"])
def list_applications():
    uid, role = authenticate(READ_ROLES)
    items = list(store.applications.values())
    if role == "Customer":
        own_subs = {s.id for s in store.subscriptions.values() if s.customer_id == uid}
        items = [t for t in items if t.subscription_id in own_subs]
    for param in ("lawn_id", "subscription_id", "shipment_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [t for t in items if getattr(t, param) == v]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_application(t) for t in page], total, limit, offset)


@bp.route("/api/applications/<tid>/reschedule", methods=["POST"])
def reschedule(tid):
    body = get_body()
    new_date = parse_ymd(body.get("new_date"), "new_date").isoformat()
    uid, role = authenticate(["Customer"])
    rec = _get_task_or_404(tid)
    check_ownership(uid, role, _owner_of_task(rec))
    if rec.status != "SCHEDULED":
        raise_err(ERR_APPLICATION_NOT_SCHEDULED, "reschedule requires task SCHEDULED")
    lawn = store.lawns.get(rec.lawn_id)
    product = find_product_by_sku(rec.product_sku)
    _run_guards(lawn, product, new_date, exclude_task_id=rec.id)
    rec.scheduled_date = new_date
    rec.snooze_count += 1
    start, end = product_window_for_year(product, int(new_date[:4]))
    rec.window_start_date = start
    rec.window_end_date = end
    touch(rec)
    return ok(ser_application(rec))


@bp.route("/api/applications/<tid>/mark-applied", methods=["POST"])
def mark_applied(tid):
    uid, role = authenticate(["Customer"])
    rec = _get_task_or_404(tid)
    check_ownership(uid, role, _owner_of_task(rec))
    if rec.status != "SCHEDULED":
        raise_err(ERR_APPLICATION_NOT_SCHEDULED, "mark-applied requires task SCHEDULED")
    rec.status = "APPLIED"
    rec.applied_at = now()
    rec.raw["applied_at"] = fmt_dt3(rec.applied_at)
    touch(rec)
    return ok(ser_application(rec))


@bp.route("/api/applications/<tid>/reminder", methods=["GET"])
def reminder(tid):
    uid, role = authenticate(READ_ROLES)
    rec = _get_task_or_404(tid)
    check_ownership(uid, role, _owner_of_task(rec))
    reasons = []
    if rec.scheduled_date is not None:
        lawn = store.lawns.get(rec.lawn_id)
        product = find_product_by_sku(rec.product_sku)
        if lawn is not None and weather_blocked(lawn.region, rec.scheduled_date):
            reasons.append("ERR_WEATHER_GATE_BLOCKED")
        if product is not None:
            inside, _, _ = date_in_window(product, rec.scheduled_date)
            if not inside:
                reasons.append("ERR_APPLICATION_WINDOW_VIOLATION")
    return ok({
        "reminder_recommended": len(reasons) == 0,
        "blocking_reasons": reasons,
    })
