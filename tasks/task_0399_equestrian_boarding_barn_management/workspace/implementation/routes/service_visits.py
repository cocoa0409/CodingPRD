"""Service visit routes & state machine (PRD §3.7 Service visits)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import err
from middleware import get_caller, require_role
from response import success
from clock import parse_iso, format_iso
from services.common import new_common, touch, require_str, require_int
from services.serialize import view
from services.lookups import get_horse, get_visit, require_owner_owns

bp = Blueprint("service_visits", __name__)


@bp.route("/service-visits", methods=["POST"])
def create_visit():
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner"])
    body = request.get_json(silent=True) or {}
    horse_id = require_str(body, "horse_id")
    visit_type = require_str(body, "visit_type")
    scheduled_at = require_str(body, "scheduled_at")
    duration = require_int(body, "duration_minutes")
    fee = require_int(body, "fee_cents")
    horse = get_horse(horse_id)
    require_owner_owns(caller, horse["owner_id"])
    if visit_type not in ("FARRIER", "VET", "DENTIST"):
        raise err("ERR_INVALID_REQUEST", "visit_type must be FARRIER, VET, or DENTIST")
    if duration <= 0:
        raise err("ERR_INVALID_REQUEST", "duration_minutes must be > 0")
    try:
        sched = parse_iso(scheduled_at)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "scheduled_at must be ISO-8601 UTC")
    visit = new_common()
    visit.update({
        "horse_id": horse["id"],
        "visit_type": visit_type,
        "scheduled_at": format_iso(sched),
        "duration_minutes": duration,
        "fee_cents": fee,
        "invoiced": False,
        "status": "REQUESTED",
    })
    db.visits[visit["id"]] = visit
    return success(view(visit), 201)


_VISIT_TARGET_ROLES = {
    "SCHEDULED": {"BarnManager"},
    "COMPLETED": {"ServiceProvider"},
    "CANCELLED": {"BarnManager", "Owner"},
}


@bp.route("/service-visits/<visit_id>/transition", methods=["POST"])
def transition_visit(visit_id):
    caller = get_caller()
    require_role(caller, ["BarnManager", "Owner", "ServiceProvider"])
    visit = get_visit(visit_id)
    body = request.get_json(silent=True) or {}
    target = body.get("target_status")
    if target not in _VISIT_TARGET_ROLES:
        raise err("ERR_INVALID_STATE", "Unknown or illegal target_status")
    if caller.role not in _VISIT_TARGET_ROLES[target]:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for target %s" % (caller.role, target))
    horse = db.horses.get(visit["horse_id"])
    require_owner_owns(caller, horse["owner_id"] if horse else None)

    if target == "SCHEDULED":
        return _schedule(visit)
    if target == "COMPLETED":
        return _complete(visit)
    return _cancel(visit)


def _window(visit):
    start = parse_iso(visit["scheduled_at"])
    end = start + timedelta(minutes=visit["duration_minutes"])
    return start, end


def _schedule(visit):
    if visit["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Visit is not REQUESTED")
    s1, e1 = _window(visit)
    # pairwise half-open overlap against the SAME horse's SCHEDULED/COMPLETED visits
    for other in db.visits.values():
        if other["id"] == visit["id"]:
            continue
        if other["horse_id"] != visit["horse_id"]:
            continue
        if other["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        s2, e2 = _window(other)
        if s1 < e2 and s2 < e1:  # half-open overlap (touching does not overlap)
            raise err("ERR_VISIT_OVERLAP", "Overlapping SCHEDULED/COMPLETED visit window")
    visit["status"] = "SCHEDULED"
    touch(visit)
    return success(view(visit), 200)


def _complete(visit):
    if visit["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Visit is not SCHEDULED")
    visit["status"] = "COMPLETED"
    touch(visit)
    return success(view(visit), 200)


def _cancel(visit):
    if visit["status"] not in ("REQUESTED", "SCHEDULED"):
        raise err("ERR_INVALID_STATE", "Visit not in REQUESTED or SCHEDULED")
    visit["status"] = "CANCELLED"
    touch(visit)
    return success(view(visit), 200)
