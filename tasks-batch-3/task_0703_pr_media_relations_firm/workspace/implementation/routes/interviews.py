"""Interview endpoints and lifecycle (PRD 3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from clock import clock
from common import (get_json_body, get_or_404, new_record, paginate, parse_dt,
                    parse_pagination, ref_or_404, require_datetime, touch)
from errors import err
from middleware import authorize
from response import success
from services.serialize import interview_out

bp = Blueprint("interviews", __name__)

INTERVIEW_STATUSES = {"REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED", "NO_SHOW"}
_NON_TERMINAL = ("REQUESTED", "CONFIRMED")


def _overlap(a_start, a_end, b_start, b_end):
    """True if half-open intervals [a_start, a_end) and [b_start, b_end) overlap."""
    return a_start < b_end and b_start < a_end


def _check_overlaps(spokesperson, journalist_id, starts_at, ends_at, exclude_id=None):
    """Enforce both non-overlap rules (PRD 3.6).

    Spokesperson rule (with prep buffer applied to both ends of the candidate)
    is checked first, then the journalist rule (raw half-open, no buffer).
    """
    buffer = timedelta(minutes=spokesperson["prep_buffer_minutes"])
    padded_start = starts_at - buffer
    padded_end = ends_at + buffer

    # Spokesperson double-booking (buffered).
    for itv in db.interviews.values():
        if exclude_id is not None and itv["id"] == exclude_id:
            continue
        if itv["spokesperson_id"] != spokesperson["id"]:
            continue
        if itv["status"] not in _NON_TERMINAL:
            continue
        o_start = parse_dt(itv["starts_at"])
        o_end = parse_dt(itv["ends_at"])
        if _overlap(padded_start, padded_end, o_start, o_end):
            raise err("ERR_SPOKESPERSON_DOUBLE_BOOKED",
                      "Interview overlaps another non-terminal interview for the spokesperson")

    # Journalist double-booking (no buffer, raw half-open).
    for itv in db.interviews.values():
        if exclude_id is not None and itv["id"] == exclude_id:
            continue
        if itv["journalist_id"] != journalist_id:
            continue
        if itv["status"] not in _NON_TERMINAL:
            continue
        o_start = parse_dt(itv["starts_at"])
        o_end = parse_dt(itv["ends_at"])
        if _overlap(starts_at, ends_at, o_start, o_end):
            raise err("ERR_JOURNALIST_DOUBLE_BOOKED",
                      "Interview overlaps another non-terminal interview for the journalist")


@bp.post("/agency/interviews")
@authorize(["SchedulingCoordinator"])
def create_interview():
    body = get_json_body()
    campaign_id = body.get("campaign_id")
    spokesperson_id = body.get("spokesperson_id")
    journalist_id = body.get("journalist_id")
    pitch_id = body.get("pitch_id")
    # Priority 4: FK existence (pitch_id nullable).
    ref_or_404(db.campaigns, campaign_id, "campaign_id")
    spokesperson = ref_or_404(db.spokespersons, spokesperson_id, "spokesperson_id")
    ref_or_404(db.journalists, journalist_id, "journalist_id")
    if pitch_id is not None:
        ref_or_404(db.pitches, pitch_id, "pitch_id")
    # Priority 5: well-formedness; ends_at must be strictly after starts_at.
    starts_at = require_datetime(body, "starts_at")
    ends_at = require_datetime(body, "ends_at")
    if ends_at <= starts_at:
        raise err("ERR_INVALID_REQUEST", "ends_at must be strictly after starts_at")

    # Priority 10: interval-overlap checks.
    _check_overlaps(spokesperson, journalist_id, starts_at, ends_at)

    rec = new_record({
        "campaign_id": campaign_id,
        "spokesperson_id": spokesperson_id,
        "journalist_id": journalist_id,
        "pitch_id": pitch_id,
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "status": "REQUESTED",
    })
    db.interviews[rec["id"]] = rec
    return success(interview_out(rec), status=201)


@bp.get("/agency/interviews/<interview_id>")
@authorize(["AccountManager", "SchedulingCoordinator", "MediaSpecialist", "PlatformAdmin"])
def get_interview(interview_id):
    rec = get_or_404(db.interviews, interview_id)
    return success(interview_out(rec))


@bp.get("/agency/interviews")
@authorize(["AccountManager", "SchedulingCoordinator", "MediaSpecialist", "PlatformAdmin"])
def list_interviews():
    limit, offset = parse_pagination()
    campaign_id = request.args.get("campaign_id")
    spokesperson_id = request.args.get("spokesperson_id")
    journalist_id = request.args.get("journalist_id")
    pitch_id = request.args.get("pitch_id")
    status = request.args.get("status")
    if status is not None and status not in INTERVIEW_STATUSES:
        raise err("ERR_INVALID_REQUEST", "status filter invalid")
    records = []
    for r in db.interviews.values():
        if campaign_id is not None and r["campaign_id"] != campaign_id:
            continue
        if spokesperson_id is not None and r["spokesperson_id"] != spokesperson_id:
            continue
        if journalist_id is not None and r["journalist_id"] != journalist_id:
            continue
        if pitch_id is not None and r.get("pitch_id") != pitch_id:
            continue
        if status is not None and r["status"] != status:
            continue
        records.append(r)
    page, meta = paginate(records, limit, offset)
    return success([interview_out(r) for r in page], pagination=meta)


@bp.post("/agency/interviews/<interview_id>/reschedule")
@authorize(["SchedulingCoordinator"])
def reschedule_interview(interview_id):
    rec = get_or_404(db.interviews, interview_id)
    body = get_json_body()
    starts_at = require_datetime(body, "starts_at")
    ends_at = require_datetime(body, "ends_at")
    if ends_at <= starts_at:
        raise err("ERR_INVALID_REQUEST", "ends_at must be strictly after starts_at")
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Interview is not REQUESTED")
    spokesperson = db.spokespersons[rec["spokesperson_id"]]
    _check_overlaps(spokesperson, rec["journalist_id"], starts_at, ends_at,
                    exclude_id=rec["id"])
    rec["starts_at"] = body["starts_at"]
    rec["ends_at"] = body["ends_at"]
    touch(rec)
    return success(interview_out(rec))


@bp.post("/agency/interviews/<interview_id>/confirm")
@authorize(["SchedulingCoordinator"])
def confirm_interview(interview_id):
    rec = get_or_404(db.interviews, interview_id)
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Interview is not REQUESTED")
    spokesperson = db.spokespersons[rec["spokesperson_id"]]
    if spokesperson["status"] != "ACTIVE":
        raise err("ERR_SPOKESPERSON_INACTIVE", "Spokesperson is not ACTIVE")
    if rec.get("pitch_id"):
        pitch = db.pitches[rec["pitch_id"]]
        if pitch["status"] != "ACCEPTED":
            raise err("ERR_PITCH_NOT_ACCEPTED", "Anchoring pitch is not ACCEPTED")
    rec["status"] = "CONFIRMED"
    touch(rec)
    return success(interview_out(rec))


@bp.post("/agency/interviews/<interview_id>/complete")
@authorize(["SchedulingCoordinator"])
def complete_interview(interview_id):
    rec = get_or_404(db.interviews, interview_id)
    if rec["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Interview is not CONFIRMED")
    if clock.now() < parse_dt(rec["ends_at"]):
        raise err("ERR_INTERVIEW_NOT_ENDED", "Interview has not ended yet")
    rec["status"] = "COMPLETED"
    touch(rec)
    return success(interview_out(rec))


@bp.post("/agency/interviews/<interview_id>/no-show")
@authorize(["SchedulingCoordinator"])
def no_show_interview(interview_id):
    rec = get_or_404(db.interviews, interview_id)
    if rec["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Interview is not CONFIRMED")
    if clock.now() < parse_dt(rec["starts_at"]):
        raise err("ERR_INTERVIEW_NOT_STARTED", "Interview has not started yet")
    rec["status"] = "NO_SHOW"
    touch(rec)
    return success(interview_out(rec))


@bp.post("/agency/interviews/<interview_id>/cancel")
@authorize(["SchedulingCoordinator"])
def cancel_interview(interview_id):
    rec = get_or_404(db.interviews, interview_id)
    if rec["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Interview cannot be cancelled from its current state")
    rec["status"] = "CANCELLED"
    touch(rec)
    return success(interview_out(rec))
