"""The recall plan and its two independent state dimensions (PRD 3.5)."""

from flask import Blueprint

import auth
import lookups
import responses
import shapes
import store
from errors import raise_error

bp = Blueprint("recalls", __name__)

REMEDY_TYPES = ("REPAIR", "REPLACE", "REFUND", "RETROFIT_KIT")
PLAN_STATUSES = ("DRAFT", "SUBMITTED", "APPROVED", "MONITORING", "CLOSED")
NOTIFICATION_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "DEFICIENT", "SATISFIED")
EFFECTIVENESS_FLAGS = ("PENDING", "MET", "SHORTFALL")

READ_ROLES = ("ProgramAdmin", "ComplianceOfficer", "SafetyDirector",
              "FieldAuditor", "PenaltyCounsel", "RetailerRep")
LIST_ROLES = ("ProgramAdmin", "ComplianceOfficer", "SafetyDirector",
              "FieldAuditor", "PenaltyCounsel")


@bp.route("/recalls/<recall_id>", methods=["GET"])
def get_recall(recall_id):
    auth.authorize(*READ_ROLES)
    return responses.object_response(lookups.find("recall", recall_id))


@bp.route("/recalls", methods=["GET"])
def list_recalls():
    auth.authorize(*LIST_ROLES)
    limit, offset = shapes.pagination()
    section_report_id = shapes.q_str("section_report_id")
    plan_status = shapes.q_enum("plan_status", PLAN_STATUSES)
    notification_status = shapes.q_enum("notification_status", NOTIFICATION_STATUSES)
    effectiveness_flag = shapes.q_enum("effectiveness_flag", EFFECTIVENESS_FLAGS)

    def keep(row):
        if section_report_id is not None and row["section_report_id"] != section_report_id:
            return False
        if plan_status is not None and row["plan_status"] != plan_status:
            return False
        if (notification_status is not None
                and row["notification_status"] != notification_status):
            return False
        if (effectiveness_flag is not None
                and row["effectiveness_flag"] != effectiveness_flag):
            return False
        return True

    return responses.list_response(store.ordered(store.recalls, keep), limit, offset)


@bp.route("/recalls", methods=["POST"])
def create_recall():
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    data = shapes.body()
    section_report_id = shapes._req(data, "section_report_id")
    remedy_options = shapes.req_enum_array(data, "remedy_options", REMEDY_TYPES)
    units_in_commerce = shapes.req_int(data, "units_in_commerce", minimum=1)
    goal = shapes.req_decimal(data, "participation_goal_pct", 2,
                              maximum=100, exclusive_minimum=0)
    correction_deadline_at = shapes.req_ts(data, "correction_deadline_at")

    report = lookups.find("section_report", section_report_id)
    if report["status"] != "ACCEPTED":
        raise_error("ERR_SECTION_REPORT_STATE_INVALID")

    for existing in store.recalls.values():
        if existing["section_report_id"] == section_report_id:
            raise_error("ERR_DUPLICATE_DOCKET_ENTRY")

    row = store.new_row(
        section_report_id=section_report_id,
        remedy_options=remedy_options,
        units_in_commerce=units_in_commerce,
        participation_goal_pct=goal,
        correction_deadline_at=correction_deadline_at,
        plan_status="DRAFT",
        notification_status="NOT_STARTED",
        units_corrected=0,
        units_outstanding=units_in_commerce,
        effectiveness_flag="PENDING",
        stop_sale_effective_at=None,
        submitted_by_user_id=None,
        last_accepted_period_end=None,
    )
    store.recalls[row["id"]] = row
    return responses.created(row)


def notifications_of(recall_id, predicate=None):
    def keep(row):
        if row["recall_id"] != recall_id:
            return False
        return predicate is None or predicate(row)

    return store.ordered(store.retailer_notifications, keep)


@bp.route("/recalls/<recall_id>/submit-plan", methods=["POST"])
def submit_plan(recall_id):
    actor = auth.authorize("ComplianceOfficer", "SafetyDirector")
    recall = lookups.find("recall", recall_id)
    shapes.body()

    if recall["plan_status"] != "DRAFT":
        raise_error("ERR_RECALL_PLAN_STATE_INVALID")

    has_direct_notice = any(
        n["recall_id"] == recall_id
        and n["channel"] == "DIRECT_NOTICE"
        and n["status"] in ("SCHEDULED", "RELEASED")
        for n in store.consumer_notices.values())
    if not has_direct_notice:
        raise_error("ERR_DIRECT_NOTICE_REQUIRED")

    recall["plan_status"] = "SUBMITTED"
    recall["submitted_by_user_id"] = actor.user_id
    store.touch(recall)
    return responses.object_response(recall)


