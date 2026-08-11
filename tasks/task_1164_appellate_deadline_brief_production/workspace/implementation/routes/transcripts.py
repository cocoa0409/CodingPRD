"""Transcript order endpoints (PRD §3.3)."""
from flask import Blueprint, request

from db import STORE, now_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import (
    get_body, req_str, req_int, req_iso, new_entity, paginate, touch,
    path_record, path_transcript, transcripts_for_record,
    recompute_record_completeness, add_calendar_days, court_for_case,
)
from services.workflows import maybe_complete_record

bp = Blueprint("transcripts", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")
TERMINAL_TRANSCRIPT = ("FILED", "CANCELLED")
DEFAULT_TRANSCRIPT_DELIVERY_DAYS = 30


def _court_for_record(rec):
    case = STORE.cases.get(rec["case_id"])
    return court_for_case(case) if case else None


@bp.post("/appellate/records/<rid>/transcript-orders")
def create_transcript(rid):
    auth = get_auth()
    require_roles(auth, ("Attorney", "ParalegalStaff"))
    rec = path_record(rid)
    if rec["status"] in ("FILED",):
        raise ApiError("ERR_ALREADY_TERMINAL", "Record is in a terminal state", 409)
    body = get_body()
    hearing = req_iso(body, "hearing_date")
    reporter = req_str(body, "court_reporter")
    est = req_int(body, "estimated_pages")
    court = _court_for_record(rec)
    delivery_days = (court or {}).get("transcript_delivery_days", DEFAULT_TRANSCRIPT_DELIVERY_DAYS)
    ordered_at = now_iso()
    t = new_entity({
        "record_id": rec["id"],
        "hearing_date": hearing,
        "court_reporter": reporter,
        "estimated_pages": est,
        "actual_pages": 0,
        "ordered_at": ordered_at,
        "due_at": add_calendar_days(ordered_at, delivery_days),
        "delivered_at": None,
        "status": "ORDERED",
    })
    STORE.transcript_orders[t["id"]] = t
    recompute_record_completeness(rec)
    touch(rec)
    out = dict(t)
    out.pop("_seq", None)
    return success_object(out, 201)


@bp.get("/appellate/records/<rid>/transcript-orders")
def list_transcripts(rid):
    auth = get_auth()
    require_roles(auth, ALL)
    rec = path_record(rid)
    items = transcripts_for_record(rec["id"])
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/transcript-orders/<tid>")
def get_transcript(tid):
    auth = get_auth()
    require_roles(auth, ALL)
    t = path_transcript(tid)
    out = dict(t)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/transcript-orders/<tid>/begin-preparation")
def begin_preparation(tid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk",))
    t = path_transcript(tid)
    if t["status"] in TERMINAL_TRANSCRIPT:
        raise ApiError("ERR_ALREADY_TERMINAL", "Transcript order is terminal", 409)
    if t["status"] != "ORDERED":
        raise ApiError("ERR_INVALID_STATE",
                       "Transcript must be ORDERED to begin preparation", 409)
    rec = STORE.records.get(t["record_id"])
    if not rec or rec["status"] not in ("DESIGNATED", "ASSEMBLING"):
        raise ApiError("ERR_INVALID_STATE",
                       "Record must be DESIGNATED or ASSEMBLING", 409)
    t["status"] = "IN_PREPARATION"
    touch(t)
    if rec["status"] == "DESIGNATED":
        rec["status"] = "ASSEMBLING"
        touch(rec)
    recompute_record_completeness(rec)
    out = dict(t)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/transcript-orders/<tid>/deliver")
def deliver_transcript(tid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk",))
    t = path_transcript(tid)
    if t["status"] in TERMINAL_TRANSCRIPT:
        raise ApiError("ERR_ALREADY_TERMINAL", "Transcript order is terminal", 409)
    if t["status"] != "IN_PREPARATION":
        raise ApiError("ERR_INVALID_STATE",
                       "Transcript must be IN_PREPARATION to deliver", 409)
    body = get_body()
    actual = req_int(body, "actual_pages")
    if actual <= 0:
        raise ApiError("ERR_INVALID_REQUEST",
                       "actual_pages must be greater than zero", 400)
    t["status"] = "DELIVERED"
    t["actual_pages"] = actual
    t["delivered_at"] = now_iso()
    touch(t)
    rec = STORE.records.get(t["record_id"])
    if rec:
        recompute_record_completeness(rec)
        maybe_complete_record(rec)
    out = dict(t)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/transcript-orders/<tid>/file")
def file_transcript(tid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    t = path_transcript(tid)
    if t["status"] in TERMINAL_TRANSCRIPT:
        raise ApiError("ERR_ALREADY_TERMINAL", "Transcript order is terminal", 409)
    if t["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE",
                       "Transcript must be DELIVERED to file", 409)
    rec = STORE.records.get(t["record_id"])
    if not rec or rec["status"] not in ("ASSEMBLING", "COMPLETE"):
        raise ApiError("ERR_INVALID_STATE",
                       "Record must be ASSEMBLING or COMPLETE", 409)
    t["status"] = "FILED"
    touch(t)
    if rec:
        recompute_record_completeness(rec)
        maybe_complete_record(rec)
    out = dict(t)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/transcript-orders/<tid>/cancel")
def cancel_transcript(tid):
    auth = get_auth()
    require_roles(auth, ("Attorney", "ParalegalStaff"))
    t = path_transcript(tid)
    if t["status"] in TERMINAL_TRANSCRIPT:
        raise ApiError("ERR_ALREADY_TERMINAL", "Transcript order is terminal", 409)
    if t["status"] not in ("ORDERED", "IN_PREPARATION"):
        raise ApiError("ERR_INVALID_STATE",
                       "Transcript must be ORDERED or IN_PREPARATION to cancel", 409)
    t["status"] = "CANCELLED"
    touch(t)
    rec = STORE.records.get(t["record_id"])
    if rec:
        recompute_record_completeness(rec)
        touch(rec)
    out = dict(t)
    out.pop("_seq", None)
    return success_object(out)
