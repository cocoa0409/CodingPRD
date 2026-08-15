"""TrainingSession routes."""

from datetime import timedelta
from flask import Blueprint, request

import db
import errors
import services.core as svc
from middleware import require_roles
from response import success_object, success_list
from routes.watch_groups import _pagination

bp = Blueprint("training_sessions", __name__)

ALL_ROLES = ("ProgramCoordinator", "LiaisonOfficer", "BlockCaptain", "Member")

VALID_CURRICULA = {"BIAS_AVOIDANCE", "OBSERVATION_SKILLS", "REPORT_WRITING"}


def _serialize_session(s):
    return {
        "id": s["id"],
        "watch_group_id": s["watch_group_id"],
        "trainer_officer_id": s["trainer_officer_id"],
        "curriculum": s["curriculum"],
        "scheduled_at": s["scheduled_at"],
        "session_status": s["session_status"],
        "attending_member_ids": s.get("attending_member_ids"),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/watch/training-sessions", methods=["POST"])
def create_session():
    user_id, role = require_roles("LiaisonOfficer")
    body = request.get_json(force=True, silent=True) or {}

    watch_group_id = body.get("watch_group_id")
    trainer_officer_id = body.get("trainer_officer_id")
    curriculum = body.get("curriculum")
    scheduled_at = body.get("scheduled_at")

    if not curriculum or curriculum not in VALID_CURRICULA:
        raise errors.invalid_request("Invalid curriculum")
    if not scheduled_at:
        raise errors.invalid_request("scheduled_at is required")
    try:
        sched_dt = db.parse_iso(scheduled_at)
    except Exception:
        raise errors.invalid_request("scheduled_at is not valid ISO-8601")

    # Existence
    g = db.watch_groups.get(watch_group_id) if watch_group_id else None
    if not g:
        raise errors.not_found("WatchGroup not found")
    o = db.liaison_officers.get(trainer_officer_id) if trainer_officer_id else None
    if not o:
        raise errors.not_found("LiaisonOfficer not found")

    # Cooldown check
    cooldown = g.get("training_cooldown_until")
    if cooldown:
        cooldown_dt = db.parse_iso(cooldown)
        if sched_dt < cooldown_dt:
            raise errors.training_cooldown()

    record = {
        "watch_group_id": watch_group_id,
        "trainer_officer_id": trainer_officer_id,
        "curriculum": curriculum,
        "scheduled_at": scheduled_at,
        "session_status": "SCHEDULED",
        "attending_member_ids": None,
    }
    svc.stamp_new(record)
    db.training_sessions[record["id"]] = record
    return success_object(_serialize_session(record), 201)


@bp.route("/watch/training-sessions", methods=["GET"])
def list_sessions():
    user_id, role = require_roles(*ALL_ROLES)

    items = list(db.training_sessions.values())

    wg = request.args.get("watch_group_id")
    if wg:
        items = [s for s in items if s["watch_group_id"] == wg]
    to = request.args.get("trainer_officer_id")
    if to:
        items = [s for s in items if s["trainer_officer_id"] == to]
    ss = request.args.get("session_status")
    if ss:
        items = [s for s in items if s["session_status"] == ss]
    cu = request.args.get("curriculum")
    if cu:
        items = [s for s in items if s["curriculum"] == cu]

    items.sort(key=lambda s: s["created_at"])
    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list([_serialize_session(s) for s in items], limit, offset, total)


@bp.route("/watch/training-sessions/<id>", methods=["GET"])
def get_session(id):
    user_id, role = require_roles(*ALL_ROLES)
    s = db.training_sessions.get(id)
    if not s:
        raise errors.not_found("TrainingSession not found")
    return success_object(_serialize_session(s))


@bp.route("/watch/training-sessions/<id>/complete", methods=["POST"])
def complete_session(id):
    user_id, role = require_roles("LiaisonOfficer")
    s = db.training_sessions.get(id)
    if not s:
        raise errors.not_found("TrainingSession not found")

    if s["session_status"] != "SCHEDULED":
        raise errors.invalid_state("Session is not SCHEDULED")

    # Acting officer must be the trainer
    if user_id != s["trainer_officer_id"]:
        raise errors.unauthorized("Only the trainer may complete the session")

    body = request.get_json(force=True, silent=True) or {}
    attending = body.get("attending_member_ids", [])
    if not attending or not isinstance(attending, list) or len(attending) == 0:
        raise errors.invalid_request("attending_member_ids must be a non-empty list")

    # Every attendee must be an ACTIVE member of the same watch group
    for mid in attending:
        m = db.members.get(mid)
        if not m:
            raise errors.invalid_request(f"Member {mid} not found")
        if m["membership_status"] != "ACTIVE":
            raise errors.invalid_request(f"Member {mid} is not ACTIVE")
        if m["watch_group_id"] != s["watch_group_id"]:
            raise errors.invalid_request(f"Member {mid} does not belong to the same watch group")

    s["session_status"] = "COMPLETED"
    s["attending_member_ids"] = attending
    svc.touch(s)

    # Stamp bias training for attendees
    if s["curriculum"] == "BIAS_AVOIDANCE":
        for mid in attending:
            m = db.members.get(mid)
            if m:
                m["bias_training_completed_at"] = s["scheduled_at"]
                svc.touch(m)

    # Set group cooldown
    g = db.watch_groups.get(s["watch_group_id"])
    if g:
        sched_dt = db.parse_iso(s["scheduled_at"])
        cooldown_end = sched_dt + timedelta(hours=24)
        g["training_cooldown_until"] = db.to_iso(cooldown_end)
        svc.touch(g)

    # Posture recompute
    svc.recompute_posture(s["watch_group_id"])

    return success_object(_serialize_session(s))


@bp.route("/watch/training-sessions/<id>/cancel", methods=["POST"])
def cancel_session(id):
    user_id, role = require_roles("LiaisonOfficer", "ProgramCoordinator")
    s = db.training_sessions.get(id)
    if not s:
        raise errors.not_found("TrainingSession not found")

    if s["session_status"] != "SCHEDULED":
        raise errors.invalid_state("Session is not SCHEDULED")

    s["session_status"] = "CANCELLED"
    svc.touch(s)
    return success_object(_serialize_session(s))
