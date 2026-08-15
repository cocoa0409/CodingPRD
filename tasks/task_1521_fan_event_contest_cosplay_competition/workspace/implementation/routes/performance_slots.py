"""PerformanceSlot routes: stage queueing, tech-cue edits, stage walk."""

from flask import Blueprint, request

from db import DB, new_id, now_ts
from errors import (
    err_not_found, err_invalid_state, err_safety_not_approved,
    err_consent_required, err_sequence_conflict, err_validation,
)
from middleware import require_roles
from response import success
from services.calculations import compact_stage_sequence
from services.helpers import body_json, req_str, req_int, opt_str, req_enum
from services.serializers import performance_slot_view, paginate

bp = Blueprint("performance_slots", __name__)

READ_ROLES = ("ContestLead", "StageManager", "Judge", "Contestant")


def _has_livestream_consent(contestant):
    if contestant is None:
        return False
    for item in contestant["consents"]:
        if item["scope"] == "LIVESTREAM":
            return item["status"] == "GRANTED"
    return False


def _sequence_conflict(contest_id, sequence_number, entry_id, exclude_slot_id=None):
    for s in DB.performance_slots.values():
        if s["contest_id"] != contest_id or s["status"] not in ("QUEUED", "ON_STAGE"):
            continue
        if exclude_slot_id and s["id"] == exclude_slot_id:
            continue
        if s["sequence_number"] == sequence_number:
            return True
    # Entry must not already occupy another QUEUED/ON_STAGE slot.
    for s in DB.performance_slots.values():
        if s["entry_id"] == entry_id and s["status"] in ("QUEUED", "ON_STAGE"):
            if exclude_slot_id and s["id"] == exclude_slot_id:
                continue
            return True
    return False


