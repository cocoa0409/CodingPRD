"""AuditionSlot endpoints and lifecycle (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, lock
from errors import ApiError
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import (
    mint_common,
    touch,
    public,
    get_json_body,
    require_str,
    require_enum,
    lookup,
    paginate,
)
from services.calc import SLOT_BUFFER_MINUTES
from timeutil import require_dt, now_dt

bp = Blueprint("audition_slots", __name__)

ALL_ROLES = {"Agent", "CastingDirector", "Talent"}
SLOT_KINDS = {"AUDITION", "CALLBACK"}


@bp.route("/audition-slots", methods=["POST"])
def create_audition_slot():
    _, role = get_identity()
    require_role(role, {"CastingDirector"})
    body = get_json_body()
    submission_id = require_str(body, "submission_id")
    casting_director_id = require_str(body, "casting_director_id")
    slot_kind = require_enum(body, "slot_kind", SLOT_KINDS)
    require_str(body, "start_at")
    require_str(body, "end_at")
    start_at = require_dt(body["start_at"])
    end_at = require_dt(body["end_at"])
    with lock:
        # Existence (priority 3), declaration order.
        sub = lookup("Submission", submission_id)
        lookup("CastingDirector", casting_director_id)
        call = lookup("CastingCall", sub["casting_call_id"])

        # State of submission for the requested transition (priority 6).
        if slot_kind == "AUDITION":
            if sub["status"] != "SUBMITTED":
                raise ApiError("ERR_INVALID_STATE")
        else:  # CALLBACK
            if sub["status"] != "AUDITION_SCHEDULED":
                raise ApiError("ERR_INVALID_STATE")

        # Cross-entity gates (priority 7).
        if slot_kind == "AUDITION":
            if call["status"] != "OPEN":
                raise ApiError("ERR_CASTING_CALL_NOT_OPEN")
        else:  # CALLBACK
            has_completed_audition = any(
                s["submission_id"] == submission_id
                and s["slot_kind"] == "AUDITION"
                and s["status"] == "COMPLETED"
                for s in db.audition_slots.values()
            )
            if not has_completed_audition:
                raise ApiError("ERR_AUDITION_NOT_COMPLETED")

        # Buffered overlap on the director's calendar (priority 9).
        _check_slot_overlap(casting_director_id, start_at, end_at)

        # Date ordering (priority 11): end strictly after start.
        if end_at <= start_at:
            raise ApiError("ERR_INVALID_DATE_RANGE")

        record = mint_common({
            "submission_id": submission_id,
            "casting_director_id": casting_director_id,
            "slot_kind": slot_kind,
            "start_at": body["start_at"],
            "end_at": body["end_at"],
            "status": "SCHEDULED",
        })
        db.audition_slots[record["id"]] = record

        # Side effect: advance submission status.
        if slot_kind == "AUDITION":
            sub["status"] = "AUDITION_SCHEDULED"
        else:
            sub["status"] = "CALLBACK_SCHEDULED"
        touch(sub)
        return object_response(public(record), status=201)


def _check_slot_overlap(casting_director_id, start_at, end_at):
    """Reject overlap with another SCHEDULED slot on the same director, where
    overlap is a closed interval extended by SLOT_BUFFER_MINUTES of buffer."""
    buffer = timedelta(minutes=SLOT_BUFFER_MINUTES)
    for slot in db.audition_slots.values():
        if slot["casting_director_id"] != casting_director_id:
            continue
        if slot["status"] != "SCHEDULED":
            continue
        existing_start = require_dt(slot["start_at"])
        existing_end = require_dt(slot["end_at"])
        # Closed intervals overlap (with buffer) iff
        # new_start <= existing_end + buffer AND existing_start <= new_end + buffer.
        if start_at <= existing_end + buffer and existing_start <= end_at + buffer:
            raise ApiError("ERR_SLOT_OVERLAP")


@bp.route("/audition-slots", methods=["GET"])
def list_audition_slots():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        items = list(db.audition_slots.values())
        for field in ("submission_id", "casting_director_id", "status"):
            val = request.args.get(field)
            if val is not None:
                items = [s for s in items if s[field] == val]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/audition-slots/<slot_id>", methods=["GET"])
def get_audition_slot(slot_id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        record = lookup("AuditionSlot", slot_id)
        return object_response(public(record), status=200)


@bp.route("/audition-slots/<slot_id>/complete", methods=["POST"])
def complete_audition_slot(slot_id):
    _, role = get_identity()
    require_role(role, {"CastingDirector"})
    with lock:
        slot = lookup("AuditionSlot", slot_id)
        if slot["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE")
        if now_dt(db) < require_dt(slot["end_at"]):
            raise ApiError("ERR_SLOT_NOT_ENDED")
        slot["status"] = "COMPLETED"
        touch(slot)
        return object_response(public(slot), status=200)


@bp.route("/audition-slots/<slot_id>/release", methods=["POST"])
def release_audition_slot(slot_id):
    _, role = get_identity()
    require_role(role, {"CastingDirector"})
    with lock:
        slot = lookup("AuditionSlot", slot_id)
        if slot["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE")
        slot["status"] = "RELEASED"
        touch(slot)
        return object_response(public(slot), status=200)
