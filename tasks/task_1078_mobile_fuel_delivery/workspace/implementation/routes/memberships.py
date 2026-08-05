from datetime import timedelta

from flask import Blueprint, request

import store
from store import DB
from core import (ApiError, get_auth, require_role, get_body, require_fields,
                  check_enum, as_int, as_bool, ok, ok_list, paginate,
                  sorted_records, base_record, touch, deny)
from serializers import ser_membership
from domain import get_customer, get_membership

bp = Blueprint("memberships", __name__)


def _period_end(start):
    return start + timedelta(days=store.MEMBERSHIP_PERIOD_DAYS)


def _final_settlement(m):
    unused = max(0, m["included_deliveries"] - m["deliveries_used_this_period"])
    charge = m["monthly_fee_cents"] - unused * store.UNUSED_DELIVERY_CREDIT_CENTS
    return max(0, charge)


@bp.post("/memberships")
def create_membership():
    uid, role = get_auth()
    require_role(role, {"Member"})
    body = get_body()
    require_fields(body, ["customer_id", "tier", "monthly_fee_cents", "included_deliveries"])
    check_enum(body["tier"], {"BASIC", "PLUS", "PRO"}, "tier")
    as_int(body["monthly_fee_cents"], "monthly_fee_cents", minimum=0)
    as_int(body["included_deliveries"], "included_deliveries", minimum=0)
    price_lock = True
    if "price_lock_enabled" in body and body["price_lock_enabled"] is not None:
        price_lock = as_bool(body["price_lock_enabled"], "price_lock_enabled")
    if body["customer_id"] != uid:
        deny()
    get_customer(body["customer_id"])
    start = store.now()
    rec = base_record()
    rec.update({
        "customer_id": body["customer_id"],
        "tier": body["tier"],
        "monthly_fee_cents": body["monthly_fee_cents"],
        "included_deliveries": body["included_deliveries"],
        "price_lock_enabled": price_lock,
        "deliveries_used_this_period": 0,
        "status": "ACTIVE",
        "current_period_start": start,
        "current_period_end": _period_end(start),
        "estimated_next_charge_cents": body["monthly_fee_cents"],
        "final_settlement_charge_cents": None,
    })
    DB.memberships[rec["id"]] = rec
    return ok(ser_membership(rec), status=201)


@bp.get("/memberships")
def list_memberships():
    uid, role = get_auth()
    require_role(role, {"Member", "BillingOfficer", "PlatformAdmin"})
    items = sorted_records(DB.memberships)
    if role == "Member":
        items = [m for m in items if m["customer_id"] == uid]
    cid = request.args.get("customer_id")
    st = request.args.get("status")
    if cid:
        items = [m for m in items if m["customer_id"] == cid]
    if st:
        items = [m for m in items if m["status"] == st]
    page, total, limit, offset = paginate(items)
    return ok_list([ser_membership(m) for m in page], total, limit, offset)


@bp.get("/memberships/<mid>")
def get_membership_ep(mid):
    uid, role = get_auth()
    require_role(role, {"Member", "BillingOfficer", "PlatformAdmin"})
    m = get_membership(mid)
    if role == "Member" and m["customer_id"] != uid:
        deny()
    return ok(ser_membership(m))


@bp.post("/memberships/<mid>/pause")
def pause_membership(mid):
    uid, role = get_auth()
    require_role(role, {"Member"})
    m = get_membership(mid)
    if m["customer_id"] != uid:
        deny()
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_MEMBERSHIP_STATE", "Membership not ACTIVE")
    m["status"] = "PAUSED"
    touch(m)
    return ok(ser_membership(m))


@bp.post("/memberships/<mid>/resume")
def resume_membership(mid):
    uid, role = get_auth()
    require_role(role, {"Member"})
    m = get_membership(mid)
    if m["customer_id"] != uid:
        deny()
    if m["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_MEMBERSHIP_STATE", "Membership not PAUSED")
    m["status"] = "ACTIVE"
    touch(m)
    return ok(ser_membership(m))


@bp.post("/memberships/<mid>/cancel")
def cancel_membership(mid):
    uid, role = get_auth()
    require_role(role, {"Member"})
    m = get_membership(mid)
    if m["customer_id"] != uid:
        deny()
    if m["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_MEMBERSHIP_STATE", "Membership already CANCELLED")
    m["final_settlement_charge_cents"] = _final_settlement(m)
    m["status"] = "CANCELLED"
    touch(m)
    _cascade_cancel_member_orders(m)
    return ok(ser_membership(m))


@bp.post("/memberships/<mid>/renew-charge")
def renew_charge(mid):
    uid, role = get_auth()
    require_role(role, {"BillingOfficer"})
    m = get_membership(mid)
    body = get_body()
    require_fields(body, ["outcome"])
    check_enum(body["outcome"], {"SUCCEEDED", "FAILED"}, "outcome")
    outcome = body["outcome"]
    status = m["status"]
    clock = store.now()

    if status == "ACTIVE":
        if clock < m["current_period_end"]:
            raise ApiError("ERR_INVALID_MEMBERSHIP_STATE", "Period has not elapsed")
        m["final_settlement_charge_cents"] = _final_settlement(m)
        if outcome == "SUCCEEDED":
            _roll_period(m)
        else:  # FAILED
            m["status"] = "PAST_DUE"
    elif status == "PAST_DUE":
        if outcome == "SUCCEEDED":
            _roll_period(m)
            m["status"] = "ACTIVE"
        else:
            raise ApiError("ERR_INVALID_MEMBERSHIP_STATE", "Cannot fail a PAST_DUE renewal")
    else:
        raise ApiError("ERR_INVALID_MEMBERSHIP_STATE", "Cannot renew from %s" % status)

    touch(m)
    return ok(ser_membership(m))


def _roll_period(m):
    prior_end = m["current_period_end"]
    m["current_period_start"] = prior_end
    m["current_period_end"] = _period_end(prior_end)
    m["deliveries_used_this_period"] = 0
    m["estimated_next_charge_cents"] = m["monthly_fee_cents"]


def _cascade_cancel_member_orders(m):
    from routes.orders import cancel_order_effects
    for o in list(DB.orders.values()):
        if o["membership_id"] == m["id"] and o["status"] in ("SCHEDULED", "ROUTED"):
            cancel_order_effects(o)
