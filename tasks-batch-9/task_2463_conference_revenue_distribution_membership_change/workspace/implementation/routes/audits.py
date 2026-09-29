"""Audit reports and the cent-conservation identity (PRD section 3.9)."""

from flask import Blueprint

import response
import serializers
import validation
from db import base_record, db, touch
from errors import ApiError
from middleware import api, current_user_id, raw_body
from routes import common
from services import distribution

bp = Blueprint("audits", __name__)

REPORT_READ_ROLES = (
    "Commissioner",
    "FinanceOfficer",
    "Treasurer",
    "Auditor",
    "ComplianceOfficer",
    "PlatformAdmin",
    "MemberRepresentative",
)

OPINIONS = ("UNQUALIFIED", "QUALIFIED", "ADVERSE")


@bp.route("/audit-reports", methods=["POST"])
@api(("Auditor",))
def create_report():
    body = raw_body()
    conference_id = validation.get_id(body, "conference_id")
    distribution_run_id = validation.get_id(body, "distribution_run_id")
    fiscal_year = validation.get_int(body, "fiscal_year", minimum=None)
    opinion = validation.get_enum(body, "opinion", OPINIONS)
    note = validation.get_optional_str(body, "note")

    run = common.get_run(distribution_run_id)
    if run["status"] != "COMPUTED":
        raise ApiError("ERR_RUN_STATE_INVALID")

    report = base_record()
    report.update(
        {
            "conference_id": conference_id,
            "distribution_run_id": distribution_run_id,
            "fiscal_year": fiscal_year,
            "opinion": opinion,
            "note": note,
            "reconciliation_delta_cents": 0,
            "status": "DRAFT",
            "issued_by_user_id": None,
            "accepted_by_user_id": None,
        }
    )
    db.audit_reports[report["id"]] = report
    return response.single(serializers.audit_report(report), 201)


@bp.route("/audit-reports/<report_id>", methods=["GET"])
@api(REPORT_READ_ROLES)
def read_report(report_id):
    return response.single(serializers.audit_report(common.get_report(report_id)))


@bp.route("/audit-reports", methods=["GET"])
@api(REPORT_READ_ROLES)
def list_reports():
    criteria = {
        "conference_id": common.string_filter("conference_id"),
        "distribution_run_id": common.string_filter("distribution_run_id"),
        "fiscal_year": common.int_filter("fiscal_year"),
        "status": common.string_filter("status"),
    }
    return common.listing(
        list(db.audit_reports.values()), serializers.audit_report, criteria=criteria
    )


@bp.route("/audit-reports/<report_id>/issue", methods=["POST"])
@api(("Auditor",))
def issue_report(report_id):
    report = common.get_report(report_id)
    run = db.distribution_runs.get(report["distribution_run_id"])

    if report["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_STATE_INVALID")
    if run is not None and current_user_id() == run["computed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    delta = distribution.reconciliation(run)["reconciliation_delta_cents"]
    if delta != 0:
        raise ApiError("ERR_RECONCILIATION_IMBALANCE")

    report["reconciliation_delta_cents"] = delta
    report["status"] = "ISSUED"
    report["issued_by_user_id"] = current_user_id()
    touch(report)
    return response.single(serializers.audit_report(report))


@bp.route("/audit-reports/<report_id>/accept", methods=["POST"])
@api(("Commissioner",))
def accept_report(report_id):
    report = common.get_report(report_id)
    run = db.distribution_runs.get(report["distribution_run_id"])

    if report["status"] != "ISSUED":
        raise ApiError("ERR_REPORT_STATE_INVALID")
    if run is None or run["status"] != "POSTED":
        # The only refusal this endpoint declares.
        raise ApiError("ERR_REPORT_STATE_INVALID")

    report["status"] = "ACCEPTED"
    report["accepted_by_user_id"] = current_user_id()
    touch(report)
    return response.single(serializers.audit_report(report))
