"""CalendarSlot routes (PRD §3.12)."""
from flask import Blueprint, request

import errors
import serializers
from db import db
from response import success_object, success_array
from middleware import get_auth, require_role, ROLE_ADMIN, ROLE_OWNER
from common import (get_body, make_record, paginate, public, touch,
                    as_str, as_int)
from services.lookups import find_or_404, require_account_owner
from services.timeutil import parse_dt

bp = Blueprint("calendar_slots", __name__)


@bp.route("/va/calendar-slots", methods=["POST"])
def create_slot():
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER})
    body = get_body()

    account_id = as_str(body, "account_id", required=True)
    account = find_or_404(db.accounts, account_id)
    require_account_owner(account["id"], user_id, role)

    window_start = as_str(body, "window_start", required=True)
    window_end = as_str(body, "window_end", required=True)
    ws = parse_dt(window_start, "window_start")
    we = parse_dt(window_end, "window_end")
    if we <= ws:
        raise errors.err(errors.ERR_INVALID_REQUEST, "window_end must be after window_start")
    buffer_minutes = as_int(body, "buffer_minutes", default=0, minimum=0)
    capacity = as_int(body, "capacity", default=1, minimum=1)

    rec = make_record({
        "account_id": account_id,
        "window_start": window_start,
        "window_end": window_end,
        "buffer_minutes": buffer_minutes,
        "capacity": capacity,
        "booked_count": 0,
        "available_count": capacity,
        "status": "OPEN",
    })
    db.calendar_slots[rec["id"]] = rec
    return success_object(serializers.calendar_slot(public(rec)), 201)


@bp.route("/va/calendar-slots/<slot_id>", methods=["GET"])
def get_slot(slot_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    rec = find_or_404(db.calendar_slots, slot_id)
    require_account_owner(rec["account_id"], user_id, role)
    return success_object(serializers.calendar_slot(public(rec)), 200)


@bp.route("/va/calendar-slots", methods=["GET"])
def list_slots():
    user_id, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    records = list(db.calendar_slots.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        records = [r for r in records if r["account_id"] == account_id]
    if role == ROLE_OWNER:
        records = [r for r in records if r["account_id"] == user_id]
    page, meta = paginate(records)
    return success_array([serializers.calendar_slot(public(r)) for r in page], meta, 200)


@bp.route("/va/calendar-slots/<slot_id>/close", methods=["POST"])
def close_slot(slot_id):
    user_id, role = get_auth()
    require_role(role, {ROLE_OWNER})
    rec = find_or_404(db.calendar_slots, slot_id)
    require_account_owner(rec["account_id"], user_id, role)
    if rec["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Slot is not OPEN")
    rec["status"] = "CLOSED"
    touch(rec)
    return success_object(serializers.calendar_slot(public(rec)), 200)
