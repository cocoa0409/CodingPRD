"""Tier-2 subcontracting reports from prime contractors (PRD 3.4)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_PRIME_ONLY,
    ERR_REPORT_NOT_EDITABLE,
    ERR_SUPPLIER_NOT_ELIGIBLE,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import (
    make_record,
    touch,
    pub_tier2_report,
    compute_tier2_totals,
    supplier_certs,
)
from util import parse_period
from validate import get_body, req_str, get_resource

bp = Blueprint("tier2", __name__)

PRIME = ["PrimeContact"]
ADMIN_ANALYST = ["DiversityAdmin", "DiversityAnalyst"]
READERS = ["DiversityAdmin", "DiversityAnalyst", "Auditor", "PrimeContact"]


def _parse_lines(body):
    """Presence + shape; returns the raw lines list (foreign keys unchecked)."""
    lines = body.get("lines")
    if lines is None or not isinstance(lines, list):
        raise_error(ERR_INVALID_REQUEST, "lines must be an array")
    for line in lines:
        if not isinstance(line, dict):
            raise_error(ERR_INVALID_REQUEST, "each line must be an object")
    return lines


def _check_line_foreign_keys(lines):
    """Existence rung: every line's diverse_supplier_id must resolve."""
    for line in lines:
        sid = line.get("diverse_supplier_id")
        if sid is None or not isinstance(sid, str) or sid == "":
            raise_error(ERR_INVALID_REQUEST, "line missing diverse_supplier_id")
        if sid not in db["suppliers"]:
            raise_error(ERR_NOT_FOUND, f"supplier not found: {sid}")


def _validate_line_amounts(lines):
    """Structural rung: gross > 0 and 0 < diverse_share_pct <= 100.00."""
    normalized = []
    for line in lines:
        gross = line.get("gross_subcontract_cents")
        if gross is None or isinstance(gross, bool) or not isinstance(gross, int) or gross <= 0:
            raise_error(ERR_INVALID_REQUEST, "gross_subcontract_cents must be an integer > 0")
        raw_pct = line.get("diverse_share_pct")
        if raw_pct is None or isinstance(raw_pct, bool) or not isinstance(raw_pct, (int, float, str)):
            raise_error(ERR_INVALID_REQUEST, "diverse_share_pct must be a number")
        try:
            pct = Decimal(str(raw_pct))
        except Exception:
            raise_error(ERR_INVALID_REQUEST, "diverse_share_pct must be a number")
        if pct.is_nan() or pct.is_infinite() or pct <= 0 or pct > Decimal("100.00"):
            raise_error(ERR_INVALID_REQUEST, "diverse_share_pct must be in (0, 100.00]")
        normalized.append({
            "diverse_supplier_id": line["diverse_supplier_id"],
            "gross_subcontract_cents": gross,
            "diverse_share_pct": float(pct),
        })
    return normalized


def _check_ownership(report, caller):
    if caller.role == "PrimeContact" and report["prime_supplier_id"] != caller.user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "PrimeContact may only touch its own reports")


@bp.route("/api/v1/tier-2-reports", methods=["POST"])
def create_tier2_report():
    caller = authorized(PRIME)
    body = get_body()
    prime_supplier_id = body.get("prime_supplier_id")
    if prime_supplier_id is None or not isinstance(prime_supplier_id, str) or prime_supplier_id == "":
        raise_error(ERR_INVALID_REQUEST, "missing or invalid field: prime_supplier_id")
    # Ownership rung precedes existence (PRD 2.8).
    if prime_supplier_id != caller.user_id:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "prime_supplier_id must equal X-User-ID")
    prime = get_resource("suppliers", prime_supplier_id)
    business_unit_id = req_str(body, "business_unit_id")
    get_resource("business_units", business_unit_id)
    lines = _parse_lines(body)
    _check_line_foreign_keys(lines)
    # Eligibility rung: only PRIME/BOTH suppliers file tier-2 reports.
    if prime["kind"] not in ("PRIME", "BOTH"):
        raise_error(ERR_PRIME_ONLY, "supplier kind is not PRIME or BOTH")
    # Structural rung.
    reporting_period = req_str(body, "reporting_period")
    if parse_period(reporting_period) is None:
        raise_error(ERR_INVALID_REQUEST, "reporting_period must match 'YYYY-Qn'")
    norm_lines = _validate_line_amounts(lines)
    total_sub, total_div = compute_tier2_totals(norm_lines)
    rec = make_record({
        "prime_supplier_id": prime_supplier_id,
        "business_unit_id": business_unit_id,
        "reporting_period": reporting_period,
        "lines": norm_lines,
        "total_subcontracted_cents": total_sub,
        "total_diverse_tier2_cents": total_div,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "reviewed_by_user_id": None,
    })
    db["tier2_reports"][rec["id"]] = rec
    return success_object(pub_tier2_report(rec), status=201)


