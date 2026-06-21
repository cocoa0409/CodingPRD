"""Check-in endpoints (PRD §3.4)."""
from flask import Blueprint, g, request

import clock
import db
from calculations import punctuality as calc_punctuality
from errors import (
    ApiError,
    ERR_CHECKIN_WINDOW_OVERLAP,
    ERR_INVALID_STATE,
    ERR_SUPERVISEE_CLOSED,
    ERR_WINDOW_NOT_CLOSED,
)
from middleware import require_roles
from response import object_response, array_response
from serialize import public, public_list
from services.supervisee import auto_file_violation
from services.common import (
    TERMINAL_SUPERVISEE_STATES,
    apply_page,
    get_body,
    get_child_or_404,
    get_supervisee_or_404,
    paginate,
    require_datetime,
    require_fields,
    require_int_min,
    sorted_by_created,
)
from timeutil import parse_iso

bp = Blueprint("check_ins", __name__)


def _window(check_in):
    start = parse_iso(check_in["scheduled_for"]).timestamp()
    close = start + check_in["window_minutes"] * 60
    return start, close


@bp.post("/supervisees/<sid>/check-ins")
@require_roles("Officer")
def create(sid):
    s = get_supervisee_or_404(sid)
    if s["status"] in TERMINAL_SUPERVISEE_STATES:
        raise ApiError(*ERR_SUPERVISEE_CLOSED, "Supervisee case is closed.")
    body = get_body()
    require_fields(body, ["scheduled_for"])
    require_datetime(body["scheduled_for"], "scheduled_for")

    window_minutes = body.get("window_minutes", 60)
    if window_minutes is None:
        window_minutes = 60
    require_int_min(window_minutes, 1, "window_minutes")

    requires_drug_test = body.get("requires_drug_test", False)
    if requires_drug_test is None:
        requires_drug_test = False
    if not isinstance(requires_drug_test, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "requires_drug_test must be a boolean.")

    new_start = parse_iso(body["scheduled_for"]).timestamp()
    new_close = new_start + window_minutes * 60
    # Overlap check (half-open intervals; adjacency allowed) — ERR_CHECKIN_WINDOW_OVERLAP.
    for c in db.check_ins.values():
        if c.get("supervisee_id") != sid:
            continue
        ex_start, ex_close = _window(c)
        if new_start < ex_close and new_close > ex_start:
            raise ApiError(*ERR_CHECKIN_WINDOW_OVERLAP, "Check-in window overlaps an existing one.")

    rec = db.common_create_fields(versioned=True)
    rec.update(
        {
            "supervisee_id": s["id"],
            "scheduled_for": body["scheduled_for"],
            "window_minutes": window_minutes,
            "requires_drug_test": requires_drug_test,
            "status": "SCHEDULED",
            "attended_at": None,
            "punctuality": None,
        }
    )
    db.check_ins[rec["id"]] = rec
    return object_response(public(rec), 201)


@bp.get("/supervisees/<sid>/check-ins")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def list_check_ins(sid):
    get_supervisee_or_404(sid)
    limit, offset = paginate(request.args)
    records = [c for c in db.check_ins.values() if c.get("supervisee_id") == sid]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    records = sorted_by_created(records)
    page, total = apply_page(records, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.get("/supervisees/<sid>/check-ins/<cid>")
@require_roles("Officer", "SupervisingJudge", "CompactAdministrator")
def get_check_in(sid, cid):
    get_supervisee_or_404(sid)
    rec = get_child_or_404(db.check_ins, cid, sid, label="Check-in")
    return object_response(public(rec), 200)


@bp.post("/supervisees/<sid>/check-ins/<cid>/attend")
@require_roles("Officer")
def attend(sid, cid):
    get_supervisee_or_404(sid)
    c = get_child_or_404(db.check_ins, cid, sid, label="Check-in")
    body = get_body()
    require_fields(body, ["attended_at"])
    require_datetime(body["attended_at"], "attended_at")
    if c["status"] != "SCHEDULED":
        raise ApiError(*ERR_INVALID_STATE, "Check-in is not SCHEDULED.")
    # If a drug test is required, one bearing a result must already exist.
    if c["requires_drug_test"]:
        has_test = any(
            dt.get("check_in_id") == cid and dt.get("result") is not None
            for dt in db.drug_tests.values()
        )
        if not has_test:
            raise ApiError(*ERR_INVALID_STATE, "Required drug test result is missing.")
    c["attended_at"] = body["attended_at"]
    c["punctuality"] = calc_punctuality(c["scheduled_for"], c["window_minutes"], body["attended_at"])
    c["status"] = "ATTENDED"
    db.touch(c)
    return object_response(public(c), 200)


@bp.post("/supervisees/<sid>/check-ins/<cid>/mark-missed")
@require_roles("Officer")
def mark_missed(sid, cid):
    get_supervisee_or_404(sid)
    s = db.supervisees[sid]
    c = get_child_or_404(db.check_ins, cid, sid, label="Check-in")
    if c["status"] != "SCHEDULED":
        raise ApiError(*ERR_INVALID_STATE, "Check-in is not SCHEDULED.")
    _, close = _window(c)
    # Window must be fully closed: current clock strictly greater than close.
    if clock.now().timestamp() <= close:
        raise ApiError(*ERR_WINDOW_NOT_CLOSED, "The on-time window has not closed.")
    c["status"] = "MISSED"
    auto_file_violation(s, "TECHNICAL", g.user_id)
    db.touch(c)
    return object_response(public(c), 200)


@bp.post("/supervisees/<sid>/check-ins/<cid>/excuse")
@require_roles("Officer")
def excuse(sid, cid):
    get_supervisee_or_404(sid)
    c = get_child_or_404(db.check_ins, cid, sid, label="Check-in")
    if c["status"] != "SCHEDULED":
        raise ApiError(*ERR_INVALID_STATE, "Check-in is not SCHEDULED.")
    c["status"] = "EXCUSED"
    db.touch(c)
    return object_response(public(c), 200)
