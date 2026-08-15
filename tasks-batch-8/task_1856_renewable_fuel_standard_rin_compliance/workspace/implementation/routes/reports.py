"""ComplianceReport endpoints: create (with OCC + supersede), get, list, submit, decide, reopen."""
from datetime import timedelta
from flask import Blueprint, request

import db
from errors import (
    invalid_request, not_found, reference_not_found, invalid_state,
    stale_version, segregation, attest_not_clean,
)
from middleware import require_roles, json_body
from response import ok_object, ok_list, parse_pagination, paginate
from serializers import report_view

bp = Blueprint("reports", __name__)


def _get_report(report_id):
    report = db.compliance_reports.get(report_id)
    if report is None:
        raise not_found("Compliance report not found")
    return report


@bp.route("/rfs/compliance-reports", methods=["POST"])
def create_report():
    user_id, _ = require_roles("ComplianceManager")
    body = json_body()

    obligation_year_id = body.get("obligation_year_id")
    report_type = body.get("report_type")
    quarter_end_date_raw = body.get("quarter_end_date")
    expected_version = body.get("expected_obligation_year_version")

    # --- Request shape (priority 5) ---
    if obligation_year_id is None:
        raise invalid_request("obligation_year_id is required")
    if report_type not in ("QUARTERLY", "ANNUAL"):
        raise invalid_request("report_type must be QUARTERLY or ANNUAL")
    quarter_end_date = None
    if report_type == "QUARTERLY":
        if quarter_end_date_raw is None:
            raise invalid_request("quarter_end_date is required for QUARTERLY reports")
        try:
            quarter_end_date = db.parse_iso(quarter_end_date_raw)
        except (ValueError, TypeError):
            raise invalid_request("quarter_end_date must be a valid ISO 8601 datetime")
    else:  # ANNUAL
        if quarter_end_date_raw is not None:
            raise invalid_request("quarter_end_date is forbidden for ANNUAL reports")

    # --- Referential integrity (priority 6) ---
    year = db.obligation_years.get(obligation_year_id)
    if year is None:
        raise reference_not_found("Referenced obligation year does not exist")

    # --- OCC (priority 7): expected_obligation_year_version must match ---
    if expected_version is None:
        raise invalid_request("expected_obligation_year_version is required")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise invalid_request("expected_obligation_year_version must be an integer")
    if expected_version != year["version"]:
        raise stale_version("expected_obligation_year_version does not match the year's current version")

    # --- State (priority 8): no reports for a FINALIZED year; same-type non-DRAFT blocks ---
    if year["status"] == "FINALIZED":
        raise invalid_state("No reports may be created for a FINALIZED year")

    prior_same_type = [
        r for r in db.compliance_reports.values()
        if r["obligation_year_id"] == year["id"] and r["report_type"] == report_type
    ]
    for r in prior_same_type:
        if r["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED"):
            raise invalid_state("A same-type report in a non-DRAFT state blocks creation")

    now = db.now_utc()

    # Supersede the prior same-type DRAFT (at most one can exist)
    for r in prior_same_type:
        if r["status"] == "DRAFT":
            r["status"] = "SUPERSEDED"
            r["version"] += 1
            r["updated_at"] = now

    # due_date: QUARTERLY = quarter_end_date + 60 days; ANNUAL = (year+1)-03-31T23:59:59Z
    if report_type == "QUARTERLY":
        due_date = quarter_end_date + timedelta(days=60)
    else:
        due_date = db.march31_deadline(year["year"] + 1)

    report = {
        "id": db.new_id(),
        "obligation_year_id": obligation_year_id,
        "report_type": report_type,
        "quarter_end_date": quarter_end_date,
        "due_date": due_date,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "submitted_at": None,
        "is_late": False,
        "amendment_required": False,
        "retention_until": db.retention_until_from(now),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.compliance_reports[report["id"]] = report

    # Report creation advances the year's version
    year["version"] += 1
    year["updated_at"] = now

    return ok_object(report_view(report), status=201)


@bp.route("/rfs/compliance-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    require_roles("OpsAdmin", "ComplianceManager", "Trader", "Auditor")
    return ok_object(report_view(_get_report(report_id)))


@bp.route("/rfs/compliance-reports", methods=["GET"])
def list_reports():
    require_roles("OpsAdmin", "ComplianceManager", "Trader", "Auditor")
    limit, offset = parse_pagination(request.args)
    obligation_year_id = request.args.get("obligation_year_id")
    rows = list(db.compliance_reports.values())
    if obligation_year_id is not None:
        rows = [r for r in rows if r["obligation_year_id"] == obligation_year_id]
    rows.sort(key=lambda r: r["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([report_view(r) for r in page], limit, offset, total)


@bp.route("/rfs/compliance-reports/<report_id>/submit", methods=["POST"])
def submit_report(report_id):
    user_id, _ = require_roles("ComplianceManager")
    report = _get_report(report_id)
    year = db.obligation_years[report["obligation_year_id"]]

    # Segregation (priority 3): submitter must not be an auditor on the same year
    for eng in db.attest_engagements.values():
        if eng["obligation_year_id"] == year["id"] and eng["auditor_user_id"] == user_id:
            raise segregation("Report submitter is an auditor on the same obligation year")

    # State: report must be DRAFT; year must not be FINALIZED
    if report["status"] != "DRAFT":
        raise invalid_state("Compliance report is not DRAFT")
    if year["status"] == "FINALIZED":
        raise invalid_state("Obligation year is FINALIZED")

    # Regulatory gate: ANNUAL requires a CLOSED_CLEAN attest engagement for the year
    if report["report_type"] == "ANNUAL":
        has_clean = any(
            e["obligation_year_id"] == year["id"] and e["status"] == "CLOSED_CLEAN"
            for e in db.attest_engagements.values()
        )
        if not has_clean:
            raise attest_not_clean("ANNUAL report submission requires a CLOSED_CLEAN attest engagement")

    now = db.now_utc()
    report["status"] = "SUBMITTED"
    report["submitted_at"] = now
    report["is_late"] = now > report["due_date"]
    report["version"] += 1
    report["updated_at"] = now
    return ok_object(report_view(report))


@bp.route("/rfs/compliance-reports/<report_id>/decide", methods=["POST"])
def decide_report(report_id):
    require_roles("OpsAdmin")
    report = _get_report(report_id)
    body = json_body()
    decision = body.get("decision")
    if decision not in ("ACCEPT", "REJECT"):
        raise invalid_request("decision must be ACCEPT or REJECT")
    if report["status"] != "SUBMITTED":
        raise invalid_state("Compliance report is not SUBMITTED")

    report["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    report["version"] += 1
    report["updated_at"] = db.now_utc()
    return ok_object(report_view(report))


@bp.route("/rfs/compliance-reports/<report_id>/reopen", methods=["POST"])
def reopen_report(report_id):
    require_roles("ComplianceManager")
    report = _get_report(report_id)
    if report["status"] not in ("REJECTED", "ACCEPTED"):
        raise invalid_state("Only a REJECTED or ACCEPTED report can be reopened")

    report["status"] = "DRAFT"
    report["amendment_required"] = False
    report["submitted_at"] = None
    report["is_late"] = False
    report["version"] += 1
    report["updated_at"] = db.now_utc()
    return ok_object(report_view(report))