@bp.route("/api/v1/tier-2-reports", methods=["GET"])
def list_tier2_reports():
    authorized(READERS)
    filters = {
        "prime_supplier_id": request.args.get("prime_supplier_id"),
        "business_unit_id": request.args.get("business_unit_id"),
        "reporting_period": request.args.get("reporting_period"),
        "status": request.args.get("status"),
    }
    return list_response(list(db["tier2_reports"].values()), filters, pub_tier2_report)


@bp.route("/api/v1/tier-2-reports/<rid>", methods=["GET"])
def get_tier2_report(rid):
    authorized(READERS)
    rec = get_resource("tier2_reports", rid)
    return success_object(pub_tier2_report(rec))


@bp.route("/api/v1/tier-2-reports/<rid>", methods=["PUT"])
def replace_tier2_lines(rid):
    caller = authorized(PRIME)
    report = get_resource("tier2_reports", rid)
    _check_ownership(report, caller)
    body = get_body()
    lines = _parse_lines(body)
    _check_line_foreign_keys(lines)
    if report["status"] not in ("DRAFT", "RETURNED"):
        raise_error(ERR_REPORT_NOT_EDITABLE, "lines are editable only in DRAFT or RETURNED")
    norm_lines = _validate_line_amounts(lines)
    total_sub, total_div = compute_tier2_totals(norm_lines)
    report["lines"] = norm_lines
    report["total_subcontracted_cents"] = total_sub
    report["total_diverse_tier2_cents"] = total_div
    touch(report)
    return success_object(pub_tier2_report(report))


@bp.route("/api/v1/tier-2-reports/<rid>/submit", methods=["POST"])
def submit_tier2_report(rid):
    caller = authorized(PRIME)
    report = get_resource("tier2_reports", rid)
    _check_ownership(report, caller)
    if report["status"] not in ("DRAFT", "RETURNED"):
        raise_error(ERR_INVALID_STATE, "submit requires status DRAFT or RETURNED")
    if not report["lines"]:
        raise_error(ERR_INVALID_REQUEST, "lines must be non-empty to submit")
    report["status"] = "SUBMITTED"
    report["submitted_by_user_id"] = caller.user_id
    touch(report)
    return success_object(pub_tier2_report(report))


@bp.route("/api/v1/tier-2-reports/<rid>/approve", methods=["POST"])
def approve_tier2_report(rid):
    caller = authorized(["DiversityAdmin"])
    report = get_resource("tier2_reports", rid)
    if report["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "approve requires status SUBMITTED")
    _year, _q, _start, period_end = parse_period(report["reporting_period"])
    for line in report["lines"]:
        sup = db["suppliers"].get(line["diverse_supplier_id"])
        if sup is None or sup["kind"] not in ("DIVERSE", "BOTH"):
            raise_error(ERR_SUPPLIER_NOT_ELIGIBLE, "line supplier is not DIVERSE or BOTH")
        covered = any(
            c["status"] in ("VERIFIED", "EXPIRED")
            and c["valid_from"] <= period_end <= c["valid_to"]
            for c in supplier_certs(sup["id"])
        )
        if not covered:
            raise_error(
                ERR_SUPPLIER_NOT_ELIGIBLE,
                "line supplier lacks a VERIFIED/EXPIRED certification covering the period end",
            )
    # Exactly-one-approved invariant per (prime_supplier_id, reporting_period).
    for other in db["tier2_reports"].values():
        if (other["id"] != report["id"]
                and other["status"] == "APPROVED"
                and other["prime_supplier_id"] == report["prime_supplier_id"]
                and other["reporting_period"] == report["reporting_period"]):
            other["status"] = "SUPERSEDED"
            touch(other)
    report["status"] = "APPROVED"
    report["reviewed_by_user_id"] = caller.user_id
    touch(report)
    return success_object(pub_tier2_report(report))


@bp.route("/api/v1/tier-2-reports/<rid>/return", methods=["POST"])
def return_tier2_report(rid):
    authorized(ADMIN_ANALYST)
    report = get_resource("tier2_reports", rid)
    if report["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "return requires status SUBMITTED")
    report["status"] = "RETURNED"
    touch(report)
    return success_object(pub_tier2_report(report))
