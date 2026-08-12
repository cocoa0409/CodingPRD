"""Households, members and account standing (PRD 3.1)."""

from flask import Blueprint, request

import serializers as S
from envelope import created, ok, ok_list, paginate, read_pagination
from errors import ApiError
from ladder import (begin, gates, household_subscription, invalid_state, occ,
                    req_enum, req_id, req_region, req_str, resolve, scope_household, touch)
from store import clock, db, new_row, sort_rows

bp = Blueprint("households", __name__)
PREFIX = "/smart-home-support"

READ_ALL = ("PlatformAdmin", "SupportAgent", "Owner", "Member", "BillingAdmin")


@bp.post(PREFIX + "/households")
def register_household():
    ctx = begin(("PlatformAdmin",))
    # Rung 20 -- shape.  Household registration is exempt from every gate.
    name = req_str(ctx.body, "name", 1, 120)
    region_code = req_region(ctx.body)
    billing_email = req_str(ctx.body, "billing_email", 1)

    row = new_row()
    row.update({
        "name": name,
        "region_code": region_code,
        "billing_email": billing_email,
        "account_status": "ACTIVE",
        "suspended_at": None,
        "entitled_device_count": 0,
        "active_device_count": 0,
    })
    db.households[row["id"]] = row
    return created(S.household(row))


@bp.get(PREFIX + "/households/<hid>")
def read_household(hid):
    ctx = begin(READ_ALL)
    found = resolve(household=hid)
    scope_household(ctx, hid)
    return ok(S.household(found["household"]))


@bp.post(PREFIX + "/households/<hid>/account-status")
def set_account_status(hid):
    ctx = begin(("PlatformAdmin",))
    found = resolve(household=hid)
    household = found["household"]
    # Rung 21 -- account_status is one of the fields that routes to the enum
    # error; every other bad value on this endpoint is ERR_INVALID_REQUEST.
    target = req_enum(ctx.body, "account_status")
    # The account-status endpoint is exempt from gates 1 and 4 -- that
    # exemption is what makes a suspended account reinstatable (PRD 2.8).
    current = household["account_status"]
    if target == "SUSPENDED":
        if current != "ACTIVE":
            invalid_state("Only an ACTIVE household may be suspended.")
        household["account_status"] = "SUSPENDED"
        household["suspended_at"] = clock.now_iso()
    elif target == "ACTIVE":
        if current != "SUSPENDED":
            invalid_state("Only a SUSPENDED household may be reinstated.")
        household["account_status"] = "ACTIVE"
        household["suspended_at"] = None
    else:  # CLOSED
        if current != "ACTIVE":
            invalid_state("Only an ACTIVE household may be closed.")
        sub = household_subscription(hid)
        if sub is None or sub.get("status") != "CANCELLED":
            invalid_state("A household may only be closed once its subscription is CANCELLED.")
        household["account_status"] = "CLOSED"
    touch(household)
    return ok(S.household(household))


@bp.post(PREFIX + "/households/<hid>/members")
def add_member(hid):
    ctx = begin(("PlatformAdmin", "Owner"))
    found = resolve(household=hid)
    household = found["household"]
    scope_household(ctx, hid)
    full_name = req_str(ctx.body, "full_name", 1)
    email = req_str(ctx.body, "email", 1)
    member_role = req_enum(ctx.body, "member_role")
    gates(household=household)

    row = new_row()
    row.update({
        "household_id": hid,
        "full_name": full_name,
        "email": email,
        "member_role": member_role,
        "is_active": True,
    })
    db.household_members[row["id"]] = row
    return created(S.household_member(row))


@bp.get(PREFIX + "/household-members")
def list_members():
    begin(READ_ALL)
    limit, offset = read_pagination(request.args)
    household_id = request.args.get("household_id")
    rows = [r for r in db.household_members.values()
            if household_id is None or r.get("household_id") == household_id]
    page, total = paginate(sort_rows(rows), limit, offset)
    return ok_list([S.household_member(r) for r in page], limit, offset, total)


@bp.get(PREFIX + "/household-members/<mid>")
def read_member(mid):
    ctx = begin(READ_ALL)
    row = db.household_members.get(mid)
    if row is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    scope_household(ctx, row.get("household_id"))
    return ok(S.household_member(row))
