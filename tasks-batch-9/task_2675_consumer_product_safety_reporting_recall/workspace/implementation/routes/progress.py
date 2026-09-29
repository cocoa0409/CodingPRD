"""Monthly effectiveness progress reporting (PRD 3.8)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import lookups
import responses
import shapes
import store
from errors import raise_error

bp = Blueprint("progress", __name__)

BASES = ("UNITS_BASIS", "PARTICIPATION_BASIS")
PROGRESS_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED")
ASSESSMENTS = ("PENDING", "ON_TRACK", "BELOW_TARGET", "CRITICAL")
FILED_STATUSES = ("SUBMITTED", "ACCEPTED")

ROLES = ("ProgramAdmin", "ComplianceOfficer", "SafetyDirector", "PenaltyCounsel")


@bp.route("/progress-reports/<report_id>", methods=["GET"])
def get_progress_report(report_id):
    auth.authorize(*ROLES)
    return responses.object_response(lookups.find("progress_report", report_id))


@bp.route("/progress-reports", methods=["GET"])
def list_progress_reports():
    auth.authorize(*ROLES)
    limit, offset = shapes.pagination()
    recall_id = shapes.q_str("recall_id")
    status = shapes.q_enum("status", PROGRESS_STATUSES)
    basis = shapes.q_enum("effectiveness_basis", BASES)
    assessment = shapes.q_enum("assessment", ASSESSMENTS)

    def keep(row):
        if recall_id is not None and row["recall_id"] != recall_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if basis is not None and row["effectiveness_basis"] != basis:
            return False
        if assessment is not None and row["assessment"] != assessment:
            return False
        return True

    return responses.list_response(
        store.ordered(store.progress_reports, keep), limit, offset)


@bp.route("/progress-reports", methods=["POST"])
def create_progress_report():
    actor = auth.authorize("ComplianceOfficer", "SafetyDirector")
    data = shapes.body()
    recall_id = shapes._req(data, "recall_id")
    period_start = shapes.req_ts(data, "period_start")
    period_end = shapes.req_ts(data, "period_end")
    basis = shapes.req_enum(data, "effectiveness_basis", BASES)
    if not period_start < period_end:
        shapes.bad()

    recall = lookups.find("recall", recall_id)
    if recall["plan_status"] not in ("APPROVED", "MONITORING"):
        raise_error("ERR_RECALL_PLAN_STATE_INVALID")

    filed = [p for p in store.progress_reports.values()
             if p["recall_id"] == recall_id and p["status"] in FILED_STATUSES]

    # Closed intervals: touching endpoints do overlap.
    for other in filed:
        if period_start <= other["period_end"] and other["period_start"] <= period_end:
            raise_error("ERR_REPORT_PERIOD_OVERLAP")

    if filed:
        latest_end = max(p["period_end"] for p in filed)
        if period_start != latest_end + store.hours(24):
            raise_error("ERR_REPORT_PERIOD_GAP")
    else:
        if (recall["stop_sale_effective_at"] is None
                or period_start != recall["stop_sale_effective_at"]):
            raise_error("ERR_REPORT_PERIOD_GAP")

    row = store.new_row(
        recall_id=recall_id,
        period_start=period_start,
        period_end=period_end,
        effectiveness_basis=basis,
        status="DRAFT",
        units_corrected_in_period=0,
        cumulative_units_corrected=0,
        effectiveness_rate=store.rhu(Decimal("0"), 2),
        assessment="PENDING",
        prepared_by_user_id=actor.user_id,
        submitted_at=None,
        accepted_at=None,
    )
    store.progress_reports[row["id"]] = row
    return responses.created(row)


@bp.route("/progress-reports/<report_id>/submit", methods=["POST"])
def submit_progress_report(report_id):
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    report = lookups.find("progress_report", report_id)
    shapes.body()

    if report["status"] != "DRAFT":
        raise_error("ERR_PROGRESS_REPORT_STATE_INVALID")

    recall = lookups.maybe("recall", report["recall_id"])
    in_period = 0
    if recall is not None:
        for claim in store.remedy_claims.values():
            if claim["recall_id"] != recall["id"]:
                continue
            if claim["status"] != "FULFILLED" or claim["fulfilled_at"] is None:
                continue
            if (claim["fulfilled_at"] >= report["period_start"]
                    and claim["fulfilled_at"] <= report["period_end"]):
                in_period += claim["quantity"]

    model = lookups.model_for_recall(recall) if recall is not None else None
    rate = (calc.effectiveness_rate(recall, report["effectiveness_basis"], model)
            if recall is not None else store.rhu(Decimal("0"), 2))

    report["status"] = "SUBMITTED"
    report["submitted_at"] = store.now_logical()
    report["units_corrected_in_period"] = in_period
    report["cumulative_units_corrected"] = (
        recall["units_corrected"] if recall is not None else 0)
    report["effectiveness_rate"] = rate
    report["assessment"] = calc.assessment_for(
        rate, recall["participation_goal_pct"]) if recall is not None else "PENDING"
    store.touch(report)
    return responses.object_response(report)


@bp.route("/progress-reports/<report_id>/accept", methods=["POST"])
def accept_progress_report(report_id):
    actor = auth.authorize("SafetyDirector")
    report = lookups.find("progress_report", report_id)
    shapes.body()

    # Segregation of duties (ordering step 7) precedes the state check (step 9).
    if (report["prepared_by_user_id"] is not None
            and actor.user_id == report["prepared_by_user_id"]):
        raise_error("ERR_SEGREGATION_OF_DUTIES")

    if report["status"] != "SUBMITTED":
        raise_error("ERR_PROGRESS_REPORT_STATE_INVALID")

    report["status"] = "ACCEPTED"
    report["accepted_at"] = store.now_logical()
    store.touch(report)

    recall = lookups.maybe("recall", report["recall_id"])
    if recall is not None:
        recall["last_accepted_period_end"] = report["period_end"]
        if report["assessment"] == "CRITICAL":
            recall["effectiveness_flag"] = "SHORTFALL"
        store.touch(recall)

    return responses.object_response(report)
