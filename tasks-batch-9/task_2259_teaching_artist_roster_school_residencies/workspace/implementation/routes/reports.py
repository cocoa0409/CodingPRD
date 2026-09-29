"""Funder reports: the compiled snapshot and its certification."""
from flask import Blueprint, request

import db
import middleware as mw
import response
from enums import HEADCOUNT_BASES, REPORT_STATUSES
from errors import ApiError
from routes.residencies import find_residency
from services import calc, derive
from validators import Payload, bad

bp = Blueprint("reports", __name__)


def find_report(report_id):
    report = db.funder_reports.get(report_id)
    if report is None:
        raise ApiError("ERR_FUNDER_REPORT_NOT_FOUND", "funder report %s not found" % report_id)
    return report


def invalid_transition(message="the requested transition is not declared from the current state"):
    return ApiError("ERR_INVALID_STATE_TRANSITION", message)


@bp.post("/funder-reports")
def create_report():
    mw.auth("ProgramDirector")
    body = Payload(request.get_json(silent=True))
    funder_name = body.string("funder_name", required=True)
    grant_code = body.string("grant_code", required=True)
    period_start = body.date("period_start", required=True)
    period_end = body.date("period_end", required=True)
    scope_ids = body.array("scope_residency_ids", required=True)
    headcount_basis = body.enum("headcount_basis", HEADCOUNT_BASES, required=True)
    if period_end < period_start:
        bad("period_end must not be earlier than period_start")

    for residency_id in scope_ids:                                # 5
        find_residency(residency_id)

    row = db.base_row()
    row.update({
        "funder_name": funder_name,
        "grant_code": grant_code,
        "period_start": period_start,
        "period_end": period_end,
        "scope_residency_ids": list(scope_ids),
        "headcount_basis": headcount_basis,
        "status": "DRAFT",
        "compiled_by_user_id": None,
        "certified_by_user_id": None,
        "attestation_text": None,
        "invalidated_reason": None,
        "sessions_delivered_total": 0,
        "students_served": 0,
        "frl_students_reached": 0,
        "ell_students_reached": 0,
        "iep_students_reached": 0,
        "direct_cost_cents": 0,
        "indirect_cost_cents": 0,
        "total_spend_cents": 0,
        "cost_per_student_cents": 0,
    })
    db.funder_reports[row["id"]] = row
    return response.ok(derive.report_view(row), 201)


@bp.get("/funder-reports/<report_id>")
def read_report(report_id):
    mw.auth()
    return response.ok(derive.report_view(find_report(report_id)))


@bp.get("/funder-reports")
def list_reports():
    mw.auth()
    limit, offset = mw.pagination()
    grant_code = mw.q_str("grant_code")
    status = mw.q_enum("status", REPORT_STATUSES)
    scope = mw.q_str("scope_residency_ids")

    rows = db.ordered(list(db.funder_reports.values()))
    if grant_code:
        rows = [r for r in rows if r["grant_code"] == grant_code]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if scope:
        wanted = [part for part in scope.split(",") if part]
        rows = [r for r in rows
                if all(rid in r["scope_residency_ids"] for rid in wanted)]
    page, total = mw.page(rows, limit, offset)
    return response.ok_list([derive.report_view(r) for r in page], limit, offset, total)


@bp.post("/funder-reports/<report_id>/compile")
def compile_report(report_id):
    user_id, _role = mw.auth("ProgramDirector")
    report = find_report(report_id)

    current = report["status"]
    if current not in ("DRAFT", "COMPILED"):                      # 8
        raise invalid_transition()
    if current == "DRAFT":
        for residency_id in report["scope_residency_ids"]:
            find_residency(residency_id)

    report.update(calc.funder_report_metrics(report))
    report["compiled_by_user_id"] = user_id
    report["status"] = "COMPILED"
    if current == "DRAFT":
        report["invalidated_reason"] = None
    db.touch(report)
    return response.ok(derive.report_view(report))


@bp.post("/funder-reports/<report_id>/certify")
def certify_report(report_id):
    mw.auth("FiscalOfficer")
    report = find_report(report_id)
    body = Payload(request.get_json(silent=True))
    certifier_user_id = body.string("certifier_user_id", required=True)
    attestation_text = body.string("attestation_text", required=True)

    if report["status"] != "COMPILED":                            # 8
        raise invalid_transition()

    for residency_id in report["scope_residency_ids"]:            # 15
        residency = db.residencies.get(residency_id)
        if residency is None or residency["status"] not in ("COMPLETED", "CLOSED"):
            raise ApiError("ERR_RESIDENCY_NOT_FINALIZED",
                           "residency %s is not finalized" % residency_id)
    if report["invalidated_reason"] is not None:
        raise ApiError("ERR_RESIDENCY_NOT_FINALIZED",
                       "the compiled snapshot is stale and must be recompiled")

    if certifier_user_id == report["compiled_by_user_id"]:        # 16
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the certifier may not be the operator who compiled the report")

    report["certified_by_user_id"] = certifier_user_id
    report["attestation_text"] = attestation_text
    report["status"] = "CERTIFIED"
    db.touch(report)
    return response.ok(derive.report_view(report))
