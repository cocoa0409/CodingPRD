"""ScreeningReport + ReportFinding endpoints (report delivery)."""
from flask import Blueprint, request

import db
from db import bump
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_ORDER_NOT_DISPATCHED, ERR_MATRIX_NOT_ACTIVE,
    ERR_FINDING_NOT_IN_PACKAGE,
)
from middleware import (
    auth, require_role, get_body, req_str, forbid, invalid,
    parse_pagination, sort_key, ALL_ROLES,
)
from response import success_object, success_list
from services import (
    active_rule_for, active_matrix_for, evaluate_finding,
    recommended_outcome, findings_of_report,
)
from timeutil import now, parse_iso, business_hours_between

bp = Blueprint("reports", __name__)

OFFENSE_CATEGORIES = (
    "VIOLENT_FELONY", "NONVIOLENT_FELONY", "MISDEMEANOR", "INFRACTION",
    "ARREST_NO_CONVICTION", "EMPLOYMENT_DISCREPANCY",
    "EDUCATION_DISCREPANCY", "SANCTIONS_HIT",
)
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
DISPOSITIONS = ("CONVICTION", "DISMISSED", "PENDING", "ARREST_ONLY")
CHECK_TYPES = (
    "CRIMINAL_COUNTY", "CRIMINAL_STATE", "CRIMINAL_FEDERAL", "SSN_TRACE",
    "EMPLOYMENT_VERIFY", "EDUCATION_VERIFY", "MVR", "CREDIT_CHECK",
    "GLOBAL_SANCTIONS",
)

SLA_CREDIT_PCT = 10
BREACH_PROBATION_THRESHOLD = 3


def validate_finding_shape(raw):
    """Validate one finding payload; returns a normalized finding dict."""
    if not isinstance(raw, dict):
        invalid("each finding must be an object")
    check_type = raw.get("check_type")
    if not isinstance(check_type, str) or check_type not in CHECK_TYPES:
        invalid("finding check_type invalid")
    category = raw.get("offense_category")
    if not isinstance(category, str) or category not in OFFENSE_CATEGORIES:
        invalid("finding offense_category invalid")
    severity = raw.get("severity")
    if not isinstance(severity, str) or severity not in SEVERITIES:
        invalid("finding severity invalid")
    raw_offense = raw.get("offense_date")
    if raw_offense is None:
        invalid("finding offense_date is required")
    try:
        offense_dt = parse_iso(raw_offense)
    except (ValueError, TypeError):
        invalid("finding offense_date must be an ISO 8601 instant")
    # time component ignored; treated as 00:00:00Z
    offense_dt = offense_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    disposition = raw.get("disposition")
    if not isinstance(disposition, str) or disposition not in DISPOSITIONS:
        invalid("finding disposition invalid")
    return {
        "check_type": check_type,
        "offense_category": category,
        "severity": severity,
        "offense_date": offense_dt,
        "disposition": disposition,
    }


def create_finding_rows(report, raw_findings):
    rows = []
    for raw in raw_findings:
        finding = db.new_entity({
            "report_id": report["id"],
            "check_type": raw["check_type"],
            "offense_category": raw["offense_category"],
            "severity": raw["severity"],
            "offense_date": raw["offense_date"],
            "disposition": raw["disposition"],
            "considerable": None,
            "matched_action": None,
        })
        db.findings[finding["id"]] = finding
        rows.append(finding)
    return rows


