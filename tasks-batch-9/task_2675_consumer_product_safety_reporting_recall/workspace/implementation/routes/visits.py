"""Shelf-removal audit visits (PRD 3.6)."""

from flask import Blueprint

import auth
import lookups
import responses
import shapes
import store
from errors import raise_error

bp = Blueprint("visits", __name__)

VISIT_STATUSES = ("SCHEDULED", "COMPLETED")
VERDICTS = ("PENDING", "PASS", "FAIL")
COMPLETION_VERDICTS = ("PASS", "FAIL")
TRAVEL_BUFFER_HOURS = 24

ROLES = ("ProgramAdmin", "ComplianceOfficer", "SafetyDirector", "FieldAuditor")


@bp.route("/audit-visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    auth.authorize(*ROLES)
    return responses.object_response(lookups.find("audit_visit", visit_id))


@bp.route("/audit-visits", methods=["GET"])
def list_visits():
    auth.authorize(*ROLES)
    limit, offset = shapes.pagination()
    notification_id = shapes.q_str("retailer_notification_id")
    status = shapes.q_enum("status", VISIT_STATUSES)
    verdict = shapes.q_enum("verdict", VERDICTS)

    def keep(row):
        if (notification_id is not None
                and row["retailer_notification_id"] != notification_id):
            return False
        if status is not None and row["status"] != status:
            return False
        if verdict is not None and row["verdict"] != verdict:
            return False
        return True

    return responses.list_response(
        store.ordered(store.audit_visits, keep), limit, offset)


@bp.route("/audit-visits", methods=["POST"])
def create_visit():
    auth.authorize("FieldAuditor", "SafetyDirector")
    data = shapes.body()
    notification_id = shapes._req(data, "retailer_notification_id")
    window_start = shapes.req_ts(data, "window_start")
    window_end = shapes.req_ts(data, "window_end")
    if not window_start < window_end:
        shapes.bad()

    notification = lookups.find("retailer_notification", notification_id)
    if notification["status"] == "VERIFIED":
        raise_error("ERR_NOTIFICATION_STATE_INVALID")

    retailer = lookups.maybe("retailer", notification["retailer_id"])
    posture = retailer["compliance_posture"] if retailer is not None else None
    if posture not in ("STOP_SALE_ACTIVE", "DELINQUENT"):
        raise_error("ERR_NO_ACTIVE_STOP_SALE")

    # Windows are deconflicted per retailer across all recalls, each side
    # widened by a 24 hour travel buffer.
    buffer = store.hours(TRAVEL_BUFFER_HOURS)
    for other in store.ordered(store.audit_visits):
        if other["status"] != "SCHEDULED":
            continue
        sibling = lookups.maybe("retailer_notification",
                                other["retailer_notification_id"])
        if sibling is None or sibling["retailer_id"] != notification["retailer_id"]:
            continue
        if (window_start < other["window_end"] + buffer
                and other["window_start"] < window_end + buffer):
            raise_error("ERR_AUDIT_WINDOW_CONFLICT")

    row = store.new_row(
        retailer_notification_id=notification_id,
        window_start=window_start,
        window_end=window_end,
        status="SCHEDULED",
        verdict="PENDING",
        shelf_units_found=None,
        completed_at=None,
    )
    store.audit_visits[row["id"]] = row
    return responses.created(row)


@bp.route("/audit-visits/<visit_id>/complete", methods=["POST"])
def complete_visit(visit_id):
    auth.authorize("FieldAuditor")
    visit = lookups.find("audit_visit", visit_id)
    data = shapes.body()
    verdict = shapes.req_enum(data, "verdict", COMPLETION_VERDICTS)
    shelf_units_found = shapes.req_int(data, "shelf_units_found", minimum=0)

    if visit["status"] != "SCHEDULED":
        raise_error("ERR_VISIT_STATE_INVALID")

    if verdict == "PASS" and shelf_units_found != 0:
        raise_error("ERR_SHELF_UNITS_PRESENT")
    if verdict == "FAIL" and shelf_units_found <= 0:
        raise_error("ERR_SHELF_UNITS_PRESENT")

    visit["status"] = "COMPLETED"
    visit["verdict"] = verdict
    visit["shelf_units_found"] = shelf_units_found
    visit["completed_at"] = store.now_logical()
    store.touch(visit)
    return responses.object_response(visit)
