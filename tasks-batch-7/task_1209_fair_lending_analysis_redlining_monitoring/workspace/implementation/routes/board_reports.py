"""Board reports."""
from datetime import date

from flask import Blueprint, g, request

import db
from errors import already_terminal, err, invalid_request, invalid_state
from middleware import body, get_or_404, list_page, require_field, require_roles
from response import success_list, success_obj
from services.cap import board_refresh_counts, periods_overlap

bp = Blueprint("board_reports", __name__)

ROLES = ("FairLendingAnalyst", "FairLendingOfficer", "ComplianceDirector")


def _is_calendar_quarter(start_s, end_s):
    try:
        ds = date.fromisoformat(start_s)
        de = date.fromisoformat(end_s)
    except (TypeError, ValueError):
        raise invalid_request("period_start and period_end must be ISO dates")
    if ds.day != 1 or ds.month not in (1, 4, 7, 10):
        return False
    year, month = ds.year, ds.month + 3
    if month > 12:
        month -= 12
        year += 1
    return de == date(year, month, 1)


@bp.post("/fair-lending/board-reports")
@require_roles("FairLendingAnalyst")
def create_report():
    data = body()
    period_start = require_field(data, "period_start")
    period_end = require_field(data, "period_end")
    # Interval conflicts (priority 7) before quarter alignment (priority 8).
    for r in db.STORES["reports"].values():
        if periods_overlap(
            period_start, period_end, r["period_start"], r["period_end"]
        ):
            raise err(
                "ERR_PERIOD_OVERLAP",
                "Board report period overlaps an existing report",
            )
    if db.STORES["reports"]:
        latest_end = max(r["period_end"] for r in db.STORES["reports"].values())
        if period_start != latest_end:
            raise err(
                "ERR_PERIOD_GAP",
                "Board report period is not contiguous with the latest report",
            )
    if not _is_calendar_quarter(period_start, period_end):
        raise err(
            "ERR_PERIOD_NOT_QUARTER",
            "Board report period must span exactly one calendar quarter",
        )
    rec = db.new_record(
        {
            "period_start": period_start,
            "period_end": period_end,
            "status": "DRAFT",
            "substantiated_finding_count": 0,
            "caps_executing_count": 0,
            "red_officer_count": 0,
            "privileged_exclusion_count": 0,
            "submitted_by_user_id": None,
            "approved_by_user_id": None,
            "published_at": None,
        }
    )
    db.STORES["reports"][rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/board-reports")
@require_roles(*ROLES)
def list_reports():
    page, total, limit, offset = list_page(
        "reports", {"status": request.args.get("status")}
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/board-reports/<reportId>")
@require_roles(*ROLES)
def get_report(reportId):
    rec = get_or_404("reports", reportId, "BoardReport")
    return success_obj(db.public(rec))


def _load(reportId):
    rec = get_or_404("reports", reportId, "BoardReport")
    if rec["status"] == "PUBLISHED":
        raise already_terminal("BoardReport is PUBLISHED")
    return rec


@bp.post("/fair-lending/board-reports/<reportId>/refresh")
@require_roles("FairLendingAnalyst")
def refresh(reportId):
    rec = _load(reportId)
    if rec["status"] not in ("DRAFT", "RETURNED"):
        raise invalid_state("Only DRAFT or RETURNED reports can be refreshed")
    board_refresh_counts(rec)
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/board-reports/<reportId>/submit")
@require_roles("FairLendingOfficer")
def submit(reportId):
    rec = _load(reportId)
    if rec["status"] != "DRAFT":
        raise invalid_state("BoardReport is not in DRAFT status")
    rec["status"] = "SUBMITTED"
    rec["submitted_by_user_id"] = g.user_id
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/board-reports/<reportId>/return")
@require_roles("ComplianceDirector")
def return_(reportId):
    rec = _load(reportId)
    if rec["status"] != "SUBMITTED":
        raise invalid_state("BoardReport is not in SUBMITTED status")
    rec["status"] = "RETURNED"
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/board-reports/<reportId>/revise")
@require_roles("FairLendingAnalyst")
def revise(reportId):
    rec = _load(reportId)
    if rec["status"] != "RETURNED":
        raise invalid_state("BoardReport is not in RETURNED status")
    rec["status"] = "DRAFT"
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/board-reports/<reportId>/approve")
@require_roles("ComplianceDirector")
def approve(reportId):
    rec = _load(reportId)
    # SoD (identity-level, priority 3): approver must differ from submitter.
    if (
        rec.get("submitted_by_user_id") is not None
        and rec["submitted_by_user_id"] == g.user_id
    ):
        raise err(
            "ERR_SOD_VIOLATION",
            "Board report approver must differ from the submitter",
        )
    if rec["status"] != "SUBMITTED":
        raise invalid_state("BoardReport is not in SUBMITTED status")
    rec["status"] = "APPROVED"
    rec["approved_by_user_id"] = g.user_id
    db.touch(rec)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/board-reports/<reportId>/publish")
@require_roles("ComplianceDirector")
def publish(reportId):
    rec = _load(reportId)
    if rec["status"] != "APPROVED":
        raise invalid_state("BoardReport is not in APPROVED status")
    for r in db.STORES["runs"].values():
        if periods_overlap(
            r["period_start"], r["period_end"], rec["period_start"], rec["period_end"]
        ) and r["status"] not in ("FINALIZED", "ARCHIVED"):
            raise err(
                "ERR_REPORT_NOT_READY",
                "An overlapping AnalysisRun is not FINALIZED/ARCHIVED",
            )
    rec["status"] = "PUBLISHED"
    rec["published_at"] = db.now_iso()
    db.touch(rec)
    return success_obj(db.public(rec))