@bp.route("/screening-reports", methods=["POST"])
def create_report():
    uid, role = auth()
    require_role(role, {"VendorAgent"})
    body = get_body()
    # existence (3): body order_id must resolve
    raw_order = body.get("order_id")
    if raw_order is not None and raw_order not in db.orders:
        raise ApiError(ERR_NOT_FOUND, 404, "Order not found")
    order_id = req_str(body, "order_id")
    order = db.orders[order_id]
    # entity-backed ownership (2.5): the assigned vendor delivers
    if uid != order["vendor_id"]:
        forbid("Only the assigned vendor may deliver this order's report")
    # shape (3.8)
    raw_findings = body.get("findings")
    if not isinstance(raw_findings, list):
        invalid("findings must be an array")
    parsed = [validate_finding_shape(f) for f in raw_findings]
    # state (4): order DISPATCHED
    if order["fulfillment_status"] != "DISPATCHED":
        raise ApiError(ERR_ORDER_NOT_DISPATCHED, 409,
                       "Report delivery requires fulfillment DISPATCHED")
    # state (4): an ACTIVE matrix must exist for the position's risk tier
    position = db.positions.get(order["position_id"])
    matrix = active_matrix_for(position["risk_tier"]) if position else None
    if matrix is None:
        raise ApiError(ERR_MATRIX_NOT_ACTIVE, 409,
                       "Report delivery requires an ACTIVE matrix for the "
                       "position's risk tier")
    # referential (8.3): every finding check_type in the pinned package
    package = db.packages.get(order["pinned_package_id"])
    package_checks = package["check_types"] if package else []
    for f in parsed:
        if f["check_type"] not in package_checks:
            raise ApiError(ERR_FINDING_NOT_IN_PACKAGE, 422,
                           "Finding check_type not in the pinned package's "
                           "check_types")
    # ---- side effects (atomic) ----
    delivered_at = now()
    vendor = db.vendors[order["vendor_id"]]
    report = db.new_entity({
        "order_id": order["id"],
        "vendor_id": order["vendor_id"],
        "delivered_at": delivered_at,
        "turnaround_business_hours": None,
        "sla_breached": None,
        "status": "DELIVERED",
    })
    db.reports[report["id"]] = report
    tat = package["tat_business_hours"]
    turnaround = business_hours_between(order["dispatched_at"], delivered_at)
    report["turnaround_business_hours"] = turnaround
    sla_breached = turnaround > tat
    report["sla_breached"] = sla_breached
    # vendor counters
    vendor["active_order_count"] -= 1
    if sla_breached:
        vendor["consecutive_sla_breaches"] += 1
    else:
        vendor["consecutive_sla_breaches"] = 0
    if (vendor["consecutive_sla_breaches"] >= BREACH_PROBATION_THRESHOLD
            and vendor["status"] == "ACTIVE"):
        vendor["status"] = "PROBATION"
    bump(vendor)
    # fees
    if order["order_type"] == "RESCREEN":
        order["final_fee_cents"] = 0
    elif sla_breached:
        provisional = order["provisional_fee_cents"]
        credit = (provisional * SLA_CREDIT_PCT) // 100
        order["final_fee_cents"] = max(0, provisional - credit)
    else:
        order["final_fee_cents"] = order["provisional_fee_cents"]
    # findings + outcome against ACTIVE jurisdiction rule + ACTIVE matrix
    rule = active_rule_for(position["jurisdiction_code"])
    findings = create_finding_rows(report, parsed)
    for f in findings:
        evaluate_finding(f, rule, position, delivered_at, matrix)
    order["recommended_outcome"] = recommended_outcome(findings)
    order["pinned_matrix_id"] = matrix["id"]
    order["pinned_matrix_version"] = matrix["version"]
    order["fulfillment_status"] = "REPORT_RECEIVED"
    order["adjudication_status"] = "PENDING_REVIEW"
    bump(order)
    return success_object(report, 201)


@bp.route("/screening-reports", methods=["GET"])
def list_reports():
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.reports.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        rows = [r for r in rows if r["order_id"] == order_id]
    vendor_id = request.args.get("vendor_id")
    if vendor_id is not None:
        rows = [r for r in rows if r["vendor_id"] == vendor_id]
    rows.sort(key=sort_key)
    total = len(rows)
    return success_list(rows[offset:offset + limit], limit, offset, total)


def _load_report(report_id):
    report = db.reports.get(report_id)
    if report is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Report not found")
    return report


@bp.route("/screening-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    return success_object(_load_report(report_id), 200)


@bp.route("/screening-reports/<report_id>/findings", methods=["GET"])
def list_findings(report_id):
    auth_uid, role = auth()
    require_role(role, ALL_ROLES)
    report = _load_report(report_id)
    limit, offset = parse_pagination()
    rows = findings_of_report(report["id"])
    total = len(rows)
    return success_list(rows[offset:offset + limit], limit, offset, total)
