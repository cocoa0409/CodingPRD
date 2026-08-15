"""Append-only account ledger reads + the logical clock endpoint."""

import clock
import db
import errors
import serializers
from flask import Blueprint, request
from middleware import ALL_ROLES, get_auth, require_roles, parse_json_body, parse_pagination
from response import success_object, success_list
from services import calc

bp = Blueprint("ledger", __name__)


@bp.get("/r2t4/account-entries")
def list_account_entries():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.account_entries.values())
    enrollment_id = request.args.get("enrollment_id")
    entry_type = request.args.get("entry_type")
    reversal_of = request.args.get("reversal_of_entry_id")
    if enrollment_id is not None:
        items = [e for e in items if e["enrollment_id"] == enrollment_id]
    if entry_type is not None:
        items = [e for e in items if e["entry_type"] == entry_type]
    if reversal_of is not None:
        items = [e for e in items if e.get("reversal_of_entry_id") == reversal_of]
    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializers.account_entry(e) for e in page],
                        total, limit, offset)


@bp.get("/r2t4/account-entries/<entry_id>")
def get_account_entry(entry_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    entry = db.account_entries.get(entry_id)
    if entry is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "account entry not found")
    return success_object(serializers.account_entry(entry))


@bp.post("/r2t4/_clock/set_current_utc")
def set_clock():
    auth = get_auth()
    require_roles(auth, ["SystemAdmin"])
    body = parse_json_body()
    value = body.get("to_iso8601")
    if value is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "to_iso8601 is required")
    target = clock.parse_iso_datetime(value)
    if target is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "to_iso8601 must be a valid ISO 8601 datetime")
    if target < clock.now():
        errors.raise_error(errors.ERR_INVALID_FIELD,
                           "the logical clock cannot move backward")
    clock.set_current(target)
    calc.run_deadline_sweep()
    return success_object({"current_utc": clock.now_iso()})
