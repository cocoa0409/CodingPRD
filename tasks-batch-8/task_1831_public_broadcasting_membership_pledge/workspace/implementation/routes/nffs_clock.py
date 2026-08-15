"""NFFS reports and the logical clock."""

from datetime import datetime, timezone

from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES
from middleware import require_roles
from services import core

bp = Blueprint("nffs_clock", __name__)


def _fy_window(fiscal_year):
    start = datetime(fiscal_year, 1, 1, tzinfo=timezone.utc)
    end = datetime(fiscal_year + 1, 1, 1, tzinfo=timezone.utc)
    return start, end


def _drive_in_fy(drive, fy_start, fy_end):
    s = db.parse_dt(drive["starts_at"])
    return fy_start <= s < fy_end


def compute_membership_revenue(fiscal_year, variant):
    """nffs_membership_revenue calculation.

    PROVISIONAL: PLEDGED at (amount_cents - fmv_deduction); PAID/PARTIAL at net_collected_cents; else 0.
    FINAL: only PAID/PARTIAL at net_collected_cents.
    """
    fy_start, fy_end = _fy_window(fiscal_year)
    total = 0
    for p in db.pledges.values():
        drive = db.drives.get(p["drive_id"])
        if drive is None or not _drive_in_fy(drive, fy_start, fy_end):
            continue
        if variant == "PROVISIONAL":
            if p["payment_status"] == "PLEDGED":
                total += p["amount_cents"] - core.compute_fmv_deduction(p)
            elif p["payment_status"] in ("PAID", "PARTIAL"):
                total += p["net_collected_cents"]
            # DECLINED / WRITTEN_OFF contribute 0
        else:  # FINAL
            if p["payment_status"] in ("PAID", "PARTIAL"):
                total += p["net_collected_cents"]
    return total


def compute_underwriting_excluded(fiscal_year):
    fy_start, fy_end = _fy_window(fiscal_year)
    total = 0
    for c in db.credits.values():
        if not c["aired"]:
            continue
        drive = db.drives.get(c["drive_id"])
        if drive is None or not _drive_in_fy(drive, fy_start, fy_end):
            continue
        total += c["amount_cents"]
    return total


def compute_matching_revenue(fiscal_year):
    fy_start, fy_end = _fy_window(fiscal_year)
    total = 0
    for c in db.challenges.values():
        if c["status"] != "MET":
            continue
        drive = db.drives.get(c["drive_id"])
        if drive is None or not _drive_in_fy(drive, fy_start, fy_end):
            continue
        total += c["match_cents"]
    return total


def _compute_all(report, variant):
    fy = report["fiscal_year"]
    report["membership_revenue_cents"] = compute_membership_revenue(fy, variant)
    report["underwriting_excluded_cents"] = compute_underwriting_excluded(fy)
    report["matching_revenue_cents"] = compute_matching_revenue(fy)


@bp.route("/station/nffs-reports", methods=["POST"])
def create_report():
    body = v.get_json_body()
    user_id, _ = require_roles("MembershipCoordinator")
    fiscal_year = v.req_int(body, "fiscal_year")

    ent = db.new_entity()
    ent.update({
        "fiscal_year": fiscal_year,
        "variant": "PROVISIONAL",
        "status": "DRAFT",
        "membership_revenue_cents": 0,
        "underwriting_excluded_cents": 0,
        "matching_revenue_cents": 0,
        "drafted_by_user_id": user_id,
        "finalized_by_user_id": None,
    })
    _compute_all(ent, "PROVISIONAL")
    db.nffs_reports[ent["id"]] = ent
    return response.success_object(ent, status=201)


@bp.route("/station/nffs-reports/<rid>", methods=["GET"])
def get_report(rid):
    require_roles("StationAdmin", "MembershipCoordinator")
    ent = db.nffs_reports.get(rid)
    if ent is None:
        v.not_found(f"NFFSReport '{rid}' not found")
    return response.success_object(ent)


@bp.route("/station/nffs-reports/<rid>/finalize", methods=["POST"])
def finalize_report(rid):
    v.get_json_body(required=False)
    user_id, _ = require_roles("StationAdmin")
    report = db.nffs_reports.get(rid)
    if report is None:
        v.not_found(f"NFFSReport '{rid}' not found")
    if report["status"] not in ("DRAFT", "AMENDED"):
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Report status is {report['status']}, must be DRAFT or AMENDED",
                       ERR_INVALID_STATE[1])
    if user_id == report["drafted_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES[0],
                       "Finalizer must differ from the report drafter",
                       ERR_SEGREGATION_OF_DUTIES[1])
    report["status"] = "FINALIZED"
    report["variant"] = "FINAL"
    report["finalized_by_user_id"] = user_id
    _compute_all(report, "FINAL")
    db.touch(report)
    return response.success_object(report)


@bp.route("/station/nffs-reports/<rid>/amend", methods=["POST"])
def amend_report(rid):
    v.get_json_body(required=False)
    user_id, _ = require_roles("StationAdmin")
    report = db.nffs_reports.get(rid)
    if report is None:
        v.not_found(f"NFFSReport '{rid}' not found")
    if report["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE[0],
                       f"Report status is {report['status']}, must be FINALIZED",
                       ERR_INVALID_STATE[1])
    report["status"] = "AMENDED"
    report["variant"] = "PROVISIONAL"
    _compute_all(report, "PROVISIONAL")
    db.touch(report)
    return response.success_object(report)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/station/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = v.get_json_body()
    require_roles("StationAdmin")
    to_dt = v.req_dt(body, "to_iso8601")
    db.set_now(to_dt)
    core.apply_clock_transitions(to_dt)
    return response.success_object({})
