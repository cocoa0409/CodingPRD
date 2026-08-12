"""The device-seat pool (PRD §3.8)."""

from flask import Blueprint, request

import constants as K
import context
import derive
import envelope
import rows
import serializers
import states
from clock import CLOCK
from context import Ctx
from errors import ApiError
from store import DB, ordered

bp = Blueprint("seats", __name__)

READ_ROLES = [
    K.ROLE_PLATFORM_ADMIN,
    K.ROLE_ACCOUNT_OWNER,
    K.ROLE_MEMBER,
    K.ROLE_AUDITOR,
]


def _addon_of(seat):
    return DB.addons.get(seat["addon_id"])


def _account_of(seat):
    addon = _addon_of(seat)
    return DB.accounts.get(addon["account_id"]) if addon else None


@bp.post("/device-seats")
def bind_seat():
    ctx = Ctx(request, [K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    ctx.load_body()
    fields = ctx.validate(
        [
            {"name": "addon_id", "type": "string", "required": True},
            {"name": "member_id", "type": "string", "required": True},
            {"name": "device_label", "type": "string", "required": True},
            {"name": "expected_addon_version", "type": "integer", "required": True},
        ]
    )
    # Rung 11 -- resolved in the endpoint's declared input order.
    addon = DB.addons.get(fields["addon_id"])
    if addon is None:
        raise ApiError("ERR_ADDON_NOT_FOUND")
    member = DB.members.get(fields["member_id"])
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    account = DB.accounts.get(addon["account_id"])
    # Rung 12
    ctx.own(account["id"], member["id"])
    # Rungs 13-15
    ctx.write_gates(account)
    # Rung 17
    if fields["expected_addon_version"] != addon["version"]:
        raise ApiError("ERR_STALE_ADDON_VERSION")
    # Rung 21
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")
    # Rung 23
    if addon["status"] != "ACTIVE":
        raise ApiError("ERR_ADDON_NOT_ACTIVE")
    # Rung 42 -- STRICT: capacity is seats_total, occupancy counts BOUND only.
    bound, _ = derive.addon_seat_counts(addon)
    if bound >= int(addon["seats_total"]):
        raise ApiError("ERR_SEAT_CAPACITY_EXCEEDED")

    seat = rows.new_row(
        "seats",
        {
            "addon_id": addon["id"],
            "member_id": member["id"],
            "device_label": fields["device_label"],
            "status": "BOUND",
            "bound_at": CLOCK.now,
            "released_at": None,
            "voided_at": None,
            "bind_count": 1,
        },
    )
    rows.touch(addon)
    return envelope.created(serializers.seat(seat))


def _visible(ctx, seat):
    if not ctx.is_scoped_caller:
        return True
    account = _account_of(seat)
    if account is None or account["id"] != ctx.caller_member["account_id"]:
        return False
    if ctx.is_non_primary_member and seat["member_id"] != ctx.caller_member["id"]:
        return False
    return True


@bp.get("/device-seats")
def list_seats():
    ctx = Ctx(request, READ_ROLES)
    status = context.enum_filter(request, "status", K.SEAT_STATUSES)
    limit, offset = context.pagination(request)
    addon_id = context.plain_filter(request, "addon_id")
    member_id = context.plain_filter(request, "member_id")
    result = []
    for seat in DB.seats.values():
        if addon_id is not None and seat["addon_id"] != addon_id:
            continue
        if member_id is not None and seat["member_id"] != member_id:
            continue
        if status is not None and seat["status"] != status:
            continue
        if not _visible(ctx, seat):
            continue
        result.append(seat)
    page, total = context.window(ordered(result), limit, offset)
    return envelope.listing([serializers.seat(s) for s in page], limit, offset, total)


@bp.get("/device-seats/<seat_id>")
def read_seat(seat_id):
    ctx = Ctx(request, READ_ROLES)
    seat = ctx.path("seat", seat_id)
    ctx.own(_account_of(seat)["id"], seat["member_id"])
    return envelope.ok(serializers.seat(seat))


@bp.post("/device-seats/<seat_id>/release")
def release_seat(seat_id):
    ctx = Ctx(request, [K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    seat = ctx.path("seat", seat_id)
    account = _account_of(seat)
    ctx.own(account["id"], seat["member_id"])
    ctx.write_gates(account)
    states.gate("seat_status", seat["status"], ("BOUND",))
    seat["status"] = "RELEASED"
    seat["released_at"] = CLOCK.now
    rows.touch(seat)
    return envelope.ok(serializers.seat(seat))


@bp.post("/device-seats/<seat_id>/rebind")
def rebind_seat(seat_id):
    ctx = Ctx(request, [K.ROLE_ACCOUNT_OWNER, K.ROLE_MEMBER])
    seat = ctx.path("seat", seat_id)
    ctx.load_body()
    fields = ctx.validate([{"name": "device_label", "type": "string", "required": True}])
    account = _account_of(seat)
    ctx.own(account["id"], seat["member_id"])
    ctx.write_gates(account)
    states.gate("seat_status", seat["status"], ("RELEASED",))
    addon = _addon_of(seat)
    # Rung 23
    if addon["status"] != "ACTIVE":
        raise ApiError("ERR_ADDON_NOT_ACTIVE")
    # Rung 31 -- INCLUSIVE boundary at released_at + 72h.
    eligible_at = derive.seat_rebind_eligible_at(seat)
    if eligible_at is not None and CLOCK.now < eligible_at:
        raise ApiError("ERR_SEAT_REBIND_COOLOFF")
    # Rung 42
    bound, _ = derive.addon_seat_counts(addon)
    if bound >= int(addon["seats_total"]):
        raise ApiError("ERR_SEAT_CAPACITY_EXCEEDED")
    seat["status"] = "BOUND"
    seat["device_label"] = fields["device_label"]
    seat["bound_at"] = CLOCK.now
    seat["released_at"] = None
    seat["bind_count"] = seat["bind_count"] + 1
    rows.touch(seat)
    return envelope.ok(serializers.seat(seat))
