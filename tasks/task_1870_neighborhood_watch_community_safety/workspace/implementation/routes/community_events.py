"""CommunityEvent routes."""

from datetime import timedelta
from flask import Blueprint, request

import db
import errors
import services.core as svc
from middleware import require_roles
from response import success_object, success_list
from routes.watch_groups import _pagination

bp = Blueprint("community_events", __name__)

ALL_ROLES = ("ProgramCoordinator", "LiaisonOfficer", "BlockCaptain", "Member")

VALID_KINDS = {"NATIONAL_NIGHT_OUT", "BLOCK_PARTY", "SAFETY_FAIR"}
PERMIT_TIER_THRESHOLD = 100
BUFFER_HOURS = 2


def _serialize_event(e):
    return {
        "id": e["id"],
        "watch_group_id": e["watch_group_id"],
        "event_kind": e["event_kind"],
        "street_closure_start": e["street_closure_start"],
        "street_closure_end": e["street_closure_end"],
        "event_status": e["event_status"],
        "estimated_attendance": e["estimated_attendance"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def _check_closure_conflict(watch_group_id, start_dt, end_dt, exclude_id=None):
    """Buffer-inclusive closure conflict check."""
    buf = timedelta(hours=BUFFER_HOURS)
    buf_start = start_dt - buf
    buf_end = end_dt + buf

    for ev in db.community_events.values():
        if ev["watch_group_id"] != watch_group_id:
            continue
        if ev["event_status"] != "APPROVED":
            continue
        if exclude_id and ev["id"] == exclude_id:
            continue
        ev_start = db.parse_iso(ev["street_closure_start"]) - buf
        ev_end = db.parse_iso(ev["street_closure_end"]) + buf
        # Buffered closed intervals must not touch (gap must be > 0)
        # Overlap or adjacency: buf_start <= ev_end and buf_end >= ev_start
        if buf_start <= ev_end and buf_end >= ev_start:
            raise errors.closure_conflict()


@bp.route("/watch/community-events", methods=["POST"])
def create_event():
    user_id, role = require_roles("ProgramCoordinator", "BlockCaptain")
    body = request.get_json(force=True, silent=True) or {}

    watch_group_id = body.get("watch_group_id")
    event_kind = body.get("event_kind")
    street_closure_start = body.get("street_closure_start")
    street_closure_end = body.get("street_closure_end")
    estimated_attendance = body.get("estimated_attendance", 0)

    # Field-level validation
    if not event_kind or event_kind not in VALID_KINDS:
        raise errors.invalid_request("Invalid event_kind")
    if not street_closure_start or not street_closure_end:
        raise errors.invalid_request("street_closure_start and street_closure_end are required")
    try:
        start_dt = db.parse_iso(street_closure_start)
        end_dt = db.parse_iso(street_closure_end)
    except Exception:
        raise errors.invalid_request("Invalid datetime format")
    if end_dt < start_dt:
        raise errors.invalid_request("street_closure_end must be >= street_closure_start")
    if not isinstance(estimated_attendance, int) or estimated_attendance < 0:
        raise errors.invalid_request("estimated_attendance must be a non-negative integer")

    # Existence
    g = db.watch_groups.get(watch_group_id) if watch_group_id else None
    if not g:
        raise errors.not_found("WatchGroup not found")

    # Posture gate
    if g["posture"] == "FROZEN":
        raise errors.posture_gated("Event proposal rejected while group is FROZEN")

    # Buffer-inclusive closure conflict check
    _check_closure_conflict(watch_group_id, start_dt, end_dt)

    record = {
        "watch_group_id": watch_group_id,
        "event_kind": event_kind,
        "street_closure_start": street_closure_start,
        "street_closure_end": street_closure_end,
        "event_status": "PROPOSED",
        "estimated_attendance": estimated_attendance,
    }
    svc.stamp_new(record)
    db.community_events[record["id"]] = record
    return success_object(_serialize_event(record), 201)


@bp.route("/watch/community-events", methods=["GET"])
def list_events():
    user_id, role = require_roles(*ALL_ROLES)

    items = list(db.community_events.values())

    wg = request.args.get("watch_group_id")
    if wg:
        items = [e for e in items if e["watch_group_id"] == wg]
    es = request.args.get("event_status")
    if es:
        items = [e for e in items if e["event_status"] == es]
    ek = request.args.get("event_kind")
    if ek:
        items = [e for e in items if e["event_kind"] == ek]

    items.sort(key=lambda e: e["created_at"])
    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list([_serialize_event(e) for e in items], limit, offset, total)


@bp.route("/watch/community-events/<id>", methods=["GET"])
def get_event(id):
    user_id, role = require_roles(*ALL_ROLES)
    e = db.community_events.get(id)
    if not e:
        raise errors.not_found("CommunityEvent not found")
    return success_object(_serialize_event(e))


@bp.route("/watch/community-events/<id>/approve", methods=["POST"])
def approve_event(id):
    user_id, role = require_roles("LiaisonOfficer")
    e = db.community_events.get(id)
    if not e:
        raise errors.not_found("CommunityEvent not found")

    if e["event_status"] != "PROPOSED":
        raise errors.invalid_state("Event is not PROPOSED")

    g = db.watch_groups.get(e["watch_group_id"])
    if not g:
        raise errors.not_found("WatchGroup not found")

    # Buffer-inclusive closure conflict (re-check at approval)
    start_dt = db.parse_iso(e["street_closure_start"])
    end_dt = db.parse_iso(e["street_closure_end"])
    _check_closure_conflict(e["watch_group_id"], start_dt, end_dt, exclude_id=e["id"])

    # Large-gathering data share gate (PRD §2.6: precedes the certification gate)
    if e["estimated_attendance"] >= PERMIT_TIER_THRESHOLD:
        if not svc.has_active_agreement(e["watch_group_id"]):
            raise errors.data_share_required("Large event requires an ACTIVE DataShareAgreement")

    # Certification gate
    if e["event_kind"] == "NATIONAL_NIGHT_OUT":
        if g["certification_status"] != "CERTIFIED":
            raise errors.certification_required("NATIONAL_NIGHT_OUT requires CERTIFIED")
    else:
        if g["certification_status"] not in ("PROVISIONAL", "CERTIFIED"):
            raise errors.certification_required("Event approval requires PROVISIONAL or CERTIFIED")

    e["event_status"] = "APPROVED"
    svc.touch(e)
    return success_object(_serialize_event(e))


@bp.route("/watch/community-events/<id>/complete", methods=["POST"])
def complete_event(id):
    user_id, role = require_roles("ProgramCoordinator")
    e = db.community_events.get(id)
    if not e:
        raise errors.not_found("CommunityEvent not found")

    if e["event_status"] != "APPROVED":
        raise errors.invalid_state("Event is not APPROVED")

    # Clock must be past street_closure_end
    end_dt = db.parse_iso(e["street_closure_end"])
    if db.get_clock() <= end_dt:
        raise errors.invalid_state("Event closure window has not fully passed")

    e["event_status"] = "COMPLETED"
    svc.touch(e)

    # Participation score recompute
    svc.recompute_posture(e["watch_group_id"])

    return success_object(_serialize_event(e))


@bp.route("/watch/community-events/<id>/cancel", methods=["POST"])
def cancel_event(id):
    user_id, role = require_roles("ProgramCoordinator", "LiaisonOfficer")
    e = db.community_events.get(id)
    if not e:
        raise errors.not_found("CommunityEvent not found")

    if e["event_status"] == "PROPOSED":
        # Coordinator cancels PROPOSED
        if role != "ProgramCoordinator":
            raise errors.unauthorized("Only a coordinator may cancel a PROPOSED event")
    elif e["event_status"] == "APPROVED":
        # Officer cancels APPROVED, only before closure start
        if role != "LiaisonOfficer":
            raise errors.unauthorized("Only an officer may cancel an APPROVED event")
        start_dt = db.parse_iso(e["street_closure_start"])
        if db.get_clock() >= start_dt:
            raise errors.invalid_state("Cannot cancel after street closure has started")
    else:
        raise errors.invalid_state("Event cannot be cancelled from its current state")

    e["event_status"] = "CANCELLED"
    svc.touch(e)
    return success_object(_serialize_event(e))
