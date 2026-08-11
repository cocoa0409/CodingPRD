"""Pausing the subscription (PRD 3.10)."""

from flask import Blueprint

import auth
import calc
import constants as K
import derive
import envelope
import ledger
import listing
import lookup
import serialize
import shape
import store
import timeutil
from errors import ApiError

bp = Blueprint("pauses", __name__)


@bp.post("/kidswear/members/<member_id>/pause-requests")
def create_pause_request(member_id):
    caller = auth.gate("Member")
    body = shape.body_json()
    start_at = shape.instant(body, "start_at")
    days_requested = shape.integer(body, "days_requested")
    auth.own(caller, member_id)
    member = lookup.member(member_id)
    lookup.standing(member)
    if days_requested < K.PAUSE_MIN_DAYS or days_requested > K.PAUSE_MAX_DAYS_PER_PERIOD:
        raise ApiError("ERR_PAUSE_DAYS_OUT_OF_RANGE")
    row = store.insert("pause_requests", {
        "member_id": member_id,
        "status": "REQUESTED",
        "start_at": start_at,
        "days_requested": days_requested,
        "end_at": timeutil.add_days(start_at, days_requested),
        "proration_credit_cents": 0,
        "denial_reason": None,
    })
    return envelope.created(serialize.pause_request(row))


@bp.get("/kidswear/pause-requests")
def list_pause_requests():
    caller = auth.gate("Member", "PlatformAdmin", "BillingAgent")
    rows = store.all_rows("pause_requests")
    rows = listing.scope_to_member(caller, rows, lambda r: r["member_id"])
    rows = listing.eq(rows, "member_id", shape.query_str("member_id"))
    rows = listing.eq(rows, "status", shape.query_member("status", K.PAUSE_STATUSES))
    return envelope.listing(rows, serialize.pause_request)


@bp.get("/kidswear/pause-requests/<pause_request_id>")
def read_pause_request(pause_request_id):
    caller = auth.gate("Member", "PlatformAdmin", "BillingAgent")
    row = lookup.pause_request(pause_request_id)
    auth.own(caller, row["member_id"])
    return envelope.ok(serialize.pause_request(row))


@bp.post("/kidswear/pause-requests/<pause_request_id>/activate")
def activate_pause(pause_request_id):
    auth.gate("BillingAgent", "PlatformAdmin")
    request = lookup.pause_request(pause_request_id)
    member = lookup.member(request["member_id"])
    lookup.standing(member)
    if request["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "The member is not ACTIVE.")
    for shipment in store.all_rows("shipments"):
        if shipment["member_id"] == member["id"] and shipment["status"] == "IN_TRANSIT":
            raise ApiError("ERR_SHIPMENT_IN_TRANSIT_BLOCKS_PAUSE")
    for item in derive.member_box_items(member["id"]):
        if item["days_late"] > 0:
            raise ApiError("ERR_UNIT_PAST_DUE_BLOCKS_PAUSE")
    days = request["days_requested"]
    if derive.pause_days_used_period(member["id"]) + days > K.PAUSE_MAX_DAYS_PER_PERIOD:
        raise ApiError("ERR_PAUSE_PERIOD_CAP_EXCEEDED")
    if derive.pause_days_used_lifetime(member["id"]) + days > K.PAUSE_MAX_DAYS_LIFETIME:
        raise ApiError("ERR_PAUSE_LIFETIME_CAP_EXCEEDED")
    for other in store.all_rows("pause_requests"):
        if other["id"] == request["id"] or other["member_id"] != member["id"]:
            continue
        if other["status"] not in ("ACTIVE", "ENDED"):
            continue
        if request["start_at"] < other["end_at"] and other["start_at"] < request["end_at"]:
            raise ApiError("ERR_WINDOW_OVERLAP")

    request["status"] = "ACTIVE"
    plan = lookup.plan(member["plan_id"])
    credit = 0
    for cycle in store.all_rows("cycles"):
        if cycle["member_id"] != member["id"] or cycle["status"] not in ("SCHEDULED", "OPEN"):
            continue
        overlap = timeutil.days_overlap(request["start_at"], request["end_at"],
                                        cycle["start_at"], cycle["return_due_at"])
        if overlap <= 0:
            continue
        credit = calc.pause_proration(plan, overlap)
        cycle["proration_credit_cents"] = credit
        store.touch(cycle)
        break
    request["proration_credit_cents"] = credit
    store.touch(request)
    for entry in derive.member_credits(member["id"]):
        if entry["status"] in ("AVAILABLE", "PARTIALLY_APPLIED"):
            entry["paused_days_extension"] += days
            entry["expires_at"] = ledger.credit_expires_at(entry)
            store.touch(entry)
    member["status"] = "PAUSED"
    store.touch(member)
    return envelope.ok(serialize.pause_request(request))


@bp.post("/kidswear/pause-requests/<pause_request_id>/end")
def end_pause(pause_request_id):
    caller = auth.gate("Member", "PlatformAdmin")
    request = lookup.pause_request(pause_request_id)
    auth.own(caller, request["member_id"])
    member = lookup.member(request["member_id"])
    lookup.standing(member)
    if request["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    if member["status"] != "PAUSED":
        raise ApiError("ERR_INVALID_STATE", "The member is not PAUSED.")
    request["status"] = "ENDED"
    store.touch(request)
    member["status"] = "ACTIVE"
    store.touch(member)
    scheduled = [c for c in store.all_rows("cycles")
                 if c["member_id"] == member["id"] and c["status"] == "SCHEDULED"]
    scheduled.sort(key=lambda c: c["cycle_index"])
    for cycle in scheduled:
        new_start = max(cycle["start_at"], request["end_at"])
        cycle["start_at"] = new_start
        (cycle["swap_by_at"], cycle["return_due_at"],
         cycle["grace_ends_at"]) = calc.cycle_windows(new_start)
        store.touch(cycle)
    return envelope.ok(serialize.pause_request(request))


@bp.post("/kidswear/pause-requests/<pause_request_id>/cancel")
def cancel_pause(pause_request_id):
    caller = auth.gate("Member")
    request = lookup.pause_request(pause_request_id)
    auth.own(caller, request["member_id"])
    member = lookup.member(request["member_id"])
    lookup.standing(member)
    if request["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    request["status"] = "CANCELLED"
    store.touch(request)
    return envelope.ok(serialize.pause_request(request))


@bp.post("/kidswear/pause-requests/<pause_request_id>/deny")
def deny_pause(pause_request_id):
    auth.gate("PlatformAdmin")
    body = shape.body_json()
    denial_reason = shape.enum_in(body, "denial_reason", K.PAUSE_DENIAL_REASONS)
    request = lookup.pause_request(pause_request_id)
    member = lookup.member(request["member_id"])
    lookup.standing(member)
    if request["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    request["status"] = "DENIED"
    request["denial_reason"] = denial_reason
    store.touch(request)
    return envelope.ok(serialize.pause_request(request))
