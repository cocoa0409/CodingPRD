"""Boil orders, notification receipts, compliance samples (PRD §3.11)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import (ALL_ROLES, body, get_district, get_scoped, req_dt,
                        req_enum, req_str, require_roles)
from response import ok_list, ok_object, paginate
from services import (bump_district, new_common, new_ledger,
                      ser_boil_order, ser_notification, ser_sample, touch,
                      NOTIFY_WINDOW_HOURS, SAMPLING_WINDOW_HOURS,
                      REQUIRED_CLEAR_SAMPLES)

bp = Blueprint("safety", __name__)

CHANNELS = ["DOOR_HANGER", "CERTIFIED_MAIL", "PHONE_TREE"]


def get_order(district_id, order_id):
    return get_scoped(db.boil_orders, order_id, district_id, "ERR_ORDER_NOT_FOUND", "BoilOrder")


def refresh_boil_order_active(d):
    d["boil_order_active"] = any(
        o["district_id"] == d["id"] and o["status"] == "IN_EFFECT"
        for o in db.boil_orders.values()
    )


@bp.post("/districts/<district_id>/boil-orders")
@require_roles(["FieldOperator"])
def create_order(user_id, role, district_id):
    b = body()
    reason = req_str(b, "reason")
    d = get_district(district_id)
    now = db.now_dt()
    o = new_common()
    o.update({
        "district_id": d["id"],
        "issued_utc": db.fmt_dt(now),
        "reason": reason,
        "notification_deadline_utc": db.fmt_dt(now + timedelta(hours=NOTIFY_WINDOW_HOURS)),
        "notified_member_count": 0,
        "status": "IN_EFFECT",
    })
    db.boil_orders[o["id"]] = o
    refresh_boil_order_active(d)
    bump_district(d)
    return ok_object(ser_boil_order(o), 201)


@bp.get("/districts/<district_id>/boil-orders")
@require_roles(ALL_ROLES)
def list_orders(user_id, role, district_id):
    d = get_district(district_id)
    items = [o for o in db.boil_orders.values() if o["district_id"] == d["id"]]
    st = request.args.get("status")
    if st is not None:
        items = [o for o in items if o["status"] == st]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_boil_order(o) for o in page], limit, offset, total)


@bp.post("/districts/<district_id>/boil-orders/<order_id>/notifications")
@require_roles(["FieldOperator"])
def create_notification(user_id, role, district_id, order_id):
    b = body()
    member_id = req_str(b, "member_id")
    channel = req_enum(b, "channel", CHANNELS)
    d = get_district(district_id)
    o = get_order(d["id"], order_id)
    m = get_scoped(db.members, member_id, d["id"], "ERR_MEMBER_NOT_FOUND", "Member")
    for n in db.notifications.values():
        if n["boil_order_id"] == o["id"] and n["member_id"] == m["id"]:
            raise ApiError("ERR_DUPLICATE_NOTIFICATION", 409,
                           "Member already notified for this boil order")
    n = new_ledger()
    n.update({
        "district_id": d["id"],
        "boil_order_id": o["id"],
        "member_id": m["id"],
        "channel": channel,
        "notified_utc": db.now_iso(),
    })
    db.notifications[n["id"]] = n
    distinct = {x["member_id"] for x in db.notifications.values() if x["boil_order_id"] == o["id"]}
    o["notified_member_count"] = len(distinct)
    touch(o)
    return ok_object(ser_notification(n), 201)


@bp.get("/districts/<district_id>/boil-orders/<order_id>/notifications")
@require_roles(ALL_ROLES)
def list_notifications(user_id, role, district_id, order_id):
    d = get_district(district_id)
    o = get_order(d["id"], order_id)
    items = [n for n in db.notifications.values() if n["boil_order_id"] == o["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_notification(n) for n in page], limit, offset, total)


@bp.post("/districts/<district_id>/boil-orders/<order_id>/begin-sampling")
@require_roles(["FieldOperator"])
def begin_sampling(user_id, role, district_id, order_id):
    d = get_district(district_id)
    o = get_order(d["id"], order_id)
    if o["status"] != "IN_EFFECT":
        raise ApiError("ERR_INVALID_STATE", 409, "Boil order is not IN_EFFECT")
    active_members = sum(
        1 for m in db.members.values()
        if m["district_id"] == d["id"] and m["membership_status"] == "ACTIVE"
    )
    if o["notified_member_count"] != active_members:
        raise ApiError("ERR_NOTIFICATION_INCOMPLETE", 409,
                       "Every ACTIVE member must be notified before sampling begins")
    o["status"] = "SAMPLING"
    touch(o)
    refresh_boil_order_active(d)
    return ok_object(ser_boil_order(o))


# -------------------------------------------------------- compliance samples

@bp.post("/districts/<district_id>/compliance-samples")
@require_roles(["FieldOperator"])
def create_sample(user_id, role, district_id):
    b = body()
    order_id = req_str(b, "boil_order_id")
    point = req_str(b, "sample_point")
    collected_raw, collected = req_dt(b, "collected_utc")
    d = get_district(district_id)
    o = get_order(d["id"], order_id)
    issued = db.parse_dt(o["issued_utc"])
    if collected < issued or collected > issued + timedelta(hours=SAMPLING_WINDOW_HOURS):
        raise ApiError("ERR_SAMPLE_WINDOW_VIOLATION", 422,
                       "collected_utc must fall within [issued_utc, issued_utc + 72h]")
    s = new_common()
    s.update({
        "district_id": d["id"],
        "boil_order_id": o["id"],
        "sample_point": point,
        "collected_utc": collected_raw,
        "result": "PENDING",
    })
    db.samples[s["id"]] = s
    return ok_object(ser_sample(s), 201)


@bp.get("/districts/<district_id>/compliance-samples")
@require_roles(ALL_ROLES)
def list_samples(user_id, role, district_id):
    d = get_district(district_id)
    items = [s for s in db.samples.values() if s["district_id"] == d["id"]]
    oid = request.args.get("boil_order_id")
    if oid is not None:
        items = [s for s in items if s["boil_order_id"] == oid]
    res = request.args.get("result")
    if res is not None:
        items = [s for s in items if s["result"] == res]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_sample(s) for s in page], limit, offset, total)


@bp.post("/districts/<district_id>/compliance-samples/<sample_id>/record-result")
@require_roles(["FieldOperator"])
def record_result(user_id, role, district_id, sample_id):
    b = body()
    result = req_enum(b, "result", ["ABSENT", "PRESENT"])
    d = get_district(district_id)
    s = get_scoped(db.samples, sample_id, d["id"], "ERR_SAMPLE_NOT_FOUND", "ComplianceSample")
    o = db.boil_orders.get(s["boil_order_id"])
    if o is None or o["status"] != "SAMPLING":
        raise ApiError("ERR_ORDER_NOT_SAMPLING", 409,
                       "Recording a result requires the parent boil order to be SAMPLING")
    if s["result"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Sample result has already been recorded")
    s["result"] = result
    touch(s)
    if result == "PRESENT":
        o["status"] = "VIOLATION_ESCALATED"
        touch(o)
        refresh_boil_order_active(d)
        bump_district(d)
    else:
        # Lift when the two most recently resulted samples (created_at order)
        # are both ABSENT; a PRESENT anywhere would already have escalated.
        resulted = [x for x in db.samples.values()
                    if x["boil_order_id"] == o["id"] and x["result"] != "PENDING"]
        resulted.sort(key=lambda x: (x["created_at"], x["_seq"]))
        if (len(resulted) >= REQUIRED_CLEAR_SAMPLES
                and resulted[-1]["result"] == "ABSENT"
                and resulted[-2]["result"] == "ABSENT"):
            o["status"] = "LIFTED"
            touch(o)
            refresh_boil_order_active(d)
            bump_district(d)
    return ok_object(ser_sample(s))
