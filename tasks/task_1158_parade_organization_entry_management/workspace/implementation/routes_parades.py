"""ParadeEvent lifecycle endpoints and the test-driving logical clock."""
from flask import Blueprint, request

import db
from auth import ALL_ROLES, guarded
from db import STORE, make_record, touch
from errors import api_err
from logic import (
    LIVE_LINEUP_STATUSES,
    TIER_MIN_SECONDS,
    allocated_seconds,
    ensure_not_frozen,
    lock_approved_script_items,
    parade_cancel_cascade,
    parade_complete_cascade,
    parade_or_404,
    parade_posture,
    permit_of,
    ser_parade,
)
from util import body, fmt_clock, paged, parse_dt, req_dt, req_int, req_str, respond_object

bp = Blueprint("parades", __name__)

CA = ("CommitteeAdmin",)


def add(rule, methods, view):
    bp.add_url_rule(rule, view_func=view, methods=methods, strict_slashes=False)


# --- Clock -----------------------------------------------------------------

def set_current_utc(uid, role):
    data = body()
    raw = data.get("to_iso8601")
    if raw is None:
        raise api_err("ERR_VALIDATION", "to_iso8601 is required")
    db.set_clock(parse_dt(raw, "to_iso8601"))
    return respond_object({"current_utc": fmt_clock(db.now())})


add("/_clock/set_current_utc", ["POST"], guarded(CA)(set_current_utc))


# --- ParadeEvent -------------------------------------------------------------

def create_parade(uid, role):
    data = body()
    name = req_str(data, "name")
    parade_date = req_dt(data, "parade_date")
    entry_deadline = req_dt(data, "entry_deadline")
    rec = make_record()
    rec.update(
        {
            "name": name,
            "parade_date": parade_date,
            "entry_deadline": entry_deadline,
            "status": "DRAFT",
            "script_finalized": False,
        }
    )
    STORE.parades[rec["id"]] = rec
    return respond_object(ser_parade(rec), 201)


def list_parades(uid, role):
    items = list(STORE.parades.values())
    status = request.args.get("status")
    posture = request.args.get("posture")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if posture is not None:
        items = [p for p in items if parade_posture(p) == posture]
    return paged(items, ser_parade)


def get_parade(uid, role, id):
    return respond_object(ser_parade(parade_or_404(id)))


def submit_permit(uid, role, id):
    parade = parade_or_404(id)
    if parade["status"] != "DRAFT":
        raise api_err("ERR_INVALID_STATE", "Parade must be in DRAFT to submit the permit step")
    if not any(s["parade_id"] == id for s in STORE.route_segments.values()):
        raise api_err("ERR_INVALID_STATE", "At least one route segment is required")
    if not any(s["parade_id"] == id for s in STORE.staging_areas.values()):
        raise api_err("ERR_INVALID_STATE", "At least one staging area is required")
    parade["status"] = "PERMIT_PENDING"
    touch(parade)
    return respond_object(ser_parade(parade))


def lock_parade(uid, role, id):
    parade = parade_or_404(id)
    permit = permit_of(id)
    if permit is None or permit["status"] != "GRANTED":
        raise api_err("ERR_PERMIT_NOT_GRANTED", "Lock requires the permit in GRANTED")
    if parade["status"] != "PERMIT_GRANTED":
        raise api_err("ERR_INVALID_STATE", "Parade must be in PERMIT_GRANTED to lock")
    if parade_posture(parade) != "OPERATIONAL":
        raise api_err("ERR_INVALID_STATE", "Lock requires an OPERATIONAL posture")
    parade["status"] = "LOCKED"
    touch(parade)
    return respond_object(ser_parade(parade))


def publish_lineup(uid, role, id):
    parade = parade_or_404(id)
    data = body()
    expected = req_int(data, "expected_parade_version")
    if parade_posture(parade) == "FROZEN":
        raise api_err("ERR_EVENT_FROZEN", "ParadeEvent posture is FROZEN")
    if not any(
        a["parade_id"] == id and a["status"] in LIVE_LINEUP_STATUSES
        for a in STORE.lineup_assignments.values()
    ):
        raise api_err("ERR_INVALID_STATE", "No active lineup assignment exists")
    if expected != parade["version"]:
        raise api_err("ERR_STALE_VERSION", "expected_parade_version does not match the current version")
    if parade["status"] != "LOCKED":
        raise api_err("ERR_INVALID_STATE", "Parade must be in LOCKED to publish the lineup")
    parade["status"] = "LINEUP_PUBLISHED"
    touch(parade)
    lock_approved_script_items(id)
    return respond_object(ser_parade(parade))


def complete_parade(uid, role, id):
    parade = parade_or_404(id)
    if parade["status"] != "LINEUP_PUBLISHED":
        raise api_err("ERR_INVALID_STATE", "Parade must be in LINEUP_PUBLISHED to complete")
    if any(
        a["parade_id"] == id and a["status"] not in ("RELEASED", "PULLED", "NO_SHOW")
        for a in STORE.lineup_assignments.values()
    ):
        raise api_err("ERR_INVALID_STATE", "Every lineup assignment must be in a terminal state")
    parade_complete_cascade(parade)
    parade["status"] = "COMPLETED"
    touch(parade)
    return respond_object(ser_parade(parade))


def cancel_parade(uid, role, id):
    parade = parade_or_404(id)
    if parade["status"] not in ("DRAFT", "PERMIT_PENDING", "PERMIT_GRANTED", "LOCKED", "LINEUP_PUBLISHED"):
        raise api_err("ERR_INVALID_STATE", "Parade is already in a terminal state")
    parade_cancel_cascade(parade)
    parade["status"] = "CANCELLED"
    touch(parade)
    return respond_object(ser_parade(parade))


def finalize_script(uid, role, id):
    parade = parade_or_404(id)
    for s in STORE.sponsors.values():
        if s["parade_id"] == id and s["status"] == "ACTIVE":
            if allocated_seconds(s["id"]) < TIER_MIN_SECONDS[s["tier"]]:
                raise api_err(
                    "ERR_SPONSOR_MINUTES_UNMET",
                    "An ACTIVE sponsor has not met its tier minimum seconds",
                )
    parade["script_finalized"] = True
    touch(parade)
    return respond_object(ser_parade(parade))


add("/parades", ["POST"], guarded(CA)(create_parade))
add("/parades", ["GET"], guarded(ALL_ROLES)(list_parades))
add("/parades/<id>", ["GET"], guarded(ALL_ROLES)(get_parade))
add("/parades/<id>/submit-permit", ["POST"], guarded(CA)(submit_permit))
add("/parades/<id>/lock", ["POST"], guarded(CA)(lock_parade))
add("/parades/<id>/publish-lineup", ["POST"], guarded(CA)(publish_lineup))
add("/parades/<id>/complete", ["POST"], guarded(CA)(complete_parade))
add("/parades/<id>/cancel", ["POST"], guarded(CA)(cancel_parade))
add("/parades/<id>/finalize-script", ["POST"], guarded(CA)(finalize_script))
