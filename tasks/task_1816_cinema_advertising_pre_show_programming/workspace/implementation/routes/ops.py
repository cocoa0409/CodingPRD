"""Playback verification and attendance reporting (PRD 3.4, 3.5)."""
import db
import calc
from auth import require, check_theater_scope, ALL_ROLES
from envelope import success_object, success_list
from errors import (ApiError, not_found, conflict, unprocessable,
                    ERR_INVALID_STATE_TRANSITION,
                    ERR_PLAYLOG_ALREADY_RECORDED,
                    ERR_PLAYLOG_SLOT_NOT_CONFIRMED,
                    ERR_PLAYLOG_BEFORE_SHOWTIME,
                    ERR_DUPLICATE_OPEN_ATTENDANCE_REPORT,
                    ERR_ATTENDANCE_NOT_AUDITABLE,
                    ERR_SOD_AUDITOR_IS_REPORTER)
from serializers import ser_playlog, ser_attendance_report
from validate import get_body, req_int, req_enum, pagination

from . import bp

THEATER = {"TheaterOps"}
OPS = {"NetworkOps"}


def _showtime_of_slot(slot):
    reel = db.reels[slot["reel_id"]]
    return db.showtimes[reel["showtime_id"]]


def _theater_id_of_showtime(showtime):
    return db.screens[showtime["screen_id"]]["theater_id"]


# ------------------------------- PlayLogs -----------------------------------

@bp.post("/network/slots/<slot_id>/playlogs")
def create_playlog(slot_id):
    user_id = require(THEATER)
    slot = db.slots.get(slot_id)
    if slot is None:
        raise not_found("slot not found")
    showtime = _showtime_of_slot(slot)
    theater_id = _theater_id_of_showtime(showtime)
    # Priority 3: theater scope.
    check_theater_scope(user_id, theater_id)
    # Priority 4: shape.
    body = get_body()
    outcome = req_enum(body, "outcome", {"VERIFIED", "PARTIAL", "FAILED"})
    # Priority 7: duplicate record speaks first, then slot state.
    for p in db.playlogs.values():
        if p["slot_id"] == slot_id:
            raise conflict(ERR_PLAYLOG_ALREADY_RECORDED,
                           "a playback record already exists for this slot")
    if slot["slot_status"] != "CONFIRMED":
        raise conflict(ERR_PLAYLOG_SLOT_NOT_CONFIRMED,
                       "slot is not in CONFIRMED")
    # Priority 10: no playback records before the showtime starts.
    clock_dt, clock_str = db.get_clock()
    if clock_dt < showtime["_starts_dt"]:
        raise unprocessable(ERR_PLAYLOG_BEFORE_SHOWTIME,
                            "playback record filed before the showtime start")

    campaign = db.campaigns[slot["campaign_id"]]
    factor = calc.play_factor_for(outcome, campaign["partial_credit_mode"])
    if outcome == "FAILED":
        slot["slot_status"] = "MISSED"
        slot["play_factor"] = 0.0
        slot["attributed_impressions"] = 0
    else:
        slot["slot_status"] = "PLAYED"
        slot["play_factor"] = factor
        slot["attributed_impressions"] = calc.attribute(
            showtime["actual_attendance"], factor)
    db.touch(slot)

    rec = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
        "slot_id": slot_id,
        "outcome": outcome,
        "played_at": clock_str,
        "reported_by_user_id": user_id,
        "reported_by_theater_id": theater_id,
    }
    db.playlogs[rec["id"]] = rec

    # Cascades: slot left RESERVED/CONFIRMED, so reserved spend releases;
    # delivered impressions recompute with the new/dropped contribution.
    calc.recompute_campaign_reserved(campaign)
    calc.recompute_campaign_delivered(campaign)
    return success_object(ser_playlog(rec), 201)


@bp.get("/network/slots/<slot_id>/playlogs")
def list_slot_playlogs(slot_id):
    require(ALL_ROLES)
    slot = db.slots.get(slot_id)
    if slot is None:
        raise not_found("slot not found")
    limit, offset = pagination()
    items = sorted((p for p in db.playlogs.values()
                    if p["slot_id"] == slot_id), key=lambda r: r["_seq"])
    total = len(items)
    page = [ser_playlog(p) for p in items[offset:offset + limit]]
    return success_list(page, limit, offset, total)


# --------------------------- Attendance reports -----------------------------

