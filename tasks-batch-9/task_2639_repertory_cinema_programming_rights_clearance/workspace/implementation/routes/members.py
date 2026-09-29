"""Membership standing, donations and the lapse sweep (PRD 3.7)."""
from flask import Blueprint

import serialize
from auth import ROLE_BOX, ROLE_EXEC, ROLE_MEMBER, authorize, require_own_member
from calc import TIER_BASIC_CENTS, refresh_member
from errors import ApiError
from response import object_response
from store import new_record, now, ordered, touch
from timeutil import fmt_instant
from validate import (body, insert, must_find, req_day, req_instant, req_int, req_str,
                      rows)

bp = Blueprint("members", __name__)


@bp.post("/members")
def create_member():
    authorize((ROLE_BOX, ROLE_EXEC))
    payload = body()
    full_name = req_str(payload, "full_name")
    email = req_str(payload, "email")
    join_date = req_day(payload, "join_date")
    for other in rows("members"):
        if other["email"] == email and other["status"] in ("PENDING", "ACTIVE"):
            raise ApiError("ERR_MEMBER_EMAIL_TAKEN",
                           "That email is already held by a live membership.")
    row = new_record(
        full_name=full_name,
        email=email,
        join_date=join_date,
        status="PENDING",
        donations=[],
        expires_at=None,
        rolling_donation_cents=0,
        fiscal_ytd_donation_cents=0,
        rolling_tier="PROSPECT",
        fiscal_tier="PROSPECT",
        effective_tier="PROSPECT",
        discount_pct=0.00,
        advance_access_hours=0,
        comp_tickets_granted=0,
        comp_tickets_remaining=0,
        credit_balance_cents=0,
    )
    insert("members", row)
    return object_response(serialize.member(row), 201)


@bp.get("/members/<member_id>")
def read_member(member_id):
    role, uid = authorize((ROLE_BOX, ROLE_EXEC, ROLE_MEMBER))
    member = must_find("members", member_id)
    require_own_member(role, uid, member["id"])
    return object_response(serialize.member(member))


@bp.post("/members/<member_id>/donations")
def lodge_donation(member_id):
    authorize((ROLE_BOX, ROLE_EXEC))
    payload = body()
    amount_cents = req_int(payload, "amount_cents", minimum=0)
    received_at = req_instant(payload, "received_at")
    member = must_find("members", member_id)
    member["donations"].append({"amount_cents": amount_cents, "received_at": received_at})
    refresh_member(member)
    if (member["status"] in ("PENDING", "LAPSED")
            and member["rolling_donation_cents"] >= TIER_BASIC_CENTS):
        member["status"] = "ACTIVE"
    touch(member)
    return object_response(serialize.member(member))


@bp.post("/membership-sweeps")
def membership_sweep():
    authorize((ROLE_EXEC,))
    body()
    evaluated_at = now()
    lapsed_ids = []
    for member in ordered(rows("members")):
        if member["status"] != "ACTIVE":
            continue
        refresh_member(member)
        if member["expires_at"] is not None and member["expires_at"] < evaluated_at:
            member["status"] = "LAPSED"
            refresh_member(member)
            touch(member)
            lapsed_ids.append(member["id"])
    return object_response({
        "swept_count": len(lapsed_ids),
        "lapsed_member_ids": lapsed_ids,
        "evaluated_at": fmt_instant(evaluated_at),
    })
