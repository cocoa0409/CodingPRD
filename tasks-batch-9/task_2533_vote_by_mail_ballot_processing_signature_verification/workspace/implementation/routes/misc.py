"""Transparency log reads and the logical clock."""
from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from errors import ApiError

bp = Blueprint("misc", __name__)

READ_ROLES = ("ElectionsAdmin", "ElectionsClerk", "CanvassSupervisor", "Observer")


@bp.get("/transparency-log/<entry_id>")
def get_log_entry(entry_id):
    mw.require_roles(*READ_ROLES)
    return response.record_response(lookups.transparency_entry(entry_id))


@bp.get("/transparency-log")
def list_log_entries():
    mw.require_roles(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.apply_filters(
        list(db.transparency_log.values()),
        ["election_id", "event_type", "actor_role", "subject_id"],
    )
    # Append order, which is sequence ASC and agrees with created_at ASC.
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/_clock/set_current_utc")
def set_clock():
    mw.require_roles("ElectionsAdmin")
    payload = mw.body()
    to_iso8601 = mw.require_datetime(payload, "to_iso8601")
    if to_iso8601 <= db.now():
        raise ApiError("ERR_CLOCK_REWIND_FORBIDDEN")
    db.set_now(to_iso8601)
    return response.object_response({"current_utc": db.iso(db.now())})