@bp.post("/network/showtimes/<showtime_id>/attendance-reports")
def create_attendance_report(showtime_id):
    user_id = require(THEATER)
    showtime = db.showtimes.get(showtime_id)
    if showtime is None:
        raise not_found("showtime not found")
    # Priority 3: theater scope.
    check_theater_scope(user_id, _theater_id_of_showtime(showtime))
    # Priority 4: shape.
    body = get_body()
    reported = req_int(body, "reported_attendance", minimum=0)
    # Priority 9: duplicate open report.
    for r in db.attendance_reports.values():
        if (r["showtime_id"] == showtime_id
                and r["report_status"] in ("SUBMITTED", "ACCEPTED")):
            raise conflict(ERR_DUPLICATE_OPEN_ATTENDANCE_REPORT,
                           "an attendance report in SUBMITTED or ACCEPTED "
                           "already exists for this showtime")
    rec = db.new_record()
    rec.update({"showtime_id": showtime_id, "reported_attendance": reported,
                "audited_attendance": None, "report_status": "SUBMITTED",
                "reported_by_user_id": user_id, "reviewed_by_user_id": None,
                "audited_by_user_id": None})
    db.attendance_reports[rec["id"]] = rec
    return success_object(ser_attendance_report(rec), 201)


@bp.get("/network/showtimes/<showtime_id>/attendance-reports")
def list_attendance_reports(showtime_id):
    require(ALL_ROLES)
    showtime = db.showtimes.get(showtime_id)
    if showtime is None:
        raise not_found("showtime not found")
    limit, offset = pagination()
    items = sorted((r for r in db.attendance_reports.values()
                    if r["showtime_id"] == showtime_id),
                   key=lambda r: r["_seq"])
    total = len(items)
    page = [ser_attendance_report(r) for r in items[offset:offset + limit]]
    return success_list(page, limit, offset, total)


def _get_report_or_404(report_id):
    r = db.attendance_reports.get(report_id)
    if r is None:
        raise not_found("attendance report not found")
    return r


@bp.post("/network/attendance-reports/<report_id>/review")
def review_attendance_report(report_id):
    user_id = require(OPS)
    body = get_body()
    decision = req_enum(body, "decision", {"ACCEPT", "DISPUTE"})
    report = _get_report_or_404(report_id)
    if report["report_status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only a SUBMITTED report can be reviewed")
    report["reviewed_by_user_id"] = user_id
    if decision == "ACCEPT":
        report["report_status"] = "ACCEPTED"
        showtime = db.showtimes[report["showtime_id"]]
        showtime["actual_attendance"] = report["reported_attendance"]
        db.touch(showtime)
        calc.cascade_showtime_attendance(showtime)
    else:
        report["report_status"] = "DISPUTED"
    db.touch(report)
    return success_object(ser_attendance_report(report))


@bp.post("/network/attendance-reports/<report_id>/resubmit")
def resubmit_attendance_report(report_id):
    user_id = require(THEATER)
    report = _get_report_or_404(report_id)
    showtime = db.showtimes[report["showtime_id"]]
    # Priority 3: theater scope.
    check_theater_scope(user_id, _theater_id_of_showtime(showtime))
    # Priority 4: shape.
    body = get_body()
    reported = req_int(body, "reported_attendance", minimum=0)
    # Priority 7: state.
    if report["report_status"] != "DISPUTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       "only a DISPUTED report can be resubmitted")
    report["reported_attendance"] = reported
    report["report_status"] = "SUBMITTED"
    report["reviewed_by_user_id"] = None
    db.touch(report)
    return success_object(ser_attendance_report(report))


@bp.post("/network/attendance-reports/<report_id>/audit")
def audit_attendance_report(report_id):
    user_id = require({"Auditor"})
    body = get_body()
    audited = req_int(body, "audited_attendance", minimum=0)
    report = _get_report_or_404(report_id)
    # Priority 6: SoD before state.
    if user_id == report["reported_by_user_id"]:
        raise ApiError(ERR_SOD_AUDITOR_IS_REPORTER, 403,
                       "auditor must differ from the reporter")
    if report["report_status"] != "ACCEPTED":
        raise conflict(ERR_ATTENDANCE_NOT_AUDITABLE,
                       "only an ACCEPTED report can be audited")
    report["audited_attendance"] = audited
    report["audited_by_user_id"] = user_id
    report["report_status"] = "AUDITED"
    showtime = db.showtimes[report["showtime_id"]]
    showtime["actual_attendance"] = audited
    db.touch(showtime)
    calc.cascade_showtime_attendance(showtime)
    db.touch(report)
    return success_object(ser_attendance_report(report))
