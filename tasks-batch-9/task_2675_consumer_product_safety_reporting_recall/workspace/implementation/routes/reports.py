"""Statutory report preparation, filing, review and revision (PRD 3.4)."""

from flask import Blueprint

import auth
import calc
import lookups
import responses
import shapes
import store
from errors import raise_error

bp = Blueprint("reports", __name__)

CORRECTIVE_ACTION_TYPES = ("REPAIR", "REPLACE", "REFUND", "RETROFIT_KIT")
REPORT_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED_FOR_INFO")
REVIEW_DECISIONS = ("ACCEPTED", "RETURNED_FOR_INFO")
LIVE_REPORT_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED")

READ_ROLES = ("ProgramAdmin", "ComplianceOfficer", "SafetyDirector",
              "PenaltyCounsel")


@bp.route("/section-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    auth.authorize(*READ_ROLES)
    return responses.object_response(lookups.find("section_report", report_id))


@bp.route("/section-reports", methods=["GET"])
def list_reports():
    auth.authorize(*READ_ROLES)
    limit, offset = shapes.pagination()
    evaluation_id = shapes.q_str("reportability_evaluation_id")
    status = shapes.q_enum("status", REPORT_STATUSES)
    action_type = shapes.q_enum("corrective_action_type", CORRECTIVE_ACTION_TYPES)

    def keep(row):
        if evaluation_id is not None and row["reportability_evaluation_id"] != evaluation_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if action_type is not None and row["corrective_action_type"] != action_type:
            return False
        return True

    return responses.list_response(
        store.ordered(store.section_reports, keep), limit, offset)


@bp.route("/section-reports", methods=["POST"])
def create_report():
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    data = shapes.body()
    evaluation_id = shapes._req(data, "reportability_evaluation_id")
    action_type = shapes.req_enum(data, "corrective_action_type",
                                  CORRECTIVE_ACTION_TYPES)
    summary = shapes.req_str(data, "corrective_action_summary", 1, 2000)

    evaluation = lookups.find("evaluation", evaluation_id)
    if evaluation["status"] != "REPORTABLE":
        raise_error("ERR_EVALUATION_STATE_INVALID")

    for existing in store.section_reports.values():
        if (existing["reportability_evaluation_id"] == evaluation_id
                and existing["status"] in LIVE_REPORT_STATUSES):
            raise_error("ERR_DUPLICATE_DOCKET_ENTRY")

    row = store.new_row(
        reportability_evaluation_id=evaluation_id,
        corrective_action_type=action_type,
        corrective_action_summary=summary,
        status="DRAFT",
        submitted_at=None,
        days_late=0,
        late_surcharge_cents=0,
        reviewed_at=None,
    )
    store.section_reports[row["id"]] = row
    return responses.created(row)


@bp.route("/section-reports/<report_id>/submit", methods=["POST"])
def submit_report(report_id):
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    report = lookups.find("section_report", report_id)
    shapes.body()

    if report["status"] != "DRAFT":
        raise_error("ERR_SECTION_REPORT_STATE_INVALID")

    submitted_at = store.now_logical()
    evaluation = lookups.maybe("evaluation", report["reportability_evaluation_id"])
    report_due_at = evaluation["report_due_at"] if evaluation else None
    days_late, surcharge = calc.lateness(report_due_at, submitted_at)

    report["status"] = "SUBMITTED"
    report["submitted_at"] = submitted_at
    report["days_late"] = days_late
    report["late_surcharge_cents"] = surcharge
    store.touch(report)

    model = lookups.model_for_report(report)
    if model is not None:
        model["hazard_posture"] = "RESTRICTED"
        store.touch(model)

    return responses.object_response(report)


@bp.route("/section-reports/<report_id>/review", methods=["POST"])
def review_report(report_id):
    auth.authorize("SafetyDirector")
    report = lookups.find("section_report", report_id)
    data = shapes.body()
    decision = shapes.req_enum(data, "decision", REVIEW_DECISIONS)
    shapes.opt_str(data, "note", 0, 2000)

    if report["status"] != "SUBMITTED":
        raise_error("ERR_SECTION_REPORT_STATE_INVALID")

    report["reviewed_at"] = store.now_logical()
    report["status"] = decision
    store.touch(report)

    if decision == "RETURNED_FOR_INFO":
        model = lookups.model_for_report(report)
        if model is not None:
            model["hazard_posture"] = "FROZEN"
            store.touch(model)

    return responses.object_response(report)


@bp.route("/section-reports/<report_id>/revise", methods=["POST"])
def revise_report(report_id):
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    report = lookups.find("section_report", report_id)
    data = shapes.body()
    action_type = shapes.opt_enum(data, "corrective_action_type",
                                 CORRECTIVE_ACTION_TYPES)
    summary = shapes.opt_str(data, "corrective_action_summary", 1, 2000)

    if report["status"] != "RETURNED_FOR_INFO":
        raise_error("ERR_SECTION_REPORT_STATE_INVALID")

    if action_type is not shapes.MISSING:
        report["corrective_action_type"] = action_type
    if summary is not shapes.MISSING:
        report["corrective_action_summary"] = summary
    report["status"] = "DRAFT"
    report["submitted_at"] = None
    store.touch(report)
    return responses.object_response(report)
