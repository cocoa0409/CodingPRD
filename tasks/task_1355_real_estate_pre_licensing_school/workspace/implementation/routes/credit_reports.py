"""Credit report endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import require_roles, get_json_body, parse_pagination, parse_date
from response import success_object, success_list
from services.calculations import (
    build_credit_report_lines, build_amendment_lines,
    compute_reporting_deadline, compute_late_fee, _extract_date,
)

bp = Blueprint("credit_reports", __name__)


def _report_to_json(r):
    return {k: v for k, v in r.items()}


def _get_report(report_id):
    r = db.credit_reports.get(report_id)
    if not r:
        errors.raise_error(errors.ERR_CREDIT_REPORT_NOT_FOUND,
                           f"CreditReport {report_id} not found")
    return r


def _check_director_scope_for_report(report, auth):
    """Director scope check via school."""
    if auth["role"] == "SchoolDirector":
        school = db.schools.get(report["school_id"])
        if school and school.get("director_user_id") != auth["user_id"]:
            errors.raise_error(errors.ERR_FORBIDDEN_SCOPE, "Not own school")


@bp.route("/credit-reports", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_credit_report():
    body = get_json_body(
        required_fields=["school_id", "period_start", "period_end"],
        optional_fields=["reason"],
    )
    auth = request.auth

    school = db.schools.get(body["school_id"])
    if not school:
        errors.raise_error(errors.ERR_SCHOOL_NOT_FOUND, f"School {body['school_id']} not found")

    period_start = parse_date(body["period_start"], "period_start")
    period_end = parse_date(body["period_end"], "period_end")

    if period_end < period_start:
        errors.raise_error(errors.ERR_REPORT_WINDOW_INVALID,
                           "period_end must be >= period_start")

    # Check base report overlap (closed-interval: adjacency IS a conflict)
    for r in db.credit_reports.values():
        if r["school_id"] != body["school_id"]:
            continue
        if r.get("amendment_of_id") is not None:
            continue  # Only base reports
        r_start = _extract_date(r["period_start"])
        r_end = _extract_date(r["period_end"])
        if r_start is None or r_end is None:
            continue
        # Closed interval overlap: conflict unless new.end < r.start OR new.start > r.end
        if period_end < r_start or period_start > r_end:
            continue
        errors.raise_error(errors.ERR_REPORT_PERIOD_OVERLAP,
                           "Overlapping base report exists for this school")

    # Build line items
    line_items, total_hours = build_credit_report_lines(
        body["school_id"], period_start, period_end
    )

    reporting_deadline = compute_reporting_deadline(period_end)

    report = db.new_entity({
        "school_id": body["school_id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "amendment_of_id": None,
        "reason": body.get("reason"),
        "status": "DRAFT",
        "line_items": line_items,
        "total_credit_hours": total_hours,
        "reporting_deadline_date": reporting_deadline.isoformat(),
        "submitted_at": None,
        "late_days": 0,
        "late_fee_cents": 0,
        "submission_count": 0,
    })
    db.credit_reports[report["id"]] = report
    db.audit("CreditReport", report["id"], "REPORT_CREATED",
             auth["role"], auth["user_id"])
    return success_object(_report_to_json(report), 201)


@bp.route("/credit-reports", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "ComplianceOfficer")
def list_credit_reports():
    limit, offset = parse_pagination()
    items = list(db.credit_reports.values())

    auth = request.auth

    school_id = request.args.get("school_id")
    if school_id:
        items = [r for r in items if r["school_id"] == school_id]

    status_filter = request.args.get("status")
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]

    amendment_of_id = request.args.get("amendment_of_id")
    if amendment_of_id:
        items = [r for r in items if r.get("amendment_of_id") == amendment_of_id]

    # Director scope
    if auth["role"] == "SchoolDirector":
        own_school_ids = {s["id"] for s in db.schools.values() if s.get("director_user_id") == auth["user_id"]}
        items = [r for r in items if r["school_id"] in own_school_ids]

    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([_report_to_json(r) for r in page], limit, offset, total)


@bp.route("/credit-reports/<id>", methods=["GET"])
@require_roles("StateCommission", "SchoolDirector", "ComplianceOfficer")
def get_credit_report(id):
    report = _get_report(id)
    auth = request.auth
    _check_director_scope_for_report(report, auth)
    return success_object(_report_to_json(report))


@bp.route("/credit-reports/<id>/submit", methods=["POST"])
@require_roles("ComplianceOfficer")
def submit_credit_report(id):
    report = _get_report(id)
    auth = request.auth

    if report["status"] != "DRAFT":
        errors.raise_error(errors.ERR_REPORT_STATE_INVALID,
                           f"Report status is {report['status']}, expected DRAFT")

    submit_date = db.today()
    deadline = _extract_date(report["reporting_deadline_date"])
    late_days, late_fee = compute_late_fee(deadline, submit_date)

    report["status"] = "SUBMITTED"
    report["submitted_at"] = db.now_iso()
    report["late_days"] = late_days
    report["late_fee_cents"] = late_fee
    report["submission_count"] = report.get("submission_count", 0) + 1
    db.touch(report)
    db.audit("CreditReport", report["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "DRAFT", "to_status": "SUBMITTED"})
    return success_object(_report_to_json(report))


@bp.route("/credit-reports/<id>/acknowledge", methods=["POST"])
@require_roles("StateCommission")
def acknowledge_credit_report(id):
    report = _get_report(id)
    auth = request.auth

    if report["status"] != "SUBMITTED":
        errors.raise_error(errors.ERR_REPORT_STATE_INVALID,
                           f"Report status is {report['status']}, expected SUBMITTED")

    report["status"] = "ACKNOWLEDGED"
    db.touch(report)
    db.audit("CreditReport", report["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "SUBMITTED", "to_status": "ACKNOWLEDGED"})
    return success_object(_report_to_json(report))


@bp.route("/credit-reports/<id>/reject", methods=["POST"])
@require_roles("StateCommission")
def reject_credit_report(id):
    report = _get_report(id)
    auth = request.auth

    body = get_json_body(required_fields=["reason"])

    if report["status"] != "SUBMITTED":
        errors.raise_error(errors.ERR_REPORT_STATE_INVALID,
                           f"Report status is {report['status']}, expected SUBMITTED")

    report["status"] = "REJECTED"
    db.touch(report)
    db.audit("CreditReport", report["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "SUBMITTED", "to_status": "REJECTED"})
    return success_object(_report_to_json(report))


@bp.route("/credit-reports/<id>/revise", methods=["POST"])
@require_roles("ComplianceOfficer")
def revise_credit_report(id):
    report = _get_report(id)
    auth = request.auth

    if report["status"] != "REJECTED":
        errors.raise_error(errors.ERR_REPORT_STATE_INVALID,
                           f"Report status is {report['status']}, expected REJECTED")

    # Recompute line items from current certificate states
    period_start = _extract_date(report["period_start"])
    period_end = _extract_date(report["period_end"])

    if report.get("amendment_of_id"):
        # Amendment: recompute from parent
        parent = db.credit_reports.get(report["amendment_of_id"])
        if parent:
            lines, total = build_amendment_lines(parent)
            report["line_items"] = lines
            report["total_credit_hours"] = total
    else:
        # Base report: recompute
        lines, total = build_credit_report_lines(
            report["school_id"], period_start, period_end
        )
        report["line_items"] = lines
        report["total_credit_hours"] = total

    report["status"] = "DRAFT"
    report["submitted_at"] = None
    db.touch(report)
    db.audit("CreditReport", report["id"], "STATUS_CHANGE",
             auth["role"], auth["user_id"],
             {"from_status": "REJECTED", "to_status": "DRAFT"})
    return success_object(_report_to_json(report))


@bp.route("/credit-reports/<id>/amendments", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_amendment(id):
    report = _get_report(id)
    auth = request.auth

    body = get_json_body(
        required_fields=["reason", "expected_credit_report_version"],
    )

    # OCC check
    expected = body["expected_credit_report_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "expected_credit_report_version must be an integer")
    if expected != report["version"]:
        errors.raise_error(errors.ERR_STALE_CREDIT_REPORT_VERSION,
                           f"Expected version {expected}, current {report['version']}")

    # State: must be ACKNOWLEDGED
    if report["status"] != "ACKNOWLEDGED":
        errors.raise_error(errors.ERR_REPORT_STATE_INVALID,
                           f"Report status is {report['status']}, expected ACKNOWLEDGED")

    # Build amendment lines
    lines, total = build_amendment_lines(report)

    amendment = db.new_entity({
        "school_id": report["school_id"],
        "period_start": report["period_start"],
        "period_end": report["period_end"],
        "amendment_of_id": id,
        "reason": body["reason"],
        "status": "DRAFT",
        "line_items": lines,
        "total_credit_hours": total,
        "reporting_deadline_date": report["reporting_deadline_date"],
        "submitted_at": None,
        "late_days": 0,
        "late_fee_cents": 0,
        "submission_count": 0,
    })
    db.credit_reports[amendment["id"]] = amendment

    # Increment parent report version
    db.touch(report)

    db.audit("CreditReport", amendment["id"], "AMENDMENT_CREATED",
             auth["role"], auth["user_id"],
             {"note": f"Amendment of report {id}"})
    return success_object(_report_to_json(amendment), 201)
