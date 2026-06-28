"""Event block routes: create, list, get, list-appointments, deposit, confirm,
reopen, close, cancel (PRD §3.11)."""

from flask import Blueprint, request

import errors
from common import (
    as_enum, as_int, as_number, get_json_body, paginate, sort_by_created,
    stamp_new, touch,
)
from db import db
from errors import err
from lookup import get_event_block, get_member
from middleware import get_auth, require_role
from response import success_list, success_object
from serialize import public, public_list
from services.reconcile import compute_event_block_deposit

bp = Blueprint("event_blocks", __name__)

TERMINAL_LIFECYCLE = {"COMPLETED", "NO_SHOW", "CANCELLED"}


@bp.post("/event-blocks")
def create_event_block():
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    body = get_json_body()
    organizer_member_id = body.get("organizer_member_id")
    if organizer_member_id is None:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: organizer_member_id")
    organizer = get_member(organizer_member_id)
    block_type = as_enum(body, "block_type", {"GROUP", "BRIDAL"})
    window_start = as_int(body, "window_start_minute")
    window_end = as_int(body, "window_end_minute")
    reserved_chair_ids = body.get("reserved_chair_ids")
    party_size = as_int(body, "party_size")
    gratuity_pct = as_number(body, "gratuity_pct", required=False, default=0.20)

    if window_start < 0 or window_start >= 1440:
        raise err(errors.ERR_INVALID_REQUEST, "window_start_minute must be in [0,1440)")
    if window_end <= window_start or window_end > 1440:
        raise err(errors.ERR_INVALID_REQUEST, "window_end_minute must be > start and <= 1440")
    if not isinstance(reserved_chair_ids, list) or any(not isinstance(x, str) for x in reserved_chair_ids):
        raise err(errors.ERR_INVALID_REQUEST, "reserved_chair_ids must be an array of strings")
    if party_size < 2 or party_size > 20:
        raise err(errors.ERR_INVALID_REQUEST, "party_size must be between 2 and 20")
    if gratuity_pct < 0 or gratuity_pct > 1:
        raise err(errors.ERR_INVALID_REQUEST, "gratuity_pct must be between 0 and 1")

    # validate reserved chairs exist
    for cid in reserved_chair_ids:
        if cid not in db.chairs:
            raise err(errors.ERR_CHAIR_NOT_FOUND, "reserved chair not found: %s" % cid)

    deposit = compute_event_block_deposit(party_size, block_type)
    block = stamp_new({
        "organizer_member_id": organizer_member_id,
        "block_type": block_type,
        "window_start_minute": window_start,
        "window_end_minute": window_end,
        "reserved_chair_ids": reserved_chair_ids,
        "party_size": party_size,
        "deposit_cents": deposit,
        "deposit_paid_cents": 0,
        "gratuity_pct": gratuity_pct,
        "status": "HOLD",
    })
    db.event_blocks[block["id"]] = block
    return success_object(public(block), 201)


@bp.get("/event-blocks")
def list_event_blocks():
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager"})
    items = list(db.event_blocks.values())
    organizer = request.args.get("organizer_member_id")
    if organizer is not None:
        items = [b for b in items if b["organizer_member_id"] == organizer]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.get("/event-blocks/<bid>")
def get_one_event_block(bid):
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager", "Member"})
    block = get_event_block(bid)
    return success_object(public(block), 200)


@bp.get("/event-blocks/<bid>/appointments")
def list_block_appointments(bid):
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager", "Member"})
    block = get_event_block(bid)
    items = [a for a in db.appointments.values() if a.get("event_block_id") == block["id"]]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.post("/event-blocks/<bid>/deposit")
def deposit(bid):
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager"})
    block = get_event_block(bid)
    body = get_json_body()
    amount = as_int(body, "amount_cents")
    if amount < 0:
        raise err(errors.ERR_INVALID_REQUEST, "amount_cents must be >= 0")
    block["deposit_paid_cents"] += amount
    touch(block)
    return success_object(public(block), 200)


@bp.post("/event-blocks/<bid>/confirm")
def confirm(bid):
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    block = get_event_block(bid)
    body = get_json_body()
    expected = as_int(body, "expected_event_block_version")
    if block["status"] != "HOLD":
        raise err(errors.ERR_EVENT_BLOCK_NOT_HOLD, "Event block is not HOLD")
    if block["deposit_paid_cents"] < block["deposit_cents"]:
        raise err(errors.ERR_DEPOSIT_NOT_MET, "Deposit not met")
    booked = sum(1 for a in db.appointments.values()
                 if a.get("event_block_id") == block["id"] and a["lifecycle_status"] == "BOOKED")
    if booked < 2:
        raise err(errors.ERR_BLOCK_UNDERFILLED, "Block requires at least 2 BOOKED appointments")
    if expected != block["version"]:
        raise err(errors.ERR_STALE_VERSION, "expected_event_block_version does not match current version")
    block["status"] = "CONFIRMED"
    touch(block)
    return success_object(public(block), 200)


@bp.post("/event-blocks/<bid>/reopen")
def reopen(bid):
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    block = get_event_block(bid)
    body = get_json_body()
    expected = as_int(body, "expected_event_block_version")
    if block["status"] != "CONFIRMED":
        raise err(errors.ERR_EVENT_BLOCK_NOT_CONFIRMED, "Event block is not CONFIRMED")
    for a in db.appointments.values():
        if a.get("event_block_id") == block["id"] and a["lifecycle_status"] in {"CHECKED_IN", "IN_SERVICE", "COMPLETED"}:
            raise err(errors.ERR_BLOCK_IN_PROGRESS, "A block appointment is already in progress")
    if expected != block["version"]:
        raise err(errors.ERR_STALE_VERSION, "expected_event_block_version does not match current version")
    block["status"] = "HOLD"
    touch(block)
    return success_object(public(block), 200)


@bp.post("/event-blocks/<bid>/close")
def close(bid):
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    block = get_event_block(bid)
    body = get_json_body()
    expected = as_int(body, "expected_event_block_version")
    if block["status"] != "CHECKED_IN":
        raise err(errors.ERR_EVENT_BLOCK_NOT_CLOSEABLE, "Event block is not closeable")
    for a in db.appointments.values():
        if a.get("event_block_id") == block["id"] and a["lifecycle_status"] not in TERMINAL_LIFECYCLE:
            raise err(errors.ERR_BLOCK_HAS_OPEN_APPOINTMENTS, "Block has open appointments")
    if expected != block["version"]:
        raise err(errors.ERR_STALE_VERSION, "expected_event_block_version does not match current version")
    block["status"] = "CLOSED"
    touch(block)
    return success_object(public(block), 200)


@bp.post("/event-blocks/<bid>/cancel")
def cancel_block(bid):
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    block = get_event_block(bid)
    body = get_json_body()
    expected = as_int(body, "expected_event_block_version")
    if block["status"] not in {"HOLD", "CONFIRMED"}:
        raise err(errors.ERR_EVENT_BLOCK_NOT_CANCELLABLE, "Event block is not cancellable")
    if expected != block["version"]:
        raise err(errors.ERR_STALE_VERSION, "expected_event_block_version does not match current version")
    # cascade cancel each BOOKED/CHECKED_IN appointment in the block
    from routes.appointments import _cancel_appointment
    for a in list(db.appointments.values()):
        if a.get("event_block_id") == block["id"] and a["lifecycle_status"] in {"BOOKED", "CHECKED_IN"}:
            _cancel_appointment(a)
    block["status"] = "CANCELLED"
    # deposit_paid_cents retained as forfeited (not refunded)
    touch(block)
    return success_object(public(block), 200)
