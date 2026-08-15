"""Tap connections: create, fee payment, install, disconnect, reconnect, abandon."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import (ALL_ROLES, body, get_district, get_scoped, opt_enum,
                        req_int, req_str, require_roles)
from response import ok_list, ok_object, paginate
from services import (invoice_dpd, new_common, new_ledger, ser_tap, touch)

bp = Blueprint("taps", __name__)

METER_SIZES = ["FIVE_EIGHTS_INCH", "THREE_QUARTER_INCH", "ONE_INCH", "TWO_INCH"]
ACTIVE_TAP = ("INSTALLED", "RECONNECTED")


def get_tap(district_id, tap_id):
    return get_scoped(db.taps, tap_id, district_id, "ERR_TAP_NOT_FOUND", "TapConnection")


def member_of(t):
    return db.members.get(t["member_id"])


@bp.post("/districts/<district_id>/taps")
@require_roles(["BillingClerk"])
def create_tap(user_id, role, district_id):
    b = body()
    member_id = req_str(b, "member_id")
    meter_size = opt_enum(b, "meter_size", METER_SIZES, "FIVE_EIGHTS_INCH")
    d = get_district(district_id)
    m = get_scoped(db.members, member_id, d["id"], "ERR_MEMBER_NOT_FOUND", "Member")
    if d.get("active_rate_schedule_id") is None:
        raise ApiError("ERR_NO_ACTIVE_RATE_SCHEDULE", 409,
                       "Tap fee quote requires an ADOPTED rate schedule")
    sched = db.rate_schedules[d["active_rate_schedule_id"]]
    fee = sched.get("tap_fee_schedule", {}).get(m["member_class"], 0)
    t = new_common()
    t.update({
        "district_id": d["id"],
        "member_id": m["id"],
        "tap_fee_cents": fee,
        "tap_fee_paid_cents": 0,
        "meter_size": meter_size,
        "status": "FEE_PENDING",
        "_pending_reconnect_fee": False,
    })
    db.taps[t["id"]] = t
    return ok_object(ser_tap(t), 201)


@bp.get("/districts/<district_id>/taps")
@require_roles(ALL_ROLES)
def list_taps(user_id, role, district_id):
    d = get_district(district_id)
    items = [t for t in db.taps.values() if t["district_id"] == d["id"]]
    mid = request.args.get("member_id")
    if mid is not None:
        items = [t for t in items if t["member_id"] == mid]
    st = request.args.get("status")
    if st is not None:
        items = [t for t in items if t["status"] == st]
    page, limit, offset, total = paginate(items, request.args)
    return ok_list([ser_tap(t) for t in page], limit, offset, total)


@bp.get("/districts/<district_id>/taps/<tap_id>")
@require_roles(ALL_ROLES)
def get_tap_by_id(user_id, role, district_id, tap_id):
    d = get_district(district_id)
    return ok_object(ser_tap(get_tap(d["id"], tap_id)))


@bp.post("/districts/<district_id>/taps/<tap_id>/pay-tap-fee")
@require_roles(["Treasurer"])
def pay_tap_fee(user_id, role, district_id, tap_id):
    b = body()
    amount = req_int(b, "amount_cents", minimum=0)
    d = get_district(district_id)
    t = get_tap(d["id"], tap_id)
    m = member_of(t)
    if m is None or m["membership_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "Tap fee collection requires an ACTIVE member")
    if t["status"] != "FEE_PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Tap is not awaiting fee payment")
    new_paid = t["tap_fee_paid_cents"] + amount
    if new_paid >= t["tap_fee_cents"]:
        excess = new_paid - t["tap_fee_cents"]
        t["tap_fee_paid_cents"] = t["tap_fee_cents"]
        if excess > 0:
            m["credit_balance_cents"] += excess
            touch(m)
        t["status"] = "PAID"
    else:
        t["tap_fee_paid_cents"] = new_paid
    touch(t)
    return ok_object(ser_tap(t))


@bp.post("/districts/<district_id>/taps/<tap_id>/install-meter")
@require_roles(["FieldOperator"])
def install_meter(user_id, role, district_id, tap_id):
    d = get_district(district_id)
    t = get_tap(d["id"], tap_id)
    if t["status"] == "FEE_PENDING":
        raise ApiError("ERR_TAP_FEE_UNPAID", 402, "Tap fee must be fully paid before installation")
    if t["status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", 409, "Tap is not in PAID status")
    m = member_of(t)
    if m is None or m["membership_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "Installation requires an ACTIVE member")
    # One active tap per member per service area: a tap lies in its member's
    # service area, so any other active tap of this member violates the rule.
    for other in db.taps.values():
        if (other["district_id"] == d["id"] and other["member_id"] == m["id"]
                and other["id"] != t["id"] and other["status"] in ACTIVE_TAP):
            raise ApiError("ERR_DUPLICATE_ACTIVE_TAP", 409,
                           "Member already has an active tap in this service area")
    t["status"] = "INSTALLED"
    touch(t)
    # Initial 0-gallon ACTUAL reading for the currently OPEN cycle, if one exists.
    open_cycles = [c for c in db.billing_cycles.values()
                   if c["district_id"] == d["id"] and c["status"] == "OPEN"]
    if open_cycles:
        open_cycles.sort(key=lambda c: c["_seq"])
        cyc = open_cycles[-1]
        r = new_ledger()
        r.update({
            "district_id": d["id"],
            "tap_id": t["id"],
            "cycle_id": cyc["id"],
            "reading_gallons": 0,
            "reading_type": "ACTUAL",
            "usage_gallons": 0,
        })
        db.readings[r["id"]] = r
    return ok_object(ser_tap(t))


@bp.post("/districts/<district_id>/taps/<tap_id>/disconnect")
@require_roles(["FieldOperator"])
def disconnect_tap(user_id, role, district_id, tap_id):
    d = get_district(district_id)
    t = get_tap(d["id"], tap_id)
    if t["status"] not in ACTIVE_TAP:
        raise ApiError("ERR_INVALID_STATE", 409, "Tap is not in INSTALLED or RECONNECTED status")
    # Health-safety moratorium first, then disconnect-eligibility.
    for o in db.boil_orders.values():
        if o["district_id"] == d["id"] and o["status"] == "IN_EFFECT":
            raise ApiError("ERR_BOIL_ORDER_MORATORIUM", 409,
                           "Disconnect blocked while a boil order is IN_EFFECT")
    unpaid = [inv for inv in db.invoices.values()
              if inv["district_id"] == d["id"] and inv["tap_id"] == t["id"]
              and inv["billing_status"] in ("ISSUED", "PARTIALLY_PAID")]
    for inv in unpaid:
        if inv["collection_status"] != "DISCONNECT_ELIGIBLE":
            raise ApiError("ERR_NOT_DISCONNECT_ELIGIBLE", 409,
                           "Every unpaid invoice on the tap must be DISCONNECT_ELIGIBLE")
    t["status"] = "DISCONNECTED"
    touch(t)
    for inv in unpaid:
        inv["collection_status"] = "DISCONNECTED"
        inv["_dpd_frozen"] = invoice_dpd(inv)
        touch(inv)
    # Suspend the member when this was the last active tap and debt remains.
    m = member_of(t)
    if m is not None and m["membership_status"] == "ACTIVE":
        other_active = any(
            o["district_id"] == d["id"] and o["member_id"] == m["id"]
            and o["id"] != t["id"] and o["status"] in ACTIVE_TAP
            for o in db.taps.values()
        )
        if not other_active:
            member_unpaid = any(
                inv["district_id"] == d["id"] and inv["member_id"] == m["id"]
                and inv["billing_status"] in ("ISSUED", "PARTIALLY_PAID")
                for inv in db.invoices.values()
            )
            if member_unpaid:
                m["membership_status"] = "SUSPENDED"
                touch(m)
    return ok_object(ser_tap(t))


@bp.post("/districts/<district_id>/taps/<tap_id>/reconnect")
@require_roles(["FieldOperator"])
def reconnect_tap(user_id, role, district_id, tap_id):
    d = get_district(district_id)
    t = get_tap(d["id"], tap_id)
    if t["status"] != "DISCONNECTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Tap is not DISCONNECTED")
    for inv in db.invoices.values():
        if (inv["district_id"] == d["id"] and inv["tap_id"] == t["id"]
                and inv["billing_status"] in ("ISSUED", "PARTIALLY_PAID")):
            raise ApiError("ERR_OUTSTANDING_BALANCE", 402,
                           "Reconnect requires every invoice on the tap to be PAID")
    t["status"] = "RECONNECTED"
    t["_pending_reconnect_fee"] = True
    touch(t)
    m = member_of(t)
    if m is not None and m["membership_status"] == "SUSPENDED":
        m["membership_status"] = "ACTIVE"
        touch(m)
    return ok_object(ser_tap(t))


@bp.post("/districts/<district_id>/taps/<tap_id>/abandon")
@require_roles(["BillingClerk"])
def abandon_tap(user_id, role, district_id, tap_id):
    d = get_district(district_id)
    t = get_tap(d["id"], tap_id)
    if t["status"] not in ("FEE_PENDING", "PAID"):
        raise ApiError("ERR_INVALID_STATE", 409, "Only FEE_PENDING or PAID taps may be abandoned")
    for inv in db.invoices.values():
        if inv["district_id"] == d["id"] and inv["tap_id"] == t["id"]:
            raise ApiError("ERR_TAP_HAS_BILLING_HISTORY", 409,
                           "Abandon requires no invoices on the tap")
    t["status"] = "ABANDONED"
    touch(t)
    return ok_object(ser_tap(t))
