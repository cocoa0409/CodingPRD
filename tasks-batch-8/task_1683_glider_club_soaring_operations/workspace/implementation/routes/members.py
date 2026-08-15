"""Member endpoints: register, list/get, tier change, payments, suspend, resign."""

import uuid

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_CREDIT_CAP_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_MEMBER_IN_FLIGHT,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_RESOURCE_NOT_FOUND,
)
from middleware import auth, forbid, require_role
from response import success
from services import (
    ARREARS_THRESHOLD_CENTS,
    CREDIT_CAP_CENTS,
    cancel_reservation,
    prorated_dues_cents,
    ser_member,
    suspend_member,
    touch,
)
from util import get_body, need_int, need_str, opt_bool, paginate, sort_items

bp = Blueprint("members", __name__)


def _get_member_or_404(member_id):
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Member not found")
    return member


@bp.post("/soaring/members")
def create_member():
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    body = get_body()
    full_name = need_str(body, "full_name")
    tier_id = need_str(body, "tier_id")
    is_instructor = opt_bool(body, "is_instructor", False)
    is_tow_pilot = opt_bool(body, "is_tow_pilot", False)
    tier = db.STORE["tiers"].get(tier_id)
    if tier is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "MembershipTier not found")
    record = {
        "id": str(uuid.uuid4()),
        "full_name": full_name,
        "tier_id": tier_id,
        "status": "ACTIVE",
        "is_instructor": is_instructor,
        "is_tow_pilot": is_tow_pilot,
        "account_balance_cents": 0,
        "pending_dues_cents": 0,
        "suspension_reason": None,
        "solo_endorsed": False,
        "badge_level": "NONE",
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.STORE["members"][record["id"]] = record
    return success(ser_member(record), "object", 201)


@bp.get("/soaring/members")
def list_members():
    auth()
    from flask import request
    items = list(db.STORE["members"].values())
    tier_id = request.args.get("tier_id")
    status = request.args.get("status")
    if tier_id is not None:
        items = [m for m in items if m["tier_id"] == tier_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, meta = paginate(sort_items(items))
    return success([ser_member(m) for m in page], "array", 200, meta)


@bp.get("/soaring/members/<mid>")
def get_member(mid):
    auth()
    return success(ser_member(_get_member_or_404(mid)), "object", 200)


@bp.post("/soaring/members/<mid>/tier")
def change_tier(mid):
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    member = _get_member_or_404(mid)
    body = get_body()
    new_tier_id = need_str(body, "tier_id")
    new_tier = db.STORE["tiers"].get(new_tier_id)
    if new_tier is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "MembershipTier not found")
    old_tier = db.STORE["tiers"].get(member["tier_id"])
    old_dues = old_tier["monthly_dues_cents"] if old_tier else 0
    member["pending_dues_cents"] = prorated_dues_cents(
        old_dues, new_tier["monthly_dues_cents"], db.now()
    )
    member["tier_id"] = new_tier_id
    touch(member)
    return success(ser_member(member), "object", 200)


@bp.post("/soaring/members/<mid>/payments")
def record_payment(mid):
    user_id, role = auth()
    require_role(role, ["Member", "ClubAdmin"])
    if role == "Member" and user_id != mid:
        forbid("A Member may only record payments against their own account")
    member = _get_member_or_404(mid)
    if member["status"] == "RESIGNED":
        raise ApiError(
            ERR_MEMBER_NOT_ACTIVE, 409,
            "A RESIGNED member may not make payments",
        )
    body = get_body()
    amount = need_int(body, "amount_cents")
    new_balance = member["account_balance_cents"] - amount
    if new_balance < CREDIT_CAP_CENTS:
        raise ApiError(
            ERR_CREDIT_CAP_EXCEEDED, 402,
            "Payment would push the member credit beyond the -50000 cent cap",
        )
    member["account_balance_cents"] = new_balance
    if (
        member["status"] == "SUSPENDED"
        and member["suspension_reason"] == "ARREARS"
        and new_balance < ARREARS_THRESHOLD_CENTS
    ):
        member["status"] = "ACTIVE"
        member["suspension_reason"] = None
    touch(member)
    return success(ser_member(member), "object", 201)


@bp.post("/soaring/members/<mid>/suspend")
def suspend(mid):
    _, role = auth()
    require_role(role, ["ClubAdmin"])
    member = _get_member_or_404(mid)
    if member["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Only an ACTIVE member can be suspended",
        )
    suspend_member(member, "MANUAL")
    return success(ser_member(member), "object", 200)


@bp.post("/soaring/members/<mid>/resign")
def resign(mid):
    user_id, role = auth()
    require_role(role, ["Member", "ClubAdmin"])
    if role == "Member" and user_id != mid:
        forbid("A Member may only resign themselves")
    member = _get_member_or_404(mid)
    if member["status"] != "ACTIVE" and member["status"] != "SUSPENDED":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Member is already RESIGNED",
        )
    # No flight currently IN_FLIGHT for this member.
    for flight in db.STORE["flights"].values():
        if flight["status"] != "IN_FLIGHT":
            continue
        reservation = db.STORE["reservations"].get(flight["reservation_id"])
        if reservation is not None and reservation["member_id"] == mid:
            raise ApiError(
                ERR_MEMBER_IN_FLIGHT, 409,
                "Member cannot resign while a flight is IN_FLIGHT",
            )
    member["status"] = "RESIGNED"
    touch(member)
    # Cascade: ALL BOOKED reservations cancel regardless of date.
    for reservation in db.STORE["reservations"].values():
        if reservation["member_id"] == mid and reservation["status"] == "BOOKED":
            cancel_reservation(reservation)
    # Every OPEN availability window they published is cancelled.
    for window in db.STORE["availability"].values():
        if window["instructor_id"] == mid and window["status"] == "OPEN":
            window["status"] = "CANCELLED"
            touch(window)
    # Future-or-today duty slots in ASSIGNED|CONFIRMED cancel.
    today = db.today_start()
    for slot in db.STORE["duty_slots"].values():
        if (
            slot["member_id"] == mid
            and slot["status"] in ("ASSIGNED", "CONFIRMED")
            and slot["duty_date"] >= today
        ):
            slot["status"] = "CANCELLED"
            touch(slot)
    return success(ser_member(member), "object", 200)
