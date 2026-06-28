"""OnCallAssignment routes: assign primary, name-backup, go-on-duty, release."""
from flask import Blueprint, request

from db import db
from common import (stamp_new, touch, public, paginate, get_body,
                    require_string, require_datetime, parse_dt)
from errors import (err, ERR_INVALID_STATE, ERR_PROVIDER_AT_CAPACITY,
                    ERR_PROVIDER_WINDOW_OVERLAP, ERR_BACKUP_SAME_PROVIDER)
from middleware import require_auth, require_role, ALL_ROLES
from response import object_response, array_response
import lookup
from services import calc

bp = Blueprint("oncall", __name__)


def _windows_overlap(s1, e1, s2, e2):
    """Closed-interval overlap [s1,e1] vs [s2,e2]: touching endpoints collide."""
    return s1 <= e2 and s2 <= e1


@bp.route("/birth-center/on-call-assignments", methods=["POST"])
def create_assignment():
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    body = get_body()
    episode_id = require_string(body, "episode_id")
    provider_id = require_string(body, "provider_id")
    coverage_start = require_datetime(body, "coverage_start")
    coverage_end = require_datetime(body, "coverage_end")
    lookup.get_episode(episode_id)
    provider = lookup.get_provider(provider_id)

    # Capacity gate (priority 10): primary load < max_active_episodes.
    if calc.primary_load(provider_id) >= provider["max_active_episodes"]:
        raise err(ERR_PROVIDER_AT_CAPACITY, "Provider at primary capacity")

    # Window overlap gate (priority 11): closed-interval, against provider's
    # PRIMARY windows in {ASSIGNED, ON_DUTY, PROMOTED}.
    s_new = parse_dt(coverage_start, "coverage_start")
    e_new = parse_dt(coverage_end, "coverage_end")
    for a in db.on_call_assignments.values():
        if a["provider_id"] != provider_id:
            continue
        if a["coverage_role"] != "PRIMARY":
            continue
        if a["status"] not in ("ASSIGNED", "ON_DUTY", "PROMOTED"):
            continue
        s_old = parse_dt(a["coverage_start"], "coverage_start")
        e_old = parse_dt(a["coverage_end"], "coverage_end")
        if _windows_overlap(s_new, e_new, s_old, e_old):
            raise err(ERR_PROVIDER_WINDOW_OVERLAP, "Coverage window overlaps existing primary window")

    rec = {
        "episode_id": episode_id,
        "provider_id": provider_id,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "backup_assignment_id": None,
        "coverage_role": "PRIMARY",
        "status": "ASSIGNED",
    }
    stamp_new(rec)
    db.on_call_assignments[rec["id"]] = rec
    provider["active_assignment_count"] += 1
    touch(provider)
    return object_response(public(rec), 201)


@bp.route("/birth-center/on-call-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    rec = lookup.get_assignment(aid)
    return object_response(public(rec), 200)


@bp.route("/birth-center/on-call-assignments", methods=["GET"])
def list_assignments():
    _, role = require_auth()
    require_role(role, ALL_ROLES)
    provider_id = request.args.get("provider_id")
    backup_assignment_id = request.args.get("backup_assignment_id")
    episode_id = request.args.get("episode_id")
    coverage_role = request.args.get("coverage_role")
    status = request.args.get("status")
    records = [r for r in db.on_call_assignments.values()
               if (provider_id is None or r["provider_id"] == provider_id)
               and (backup_assignment_id is None or r.get("backup_assignment_id") == backup_assignment_id)
               and (episode_id is None or r["episode_id"] == episode_id)
               and (coverage_role is None or r["coverage_role"] == coverage_role)
               and (status is None or r["status"] == status)]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)


@bp.route("/birth-center/on-call-assignments/<aid>/name-backup", methods=["POST"])
def name_backup(aid):
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    primary = lookup.get_assignment(aid)
    body = get_body()
    provider_id = require_string(body, "provider_id")
    coverage_start = require_datetime(body, "coverage_start")
    coverage_end = require_datetime(body, "coverage_end")
    provider = lookup.get_provider(provider_id)
    # backup provider must differ from primary's provider (priority 9)
    if provider_id == primary["provider_id"]:
        raise err(ERR_BACKUP_SAME_PROVIDER, "Backup provider equals primary's provider")

    backup = {
        "episode_id": primary["episode_id"],
        "provider_id": provider_id,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "backup_assignment_id": None,
        "coverage_role": "BACKUP",
        "status": "ASSIGNED",
    }
    stamp_new(backup)
    db.on_call_assignments[backup["id"]] = backup
    # Link the primary to the new backup (primary is mutated).
    primary["backup_assignment_id"] = backup["id"]
    touch(primary)
    # BACKUP rows do not consume primary capacity; no active count change.
    return object_response(public(backup), 201)


@bp.route("/birth-center/on-call-assignments/<aid>/go-on-duty", methods=["POST"])
def go_on_duty(aid):
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    rec = lookup.get_assignment(aid)
    if rec["status"] != "ASSIGNED" or rec["coverage_role"] != "PRIMARY":
        raise err(ERR_INVALID_STATE, "Assignment cannot go on duty from this state")
    episode = db.episodes.get(rec["episode_id"])
    if episode is None or episode["clinical_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Episode is not ACTIVE")
    rec["status"] = "ON_DUTY"
    touch(rec)
    return object_response(public(rec), 200)


@bp.route("/birth-center/on-call-assignments/<aid>/release", methods=["POST"])
def release(aid):
    _, role = require_auth()
    require_role(role, ["CenterAdmin"])
    rec = lookup.get_assignment(aid)
    if rec["status"] not in ("ASSIGNED", "ON_DUTY") or rec["coverage_role"] != "PRIMARY":
        raise err(ERR_INVALID_STATE, "Assignment cannot be released from this state")
    episode = db.episodes.get(rec["episode_id"])
    if episode is None or episode["clinical_status"] not in ("BORN", "COMPLETED", "TRANSFERRED"):
        raise err(ERR_INVALID_STATE, "Episode coverage still needed")
    rec["status"] = "RELEASED"
    touch(rec)
    provider = db.providers.get(rec["provider_id"])
    if provider is not None:
        provider["active_assignment_count"] = max(0, provider["active_assignment_count"] - 1)
        touch(provider)
    return object_response(public(rec), 200)
