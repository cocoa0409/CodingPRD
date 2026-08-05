"""Member routes: registration, balances, payments, billing health."""
from datetime import timedelta

from flask import Blueprint

import core
from core import (
    db, require, get_body, get_or_404, base_record, touch, success,
    list_response, req_str, req_int, opt_enum, ApiError, now_clock,
    SUSPEND_GRACE_DAYS,
)
from services import ser_member, ser_vehicle, ser_waitlist

bp = Blueprint("members", __name__)

TIERS = {"BRONZE", "SILVER", "GOLD", "PLATINUM"}


@bp.post("/members")
def create_member():
    require("VaultManager", "BillingAdmin")
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    tier = opt_enum(body, "membership_tier", TIERS, "BRONZE")
    for m in db.members.values():
        if m["email"] == email:
            raise ApiError("ERR_DUPLICATE", 409, "email already registered")
    rec = base_record()
    rec.update({
        "full_name": full_name,
        "email": email,
        "membership_tier": tier,
        "billing_status": "CURRENT",
    })
    db.members[rec["id"]] = rec
    return success(ser_member(rec), status=201)


@bp.get("/members/<mid>")
def get_member(mid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    rec = get_or_404(db.members, mid)
    return success(ser_member(rec))


@bp.get("/members/<mid>/vehicles")
def list_member_vehicles(mid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    get_or_404(db.members, mid)
    vehicles = [v for v in db.vehicles.values() if v["member_id"] == mid]
    return list_response(vehicles, ser_vehicle)


@bp.get("/members/<mid>/waitlist")
def list_member_waitlist(mid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    get_or_404(db.members, mid)
    entries = [w for w in db.waitlist.values() if w["member_id"] == mid]
    return list_response(entries, ser_waitlist)


@bp.post("/members/<mid>/record-payment")
def record_payment(mid):
    require("BillingAdmin")
    member = get_or_404(db.members, mid)
    body = get_body()
    amount_cents = req_int(body, "amount_cents", minimum=0)
    db.payments.append({"member_id": mid, "amount_cents": amount_cents})
    touch(member)
    return success(ser_member(member))


@bp.post("/members/<mid>/refresh-billing")
def refresh_billing(mid):
    require("BillingAdmin")
    member = get_or_404(db.members, mid)
    clock = now_clock()
    issued = [inv for inv in db.invoices.values()
              if inv["member_id"] == mid and inv["status"] == "ISSUED"]
    past_due = [inv for inv in issued if inv["due_at"] is not None and inv["due_at"] <= clock]
    grace_due = [inv for inv in issued
                 if inv["due_at"] is not None
                 and inv["due_at"] + timedelta(days=SUSPEND_GRACE_DAYS) <= clock]
    cur = member["billing_status"]
    if cur == "CURRENT":
        new = "PAST_DUE" if past_due else "CURRENT"
    elif cur == "PAST_DUE":
        if not past_due:
            new = "CURRENT"
        elif grace_due:
            new = "SUSPENDED"
        else:
            new = "PAST_DUE"
    else:  # SUSPENDED
        new = "CURRENT" if not past_due else "SUSPENDED"
    if new != cur:
        member["billing_status"] = new
        touch(member)
    return success(ser_member(member))
