"""LiaisonMeeting routes."""

from flask import Blueprint, request

import db
import errors
import services.core as svc
from middleware import require_roles
from response import success_object, success_list
from routes.watch_groups import _pagination

bp = Blueprint("liaison_meetings", __name__)

ALL_ROLES = ("ProgramCoordinator", "LiaisonOfficer", "BlockCaptain", "Member")


def _serialize_meeting(m):
    return {
        "id": m["id"],
        "watch_group_id": m["watch_group_id"],
        "liaison_officer_id": m["liaison_officer_id"],
        "room_slot_start": m["room_slot_start"],
        "room_slot_end": m["room_slot_end"],
        "meeting_status": m["meeting_status"],
        "quorum_met": m["quorum_met"],
        "attendee_count": m.get("attendee_count"),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


@bp.route("/watch/liaison-meetings", methods=["POST"])
def create_meeting():
    user_id, role = require_roles("LiaisonOfficer")
    body = request.get_json(force=True, silent=True) or {}

    watch_group_id = body.get("watch_group_id")
    liaison_officer_id = body.get("liaison_officer_id")
    room_slot_start = body.get("room_slot_start")
    room_slot_end = body.get("room_slot_end")

    # Field-level validation
    if not room_slot_start or not room_slot_end:
        raise errors.invalid_request("room_slot_start and room_slot_end are required")
    try:
        start_dt = db.parse_iso(room_slot_start)
        end_dt = db.parse_iso(room_slot_end)
    except Exception:
        raise errors.invalid_request("Invalid datetime format")
    if end_dt <= start_dt:
        raise errors.invalid_request("room_slot_end must be > room_slot_start")

    # Existence
    g = db.watch_groups.get(watch_group_id) if watch_group_id else None
    if not g:
        raise errors.not_found("WatchGroup not found")
    o = db.liaison_officers.get(liaison_officer_id) if liaison_officer_id else None
    if not o:
        raise errors.not_found("LiaisonOfficer not found")

    # Room slot conflict check (half-open interval, same precinct)
    for mt in db.liaison_meetings.values():
        if mt["meeting_status"] not in ("SCHEDULED", "HELD"):
            continue
        # Check same precinct (via the meeting's watch group)
        mt_group = db.watch_groups.get(mt["watch_group_id"])
        if not mt_group or mt_group["precinct_code"] != g["precinct_code"]:
            continue
        mt_start = db.parse_iso(mt["room_slot_start"])
        mt_end = db.parse_iso(mt["room_slot_end"])
        # Half-open overlap: [start, end) overlaps [mt_start, mt_end)
        # No overlap iff end <= mt_start or start >= mt_end
        if not (end_dt <= mt_start or start_dt >= mt_end):
            raise errors.room_slot_conflict()

    record = {
        "watch_group_id": watch_group_id,
        "liaison_officer_id": liaison_officer_id,
        "room_slot_start": room_slot_start,
        "room_slot_end": room_slot_end,
        "meeting_status": "SCHEDULED",
        "quorum_met": False,
        "attendee_count": None,
    }
    svc.stamp_new(record)
    db.liaison_meetings[record["id"]] = record
    return success_object(_serialize_meeting(record), 201)


@bp.route("/watch/liaison-meetings", methods=["GET"])
def list_meetings():
    user_id, role = require_roles(*ALL_ROLES)

    items = list(db.liaison_meetings.values())

    wg = request.args.get("watch_group_id")
    if wg:
        items = [m for m in items if m["watch_group_id"] == wg]
    lo = request.args.get("liaison_officer_id")
    if lo:
        items = [m for m in items if m["liaison_officer_id"] == lo]
    ms = request.args.get("meeting_status")
    if ms:
        items = [m for m in items if m["meeting_status"] == ms]

    items.sort(key=lambda m: m["created_at"])
    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list([_serialize_meeting(m) for m in items], limit, offset, total)


@bp.route("/watch/liaison-meetings/<id>", methods=["GET"])
def get_meeting(id):
    user_id, role = require_roles(*ALL_ROLES)
    m = db.liaison_meetings.get(id)
    if not m:
        raise errors.not_found("LiaisonMeeting not found")
    return success_object(_serialize_meeting(m))


@bp.route("/watch/liaison-meetings/<id>/mark-held", methods=["POST"])
def mark_held(id):
    user_id, role = require_roles("LiaisonOfficer")
    m = db.liaison_meetings.get(id)
    if not m:
        raise errors.not_found("LiaisonMeeting not found")

    if m["meeting_status"] != "SCHEDULED":
        raise errors.invalid_state("Meeting is not SCHEDULED")

    # Acting officer must be the chairing officer
    if user_id != m["liaison_officer_id"]:
        raise errors.unauthorized("Only the chairing officer may mark a meeting held")

    # Clock must have reached room_slot_start
    start_dt = db.parse_iso(m["room_slot_start"])
    if db.get_clock() < start_dt:
        raise errors.invalid_state("Meeting has not yet started")

    body = request.get_json(force=True, silent=True) or {}
    attendee_count = body.get("attendee_count")
    if attendee_count is None or not isinstance(attendee_count, int) or attendee_count < 0:
        raise errors.invalid_request("attendee_count must be a non-negative integer")

    # Compute quorum (pinned order: snapshot active count, compute threshold, compare)
    quorum_met = svc.compute_quorum(m["watch_group_id"], attendee_count)

    m["meeting_status"] = "HELD"
    m["quorum_met"] = quorum_met
    m["attendee_count"] = attendee_count
    svc.touch(m)

    # Participation score recompute when quorum met
    if quorum_met:
        svc.recompute_posture(m["watch_group_id"])

    return success_object(_serialize_meeting(m))


@bp.route("/watch/liaison-meetings/<id>/cancel", methods=["POST"])
def cancel_meeting(id):
    user_id, role = require_roles("LiaisonOfficer", "ProgramCoordinator")
    m = db.liaison_meetings.get(id)
    if not m:
        raise errors.not_found("LiaisonMeeting not found")

    if m["meeting_status"] != "SCHEDULED":
        raise errors.invalid_state("Meeting is not SCHEDULED")

    m["meeting_status"] = "CANCELLED"
    svc.touch(m)
    return success_object(_serialize_meeting(m))
