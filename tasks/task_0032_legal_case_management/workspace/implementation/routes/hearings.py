"""Hearing endpoints (scheduling, reschedule, cancel, complete, prep tasks)."""

from datetime import timedelta

import clock
import db
import errors
import helpers
import response
import serializers
from flask import Blueprint, request
from middleware import auth_required
from services import calculations, posture


bp = Blueprint("hearings", __name__)


TRAVEL_BUFFER = timedelta(minutes=30)


def _ensure_not_archived(case):
    if case["status"] == "ARCHIVED":
        errors.raise_error(errors.ERR_CASE_ARCHIVED, "Case is archived.")


def _parse_window(body):
    """Validate and parse scheduled_start/scheduled_end. Returns tuple of dt."""
    if "scheduled_start" not in body or "scheduled_end" not in body:
        errors.raise_error(
            errors.ERR_VALIDATION_FAILED,
            "scheduled_start and scheduled_end are required.",
        )
    try:
        start = clock.parse_iso(body["scheduled_start"])
        end = clock.parse_iso(body["scheduled_end"])
    except (ValueError, TypeError):
        errors.raise_error(errors.ERR_VALIDATION_FAILED, "scheduled_start/end must be ISO 8601.")

    if end <= start:
        errors.raise_error(
            errors.ERR_HEARING_INVALID_INTERVAL,
            "scheduled_end must be > scheduled_start.",
        )
    if start <= clock.now():
        errors.raise_error(
            errors.ERR_HEARING_PAST_TIME,
            "scheduled_start must be in the future.",
        )
    return start, end