@bp.route("/recalls/<recall_id>/approve-plan", methods=["POST"])
def approve_plan(recall_id):
    actor = auth.authorize("SafetyDirector")
    recall = lookups.find("recall", recall_id)
    shapes.body()

    # Segregation of duties (ordering step 7) precedes the state check (step 9).
    if (recall["submitted_by_user_id"] is not None
            and actor.user_id == recall["submitted_by_user_id"]):
        raise_error("ERR_SEGREGATION_OF_DUTIES")

    if recall["plan_status"] != "SUBMITTED":
        raise_error("ERR_RECALL_PLAN_STATE_INVALID")

    effective_at = store.now_logical()
    recall["plan_status"] = "APPROVED"
    recall["stop_sale_effective_at"] = effective_at

    pending = notifications_of(recall_id, lambda n: n["status"] == "PENDING")
    for notification in pending:
        notification["status"] = "ISSUED"
        notification["stop_sale_required"] = True
        notification["issued_at"] = effective_at
        notification["ack_due_at"] = effective_at + store.hours(72)
        store.touch(notification)

        retailer = lookups.maybe("retailer", notification["retailer_id"])
        if retailer is not None:
            retailer["open_stop_sale_count"] = retailer["open_stop_sale_count"] + 1
            retailer["compliance_posture"] = "STOP_SALE_ACTIVE"
            store.touch(retailer)

    # The notification dimension only moves when at least one row actually flipped.
    if pending and recall["notification_status"] == "NOT_STARTED":
        recall["notification_status"] = "IN_PROGRESS"

    store.touch(recall)
    return responses.object_response(recall)


@bp.route("/recalls/<recall_id>/begin-monitoring", methods=["POST"])
def begin_monitoring(recall_id):
    auth.authorize("SafetyDirector")
    recall = lookups.find("recall", recall_id)
    shapes.body()

    if recall["plan_status"] != "APPROVED":
        raise_error("ERR_RECALL_PLAN_STATE_INVALID")

    released = any(n["recall_id"] == recall_id and n["status"] == "RELEASED"
                   for n in store.consumer_notices.values())
    if not released:
        raise_error("ERR_CONSUMER_NOTICE_NOT_RELEASED")

    recall["plan_status"] = "MONITORING"
    store.touch(recall)
    return responses.object_response(recall)


@bp.route("/recalls/<recall_id>/compliance-sweep", methods=["POST"])
def compliance_sweep(recall_id):
    auth.authorize("SafetyDirector", "ComplianceOfficer")
    recall = lookups.find("recall", recall_id)
    shapes.body()

    if recall["plan_status"] not in ("APPROVED", "MONITORING"):
        raise_error("ERR_RECALL_PLAN_STATE_INVALID")

    now = store.now_logical()

    def overdue(row):
        return (row["status"] == "ISSUED"
                and row["ack_due_at"] is not None
                and now > row["ack_due_at"])

    flipped = notifications_of(recall_id, overdue)
    for notification in flipped:
        notification["status"] = "DELINQUENT"
        store.touch(notification)
        retailer = lookups.maybe("retailer", notification["retailer_id"])
        if retailer is not None:
            retailer["delinquent_count"] = retailer["delinquent_count"] + 1
            retailer["compliance_posture"] = "DELINQUENT"
            store.touch(retailer)

    if flipped and recall["notification_status"] == "IN_PROGRESS":
        recall["notification_status"] = "DEFICIENT"
        store.touch(recall)

    return responses.object_response(recall)


@bp.route("/recalls/<recall_id>/close", methods=["POST"])
def close_recall(recall_id):
    auth.authorize("SafetyDirector")
    recall = lookups.find("recall", recall_id)
    shapes.body()

    if recall["plan_status"] != "MONITORING":
        raise_error("ERR_RECALL_PLAN_STATE_INVALID")
    if recall["notification_status"] != "SATISFIED":
        raise_error("ERR_NOTIFICATION_NOT_SATISFIED")
    accepted = any(p["recall_id"] == recall_id and p["status"] == "ACCEPTED"
                   for p in store.progress_reports.values())
    if not accepted:
        raise_error("ERR_PROGRESS_REPORT_REQUIRED")
    if recall["effectiveness_flag"] != "MET":
        raise_error("ERR_EFFECTIVENESS_NOT_MET")

    recall["plan_status"] = "CLOSED"
    store.touch(recall)

    model = lookups.model_for_recall(recall)
    if model is not None:
        still_open = False
        for other in store.recalls.values():
            if other["id"] == recall["id"]:
                continue
            if other["plan_status"] == "CLOSED":
                continue
            other_model = lookups.model_for_recall(other)
            if other_model is not None and other_model["id"] == model["id"]:
                still_open = True
                break
        if not still_open:
            model["open_escalation_count"] = 0
            model["hazard_posture"] = "MONITORED"
            store.touch(model)

    return responses.object_response(recall)
