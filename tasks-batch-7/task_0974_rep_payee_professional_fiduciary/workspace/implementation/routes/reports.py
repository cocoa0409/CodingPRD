"""Accounting reports endpoints."""

from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_CLIENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REPORT_NOT_FOUND,
    ERR_REPORT_OVERDUE,
    ERR_REPORT_PERIOD_GAP,
    ERR_REPORT_PERIOD_OVERLAP,
    err,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import serialize_report
from services.calcs import compute_report_totals
from services.cascade import clock_now_iso, clock_date
from util import (
    new_id,
    parse_date,
    parse_pagination,
    require_body,
    get_string,
    get_enum,
    reject_unexpected,
)

bp = Blueprint("reports", __name__)

READ_ROLES = ("FiduciaryAdmin", "CaseManager", "FinancialOfficer", "ConservatorOfficer", "ComplianceAuditor")
REPORT_TYPES = ("SSA_6233", "COURT_ANNUAL")
BASES = ("CASH", "ACCRUAL")
REPORT_DUE_DAYS = 30


@bp.route("/accounting-reports", methods=["POST"])
def create_report():
    require_roles("CaseManager")
    body = require_body()
    reject_unexpected(body, {
        "client_id", "report_type", "period_start_date", "period_end_date", "basis",
    })
    client_id = get_string(body, "client_id")
    report_type = get_enum(body, "report_type", REPORT_TYPES)
    ps = parse_date(get_string(body, "period_start_date"), "period_start_date")
    pe = parse_date(get_string(body, "period_end_date"), "period_end_date")
    basis = get_enum(body, "basis", BASES)
    if pe < ps:
        raise err(ERR_INVALID_REQUEST, 400, "period_end_date must be >= period_start_date")

    if client_id not in store.clients:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")

    # contiguity check over SUBMITTED/ACCEPTED reports for same (client, type)
    peers = [
        r for r in store.reports.values()
        if r["client_id"] == client_id
        and r["report_type"] == report_type
        and r["status"] in ("SUBMITTED", "ACCEPTED")
    ]
    if peers:
        # overlap: new period intersects any existing peer period
        for r in peers:
            if ps <= r["period_end_date"] and pe >= r["period_start_date"]:
                raise err(ERR_REPORT_PERIOD_OVERLAP, 409, "period overlaps existing report")
        # contiguity: must start exactly previous_end + 1
        latest_end = max(r["period_end_date"] for r in peers)
        expected_start = latest_end + timedelta(days=1)
        if ps > expected_start:
            raise err(ERR_REPORT_PERIOD_GAP, 409, "period gap: must start previous_end + 1 day")
        # if ps < expected_start and no overlap, that means entirely before chain — also a gap-like problem.
        # We only reach here if no overlap. Allow if ps == expected_start.
        if ps < expected_start:
            # before the chain starts; doesn't overlap, but spec only checks "previous end + 1"
            # when prior report exists. Treat as gap.
            raise err(ERR_REPORT_PERIOD_GAP, 409, "period must start previous_end + 1 day")

    due = pe + timedelta(days=REPORT_DUE_DAYS)
    now = clock_now_iso()
    rid = new_id()
    r = {
        "id": rid,
        "client_id": client_id,
        "report_type": report_type,
        "period_start_date": ps,
        "period_end_date": pe,
        "basis": basis,
        "due_date": due,
        "receipts_total_cents": None,
        "disbursements_total_cents": None,
        "opening_balance_cents": None,
        "ending_balance_cents": None,
        "submitted_at": None,
        "status": "DRAFTING",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.reports[rid] = r
    return success_object(serialize_report(r), status=201)


@bp.route("/accounting-reports", methods=["GET"])
def list_reports():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    client_id = request.args.get("client_id")
    report_type = request.args.get("report_type")
    status = request.args.get("status")
    items = list(store.reports.values())
    if client_id is not None:
        items = [r for r in items if r["client_id"] == client_id]
    if report_type is not None:
        items = [r for r in items if r["report_type"] == report_type]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_report(r) for r in page], limit, offset, total)


def _get_or_404(rid):
    r = store.reports.get(rid)
    if not r:
        raise err(ERR_REPORT_NOT_FOUND, 404, "report not found")
    return r


@bp.route("/accounting-reports/<rid>", methods=["GET"])
def get_report(rid):
    require_roles(*READ_ROLES)
    r = _get_or_404(rid)
    return success_object(serialize_report(r))


@bp.route("/accounting-reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    require_roles("FinancialOfficer")
    r = _get_or_404(rid)
    if r["status"] in ("ACCEPTED", "REJECTED"):
        raise err(ERR_ALREADY_TERMINAL, 409, "Report is terminal")
    if r["status"] != "DRAFTING":
        raise err(ERR_INVALID_STATE, 409, "Only DRAFTING -> SUBMITTED")
    c = store.clients.get(r["client_id"])
    if not c:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")
    if c["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err(ERR_CLIENT_NOT_ACTIVE, 409, "Client must be ACTIVE or SUSPENDED")
    now_date = clock_date()
    if now_date > r["due_date"]:
        raise err(ERR_REPORT_OVERDUE, 422, "Report is overdue")
    receipts, disb, opening, ending = compute_report_totals(r)
    r["receipts_total_cents"] = receipts
    r["disbursements_total_cents"] = disb
    r["opening_balance_cents"] = opening
    r["ending_balance_cents"] = ending
    now = clock_now_iso()
    r["submitted_at"] = now
    r["status"] = "SUBMITTED"
    r["updated_at"] = now
    r["version"] += 1
    return success_object(serialize_report(r))


@bp.route("/accounting-reports/<rid>/accept", methods=["POST"])
def accept_report(rid):
    require_roles("ComplianceAuditor")
    r = _get_or_404(rid)
    if r["status"] in ("ACCEPTED", "REJECTED"):
        raise err(ERR_ALREADY_TERMINAL, 409, "Report is terminal")
    if r["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, 409, "Only SUBMITTED -> ACCEPTED")
    now = clock_now_iso()
    r["status"] = "ACCEPTED"
    r["updated_at"] = now
    r["version"] += 1
    return success_object(serialize_report(r))


@bp.route("/accounting-reports/<rid>/reject", methods=["POST"])
def reject_report(rid):
    require_roles("ComplianceAuditor")
    r = _get_or_404(rid)
    if r["status"] in ("ACCEPTED", "REJECTED"):
        raise err(ERR_ALREADY_TERMINAL, 409, "Report is terminal")
    if r["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, 409, "Only SUBMITTED -> REJECTED")
    now = clock_now_iso()
    r["status"] = "REJECTED"
    r["updated_at"] = now
    r["version"] += 1
    return success_object(serialize_report(r))