@bp.route("/performance-slots", methods=["POST"])
def create_slot():
    require_roles("StageManager")
    body = body_json()
    entry_id = req_str(body, "entry_id")
    sequence_number = req_int(body, "sequence_number", minimum=1)
    duration_seconds = req_int(body, "duration_seconds", minimum=1)
    tech_cues = opt_str(body, "tech_cues", default="")

    entry = DB.entries.get(entry_id)
    if entry is None:
        raise err_not_found("Entry not found")

    # State gate (pri 6): entry in {SUBMITTED, SAFETY_REJECTED, SAFETY_APPROVED,
    # PREJUDGED} AND (requires_prejudging == false OR status == PREJUDGED).
    allowed_states = ("SUBMITTED", "SAFETY_REJECTED", "SAFETY_APPROVED", "PREJUDGED")
    if entry["status"] not in allowed_states:
        raise err_invalid_state("Entry not in a stage-queueable state")
    if entry["requires_prejudging"] and entry["status"] != "PREJUDGED":
        raise err_invalid_state("Entry requires pre-judging before stage queueing")

    # Safety gate (pri 7).
    if entry["safety_status"] != "APPROVED":
        raise err_safety_not_approved()

    # Consent gate (pri 7).
    contestant = DB.contestants.get(entry["contestant_id"])
    if not _has_livestream_consent(contestant):
        raise err_consent_required()

    # Constraint (pri 9).
    if _sequence_conflict(entry["contest_id"], sequence_number, entry_id):
        raise err_sequence_conflict()

    ts = now_ts()
    slot = {
        "id": new_id(),
        "entry_id": entry_id,
        "contest_id": entry["contest_id"],
        "sequence_number": sequence_number,
        "duration_seconds": duration_seconds,
        "tech_cues": tech_cues,
        "status": "QUEUED",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB.performance_slots[slot["id"]] = slot

    # Entry SAFETY_APPROVED|PREJUDGED -> STAGE_QUEUED.
    if entry["status"] in ("SAFETY_APPROVED", "PREJUDGED"):
        entry["status"] = "STAGE_QUEUED"
        entry["updated_at"] = ts
        entry["version"] += 1

    return success(performance_slot_view(slot), status=201)


@bp.route("/performance-slots", methods=["GET"])
def list_slots():
    require_roles(*READ_ROLES)
    items = list(DB.performance_slots.values())
    contest_id = request.args.get("contest_id")
    entry_id = request.args.get("entry_id")
    status = request.args.get("status")
    if contest_id is not None:
        items = [s for s in items if s["contest_id"] == contest_id]
    if entry_id is not None:
        items = [s for s in items if s["entry_id"] == entry_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: s["created_at"])
    page, pag = paginate([performance_slot_view(s) for s in items], request.args)
    return success(page, response_type="array", pagination=pag)


@bp.route("/performance-slots/<sid>", methods=["GET"])
def get_slot(sid):
    require_roles(*READ_ROLES)
    slot = DB.performance_slots.get(sid)
    if slot is None:
        raise err_not_found("PerformanceSlot not found")
    return success(performance_slot_view(slot))


@bp.route("/performance-slots/<sid>", methods=["PATCH"])
def patch_slot(sid):
    require_roles("StageManager")
    body = body_json()

    if "sequence_number" in body:
        v = body["sequence_number"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise err_validation("sequence_number must be an integer >= 1")
    if "duration_seconds" in body:
        v = body["duration_seconds"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise err_validation("duration_seconds must be an integer >= 1")
    if "tech_cues" in body and not isinstance(body["tech_cues"], str):
        raise err_validation("tech_cues must be a string")

    slot = DB.performance_slots.get(sid)
    if slot is None:
        raise err_not_found("PerformanceSlot not found")

    if slot["status"] != "QUEUED":
        raise err_invalid_state("PerformanceSlot editable only while QUEUED")

    if "sequence_number" in body:
        new_seq = body["sequence_number"]
        for s in DB.performance_slots.values():
            if (
                s["contest_id"] == slot["contest_id"]
                and s["status"] in ("QUEUED", "ON_STAGE")
                and s["id"] != sid
                and s["sequence_number"] == new_seq
            ):
                raise err_sequence_conflict()
        slot["sequence_number"] = new_seq
    if "duration_seconds" in body:
        slot["duration_seconds"] = body["duration_seconds"]
    if "tech_cues" in body:
        slot["tech_cues"] = body["tech_cues"]

    slot["updated_at"] = now_ts()
    slot["version"] += 1
    return success(performance_slot_view(slot))


@bp.route("/performance-slots/<sid>/advance", methods=["POST"])
def advance_slot(sid):
    require_roles("StageManager")
    body = body_json()
    to = req_enum(body, "to", {"ON_STAGE", "COMPLETED", "SKIPPED"})

    slot = DB.performance_slots.get(sid)
    if slot is None:
        raise err_not_found("PerformanceSlot not found")

    entry = DB.entries.get(slot["entry_id"])

    if to == "ON_STAGE":
        if slot["status"] != "QUEUED":
            raise err_invalid_state("Only QUEUED slots can go ON_STAGE")
        # No other slot of the contest currently ON_STAGE.
        for s in DB.performance_slots.values():
            if (
                s["contest_id"] == slot["contest_id"]
                and s["status"] == "ON_STAGE"
                and s["id"] != sid
            ):
                raise err_invalid_state("Another slot is currently ON_STAGE")
        if entry is None or entry["status"] != "STAGE_QUEUED":
            raise err_invalid_state("Entry must be STAGE_QUEUED to go on stage")
        if entry["safety_status"] != "APPROVED":
            raise err_safety_not_approved()
        contestant = DB.contestants.get(entry["contestant_id"])
        if not _has_livestream_consent(contestant):
            raise err_consent_required()
        slot["status"] = "ON_STAGE"
        slot["updated_at"] = now_ts()
        slot["version"] += 1
        return success(performance_slot_view(slot))

    if to == "COMPLETED":
        if slot["status"] != "ON_STAGE":
            raise err_invalid_state("Only ON_STAGE slots can complete")
        ts = now_ts()
        slot["status"] = "COMPLETED"
        slot["updated_at"] = ts
        slot["version"] += 1
        if entry is not None and entry["status"] == "STAGE_QUEUED":
            entry["status"] = "PERFORMED"
            entry["updated_at"] = ts
            entry["version"] += 1
        return success(performance_slot_view(slot))

    # to == "SKIPPED"
    if slot["status"] not in ("QUEUED", "ON_STAGE"):
        raise err_invalid_state("Only QUEUED or ON_STAGE slots can be skipped")
    ts = now_ts()
    slot["status"] = "SKIPPED"
    slot["updated_at"] = ts
    slot["version"] += 1
    # Entry regresses out of STAGE_QUEUED.
    if entry is not None and entry["status"] == "STAGE_QUEUED":
        entry["status"] = "PREJUDGED" if entry["requires_prejudging"] else "SAFETY_APPROVED"
        entry["updated_at"] = ts
        entry["version"] += 1
    compact_stage_sequence(slot["contest_id"])
    return success(performance_slot_view(slot))
