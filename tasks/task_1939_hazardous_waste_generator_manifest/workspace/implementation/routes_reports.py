"""BiennialReport endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, request

from core import (
    base_entity,
    bump,
    compute_final_fee,
    compute_provisional_fee_cents,
    now_iso,
)
from db import _parse_iso, iso_utc, store
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_REPORT_PERIOD_OVERLAP,
    ERR_REPORT_YEAR_NOT_ODD,
    already_terminal,
    invalid_request,
    invalid_state,
    not_found,
)
from middleware import require_roles
from response import success_list, success_object
from validators import (
    reject_unknown_fields,
    req_enum,
    req_int,
    req_str,
    require_fields,
    require_object,
)

bp = Blueprint("reports", __name__)

ALL_ROLES = ("EHSManager", "WasteCoordinator", "ComplianceAuditor", "TransporterAgent", "TSDFAgent")


def _parse_pagination():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (ValueError, TypeError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (ValueError, TypeError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def report_view(r: dict) -> dict:
    return dict(r)


@bp.route("/hazwaste/biennial-reports", methods=["POST"])
def create_report():
    user_id, _ = require_roles("EHSManager")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"site_id", "report_year"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["site_id", "report_year"])
    site_id = req_str(body, "site_id")
    report_year = req_int(body, "report_year")

    # shape band: odd year
    if report_year % 2 == 0:
        raise ApiError(ERR_REPORT_YEAR_NOT_ODD, 400, "report_year must be an odd integer")

    site = store.sites.get(site_id)
    if site is None:
        raise not_found("site not found")

    # Uniqueness per (site, year)
    for r in store.reports.values():
        if r["site_id"] == site_id and r["report_year"] == report_year:
            raise ApiError(ERR_REPORT_PERIOD_OVERLAP, 409, "report already exists for this site and year")

    period_start = datetime(report_year, 1, 1, tzinfo=timezone.utc)
    period_end = datetime(report_year + 1, 1, 1, tzinfo=timezone.utc)
    due_at = datetime(report_year + 1, 3, 1, tzinfo=timezone.utc)

    r = base_entity()
    r.update(
        {
            "site_id": site_id,
            "report_year": report_year,
            "period_start": iso_utc(period_start),
            "period_end": iso_utc(period_end),
            "due_at": iso_utc(due_at),
            "status": "DRAFT",
            "category_snapshot": site["generator_category"],
            "provisional_shipped_kg": 0,
            "final_shipped_kg": 0,
            "provisional_fee_cents": 0,
            "final_fee_cents": 0,
            "is_late": False,
            "days_late": 0,
            "submitted_at": None,
        }
    )
    store.reports[r["id"]] = r

    cat, kg, fee = compute_provisional_fee_cents(site, r)
    r["category_snapshot"] = cat
    r["provisional_shipped_kg"] = kg
    r["provisional_fee_cents"] = fee

    return success_object(report_view(r), status=201)


@bp.route("/hazwaste/biennial-reports", methods=["GET"])
def list_reports():
    require_roles(*ALL_ROLES)
    limit, offset = _parse_pagination()
    site_id = request.args.get("site_id")
    items = list(store.reports.values())
    if site_id is not None:
        items = [r for r in items if r["site_id"] == site_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([report_view(r) for r in page], limit, offset, total)


@bp.route("/hazwaste/biennial-reports/<reportId>", methods=["GET"])
def get_report(reportId: str):
    require_roles(*ALL_ROLES)
    r = store.reports.get(reportId)
    if r is None:
        raise not_found("report not found")
    return success_object(report_view(r))


@bp.route("/hazwaste/biennial-reports/<reportId>/submit", methods=["POST"])
def submit_report(reportId: str):
    user_id, _ = require_roles("EHSManager")
    r = store.reports.get(reportId)
    if r is None:
        raise not_found("report not found")
    body = request.get_json(silent=True) or {}
    if body:
        require_object(body)
        reject_unknown_fields(body, set())

    if r["status"] == "ACCEPTED":
        raise already_terminal("report is accepted")
    if r["status"] != "DRAFT":
        raise invalid_state(f"cannot submit from {r['status']}")

    r["submitted_at"] = now_iso()
    cat, kg, fee, is_late, days_late = compute_final_fee(r)
    r["category_snapshot"] = cat
    r["final_shipped_kg"] = kg
    r["final_fee_cents"] = fee
    r["is_late"] = is_late
    r["days_late"] = days_late
    r["status"] = "SUBMITTED"
    bump(r)
    return success_object(report_view(r))


@bp.route("/hazwaste/biennial-reports/<reportId>/review", methods=["POST"])
def review_report(reportId: str):
    user_id, _ = require_roles("ComplianceAuditor")
    r = store.reports.get(reportId)
    if r is None:
        raise not_found("report not found")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"outcome"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["outcome"])
    outcome = req_enum(body, "outcome", {"ACCEPT", "REJECT"})

    if r["status"] == "ACCEPTED":
        raise already_terminal("report is accepted")
    if r["status"] != "SUBMITTED":
        raise invalid_state(f"cannot review from {r['status']}")

    if outcome == "ACCEPT":
        r["status"] = "ACCEPTED"
    else:
        r["status"] = "DRAFT"
        r["submitted_at"] = None
        # leave provisional fee to be re-derived on next flip; no recompute here
    bump(r)
    return success_object(report_view(r))
