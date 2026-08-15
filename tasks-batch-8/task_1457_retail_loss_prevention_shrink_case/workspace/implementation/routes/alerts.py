"""Alert endpoints: list/get/dismiss/convert (PRD §3.2)."""

from flask import Blueprint, request

from db import db
from middleware import get_auth, require_role, ALL_ROLES
from response import success_object, success_list, parse_pagination
from services.validate import body, req_string, opt_string, req_enum, get_or_404
from services.entities import make_case, pub, touch
from services.calculations import recompute_case_total_loss, recompute_case_priority
from errors import (
    err400, err403, err409, err404, ApiError,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION, ERR_STORE_CLOSED,
    ERR_SUBJECT_MISMATCH, ERR_EMPLOYEE_NOT_ACTIVE, ERR_FORBIDDEN_FOR_ROLE,
)

bp = Blueprint("alerts", __name__)


@bp.route("/alerts", methods=["GET"])
def list_alerts():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    store_id = _q("store_id")
    employee_id = _q("employee_id")
    case_id = _q("case_id")
    status = _q("status")
    subject_type = _q("subject_type")
    min_score = _q("min_score")
    items = sorted(db.alerts.values(), key=lambda a: (a["created_at"], a["id"]))
    if store_id is not None:
        items = [a for a in items if a["store_id"] == store_id]
    if employee_id is not None:
        items = [a for a in items if a["employee_id"] == employee_id]
    if case_id is not None:
        items = [a for a in items if a.get("case_id") == case_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if subject_type is not None:
        items = [a for a in items if a["subject_type"] == subject_type]
    if min_score is not None:
        try:
            ms = float(min_score)
        except ValueError:
            raise err400(ERR_INVALID_REQUEST, "min_score must be a number")
        items = [a for a in items if a["score"] >= ms]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([pub(a) for a in page], limit, offset, total)


@bp.route("/alerts/<alert_id>", methods=["GET"])
def get_alert(alert_id):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    alert = get_or_404(db.alerts, alert_id, "alert")
    return success_object(pub(alert))


@bp.route("/alerts/<alert_id>/dismiss", methods=["POST"])
def dismiss_alert(alert_id):
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst", "LPManager"})
    data = body()
    reason = req_string(data, "reason")
    alert = get_or_404(db.alerts, alert_id, "alert")
    if alert["status"] == "OPEN":
        pass  # LPAnalyst or LPManager
    elif alert["status"] == "ESCALATED":
        if role != "LPManager":
            raise ApiError(ERR_FORBIDDEN_FOR_ROLE,
                           "Dismissing an ESCALATED alert requires LPManager", 403)
    else:
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Alert must be OPEN or ESCALATED to dismiss")
    alert["status"] = "DISMISSED"
    alert["dismiss_reason"] = reason
    for eid in alert["_member_event_ids"]:
        ev = db.exception_events[eid]
        ev["status"] = "UNAGGREGATED"
        touch(ev)
    touch(alert)
    return success_object(pub(alert))


@bp.route("/alerts/<alert_id>/convert", methods=["POST"])
def convert_alert(alert_id):
    user_id, role = get_auth()
    require_role(role, {"LPAnalyst"})
    data = body()
    subject_type = req_enum(data, "subject_type",
                            ["EMPLOYEE", "EXTERNAL", "UNKNOWN"])
    employee_id = opt_string(data, "employee_id")
    additional_alert_ids = data.get("additional_alert_ids")
    if additional_alert_ids is None:
        additional_alert_ids = []
    if not isinstance(additional_alert_ids, list) or any(
            not isinstance(x, str) for x in additional_alert_ids):
        raise err400(ERR_INVALID_REQUEST,
                     "additional_alert_ids must be a list of strings")

    # path id first, then body FKs in declared input order
    alert = get_or_404(db.alerts, alert_id, "alert")
    if employee_id is not None:
        get_or_404(db.employees, employee_id, "employee")
    extra_alerts = []
    for aid in additional_alert_ids:
        extra_alerts.append(get_or_404(db.alerts, aid, "alert"))

    # state gates on the primary alert
    if alert["status"] not in ("OPEN", "ESCALATED"):
        raise err409(ERR_INVALID_STATE_TRANSITION,
                     "Alert must be OPEN or ESCALATED to convert")
    store = db.stores.get(alert["store_id"])
    if store is None or store["status"] != "ACTIVE":
        raise err409(ERR_STORE_CLOSED, "Store is CLOSED")

    # subject consistency
    if subject_type == "EMPLOYEE":
        if alert["employee_id"] is None or employee_id != alert["employee_id"]:
            raise err409(ERR_SUBJECT_MISMATCH,
                         "subject_type=EMPLOYEE requires employee_id equal to the "
                         "alert's employee_id")
        emp = db.employees[employee_id]
        if emp["status"] == "TERMINATED":
            raise err409(ERR_EMPLOYEE_NOT_ACTIVE, "Employee is TERMINATED")
    else:
        if employee_id is not None:
            raise err409(ERR_SUBJECT_MISMATCH,
                         "EXTERNAL/UNKNOWN subject types require null employee_id")

    # additional alerts: OPEN|ESCALATED and same store
    for a in extra_alerts:
        if a["status"] not in ("OPEN", "ESCALATED"):
            raise err409(ERR_INVALID_STATE_TRANSITION,
                         "Additional alerts must be OPEN or ESCALATED")
        if a["store_id"] != alert["store_id"]:
            raise err409(ERR_INVALID_STATE_TRANSITION,
                         "Additional alerts must be of the same store")

    escalated_source = (alert["status"] == "ESCALATED"
                        or any(a["status"] == "ESCALATED" for a in extra_alerts))

    case = make_case(store, "ALERT", subject_type,
                     employee_id if subject_type == "EMPLOYEE" else None,
                     user_id, manual_loss_cents=0)
    db.cases[case["id"]] = case

    alert["status"] = "CONVERTED"
    alert["case_id"] = case["id"]
    touch(alert)
    for a in extra_alerts:
        a["status"] = "CONVERTED"
        a["case_id"] = case["id"]
        touch(a)

    recompute_case_total_loss(case)
    case["priority"] = "HIGH" if escalated_source else "STANDARD"
    touch(case)
    return success_object(pub(case), status=201)


def _q(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None