def _intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test (touching is allowed)."""
    return a_start < b_end and b_start < a_end


def _check_room_conflict(court_room, start, end, *, exclude_hearing_id=None):
    for h in db.hearings.values():
        if exclude_hearing_id is not None and h["id"] == exclude_hearing_id:
            continue
        if h["status"] != "SCHEDULED":
            continue
        if h["court_room"] != court_room:
            continue
        if _intervals_overlap(start, end, h["scheduled_start"], h["scheduled_end"]):
            errors.raise_error(
                errors.ERR_HEARING_ROOM_CONFLICT,
                f"Court room {court_room} already booked for an overlapping window.",
            )


def _check_lawyer_conflict(lead_lawyer_id, start, end, *, exclude_hearing_id=None):
    for h in db.hearings.values():
        if exclude_hearing_id is not None and h["id"] == exclude_hearing_id:
            continue
        if h["status"] != "SCHEDULED":
            continue
        if h["lead_lawyer_id"] != lead_lawyer_id:
            continue
        # Need 30-min travel buffer: next.start >= prev.end + 30min, OR
        # equivalently: prev.start >= next.end + 30min. Treat as overlap if
        # buffered intervals overlap.
        prev_buffered_end = h["scheduled_end"] + TRAVEL_BUFFER
        new_buffered_end = end + TRAVEL_BUFFER
        if _intervals_overlap(start, new_buffered_end, h["scheduled_start"], prev_buffered_end):
            errors.raise_error(
                errors.ERR_LAWYER_SCHEDULE_CONFLICT,
                "Lead lawyer schedule overlaps another SCHEDULED hearing within 30-min buffer.",
            )


@bp.route("/hearings", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer", "IntakeClerk")
def schedule_hearing():
    body = helpers.get_json_body()
    case_id = helpers.require_str(body, "case_id")
    court_room = helpers.require_str(body, "court_room", min_len=1)

    case = db.cases.get(case_id)
    if case is None:
        errors.raise_error(errors.ERR_REFERENCED_NOT_FOUND, f"Case {case_id} not found.")
    _ensure_not_archived(case)

    start, end = _parse_window(body)

    # Posture gate: FROZEN cases cannot create new hearings.
    if case["posture"] == "FROZEN":
        errors.raise_error(errors.ERR_CASE_POSTURE_FROZEN, "Case is FROZEN; cannot schedule hearings.")

    # Room conflict (priority 13).
    _check_room_conflict(court_room, start, end)
    # Lawyer schedule conflict (priority 14).
    _check_lawyer_conflict(case["lead_lawyer_id"], start, end)

    hid = db.new_id()
    common = helpers.common_create()
    hearing = {
        "id": hid,
        "case_id": case_id,
        "court_room": court_room,
        "scheduled_start": start,
        "scheduled_end": end,
        "lead_lawyer_id": case["lead_lawyer_id"],
        "status": "SCHEDULED",
        "prep_tasks_generated": True,
        "previous_hearing_id": None,
        **common,
    }
    db.hearings[hid] = hearing
    posture.recompute(case)
    return response.created(serializers.hearing_dict(hearing))


@bp.route("/hearings/<hid>/reschedule", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer")
def reschedule_hearing(hid):
    hearing = db.hearings.get(hid)
    if hearing is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Hearing {hid} not found.")
    case = db.cases.get(hearing["case_id"])
    if case is not None:
        _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(hearing, body.get("version"))

    if hearing["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only SCHEDULED hearings may be rescheduled.")
    if case is None or case["status"] not in {"ACTIVE", "ON_HOLD"}:
        errors.raise_error(errors.ERR_INVALID_STATE, "Case must be ACTIVE or ON_HOLD to reschedule.")

    court_room = helpers.require_str(body, "court_room", min_len=1)
    start, end = _parse_window(body)

    # Conflict checks against the new window, excluding the hearing being rescheduled.
    _check_room_conflict(court_room, start, end, exclude_hearing_id=hid)
    _check_lawyer_conflict(hearing["lead_lawyer_id"], start, end, exclude_hearing_id=hid)

    # Mark original as RESCHEDULED.
    hearing["status"] = "RESCHEDULED"
    helpers.bump(hearing)

    nid = db.new_id()
    common = helpers.common_create()
    new_h = {
        "id": nid,
        "case_id": hearing["case_id"],
        "court_room": court_room,
        "scheduled_start": start,
        "scheduled_end": end,
        "lead_lawyer_id": hearing["lead_lawyer_id"],
        "status": "SCHEDULED",
        "prep_tasks_generated": True,
        "previous_hearing_id": hid,
        **common,
    }
    db.hearings[nid] = new_h
    posture.recompute_by_id(hearing["case_id"])
    return response.created(serializers.hearing_dict(new_h))


@bp.route("/hearings/<hid>/cancel", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer")
def cancel_hearing(hid):
    hearing = db.hearings.get(hid)
    if hearing is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Hearing {hid} not found.")
    case = db.cases.get(hearing["case_id"])
    if case is not None:
        _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(hearing, body.get("version"))

    if hearing["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only SCHEDULED hearings may be cancelled.")

    hearing["status"] = "CANCELLED"
    helpers.bump(hearing)
    posture.recompute_by_id(hearing["case_id"])
    return response.ok(serializers.hearing_dict(hearing))


@bp.route("/hearings/<hid>/complete", methods=["POST"])
@auth_required("PartnerLawyer", "SeniorLawyer")
def complete_hearing(hid):
    hearing = db.hearings.get(hid)
    if hearing is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Hearing {hid} not found.")
    case = db.cases.get(hearing["case_id"])
    if case is not None:
        _ensure_not_archived(case)
    body = helpers.get_json_body()
    helpers.check_occ(hearing, body.get("version"))

    if hearing["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only SCHEDULED hearings may be completed.")
    if case is None or case["status"] not in {"ACTIVE", "AWAITING_SETTLEMENT"}:
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Case must be ACTIVE or AWAITING_SETTLEMENT.",
        )
    if clock.now() < hearing["scheduled_end"]:
        errors.raise_error(
            errors.ERR_INVALID_STATE,
            "Hearing cannot be completed before scheduled_end.",
        )

    hearing["status"] = "COMPLETED"
    helpers.bump(hearing)
    posture.recompute_by_id(hearing["case_id"])
    return response.ok(serializers.hearing_dict(hearing))


@bp.route("/hearings/<hid>/prep-tasks", methods=["GET"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer")
def get_prep_tasks(hid):
    hearing = db.hearings.get(hid)
    if hearing is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Hearing {hid} not found.")
    case = db.cases.get(hearing["case_id"])
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Parent case not found.")
    tasks = calculations.compute_prep_tasks(case)
    return response.ok({"hearing_id": hid, "case_id": case["id"], "prep_tasks": tasks})


@bp.route("/cases/<cid>/hearings", methods=["GET"])
@auth_required("PartnerLawyer", "SeniorLawyer", "JuniorLawyer", "IntakeClerk")
def list_case_hearings(cid):
    case = db.cases.get(cid)
    if case is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Case {cid} not found.")
    limit, offset = helpers.parse_pagination()
    items = [h for h in db.hearings.values() if h["case_id"] == cid]
    if request.args.get("status"):
        items = [h for h in items if h["status"] == request.args["status"]]
    items.sort(key=lambda h: h["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok(
        [serializers.hearing_dict(h) for h in page],
        limit=limit, offset=offset, total_count=total,
    )
