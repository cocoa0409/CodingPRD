"""Safety incidents: intake, triage, adjudication and the safety score."""
from flask import Blueprint

import calc
import services
import validation as v
from auth import (
    COMPLIANCE_REVIEWER,
    DINER,
    FINANCE_OPERATOR,
    PLATFORM_ADMIN,
    SAFETY_OFFICER,
    acting_user,
    guard,
)
from core import ApiError, created, db, new_row, ok, public, touch
from listing import list_rows

bp = Blueprint("safety", __name__)


def find_incident(incident_id):
    incident = db.incidents.get(incident_id)
    if incident is None:
        raise ApiError("ERR_INCIDENT_NOT_FOUND")
    return incident


@bp.route("/safety-incidents", methods=["POST"])
@guard([DINER, SAFETY_OFFICER, PLATFORM_ADMIN])
def create_incident():
    body = v.body()
    cook_id = v.s_id(body, "cook_id")
    subject_type = v.s_enum(body, "subject_type", v.SUBJECT_TYPES)
    category = v.s_enum(body, "category", v.INCIDENT_CATEGORIES)
    severity = v.s_enum(body, "severity", v.SEVERITIES)
    description = v.s_str(body, "description", 1, 2000)
    occurred_raw, _ = v.s_dt(body, "occurred_at")
    order_id = v.s_id(body, "order_id", required=False)
    menu_item_id = v.s_id(body, "menu_item_id", required=False)

    cook = db.cooks.get(cook_id)
    if cook is None:
        raise ApiError("ERR_COOK_NOT_FOUND")
    order = None
    if order_id is not None:
        order = db.orders.get(order_id)
        if order is None:
            raise ApiError("ERR_ORDER_NOT_FOUND")
    item = None
    if menu_item_id is not None:
        item = db.menu_items.get(menu_item_id)
        if item is None:
            raise ApiError("ERR_MENU_ITEM_NOT_FOUND")

    # Priority 43 - the polymorphic subject selector is strict.
    if subject_type == "COOK":
        if order_id is not None or menu_item_id is not None:
            raise ApiError("ERR_INCIDENT_SUBJECT_MISMATCH", "a COOK subject takes no identifiers")
    elif subject_type == "MENU_ITEM":
        if menu_item_id is None or order_id is not None or item["cook_id"] != cook_id:
            raise ApiError(
                "ERR_INCIDENT_SUBJECT_MISMATCH", "a MENU_ITEM subject requires that cook's dish"
            )
    else:
        if order_id is None or menu_item_id is not None or order["cook_id"] != cook_id:
            raise ApiError(
                "ERR_INCIDENT_SUBJECT_MISMATCH", "an ORDER subject requires that cook's order"
            )

    row = new_row(
        db.incidents,
        {
            "cook_id": cook_id,
            "order_id": order_id,
            "menu_item_id": menu_item_id,
            "subject_type": subject_type,
            "category": category,
            "severity": severity,
            "severity_points": calc.SEVERITY_POINTS[severity],
            "description": description,
            "occurred_at": occurred_raw,
            "status": "INTAKE",
            "reported_by_user_id": acting_user(),
            "triaged_by_user_id": None,
            "triaged_at": None,
            "adjudicated_by_user_id": None,
            "adjudicated_at": None,
            "resolution_note": None,
        },
    )
    return created(public(row))


@bp.route("/safety-incidents/<incident_id>", methods=["GET"])
@guard([SAFETY_OFFICER, COMPLIANCE_REVIEWER, PLATFORM_ADMIN])
def get_incident(incident_id):
    return ok(public(find_incident(incident_id)))


@bp.route("/safety-incidents", methods=["GET"])
@guard([SAFETY_OFFICER, COMPLIANCE_REVIEWER, FINANCE_OPERATOR, PLATFORM_ADMIN])
def list_incidents():
    return list_rows(
        list(db.incidents.values()),
        ["cook_id", "order_id", "menu_item_id", "status", "severity"],
    )


@bp.route("/safety-incidents/<incident_id>/triage", methods=["POST"])
@guard([SAFETY_OFFICER, PLATFORM_ADMIN])
def triage_incident(incident_id):
    body = v.body()
    decision = v.s_enum(body, "decision", ["ACCEPT", "DISMISS"])
    override = v.s_enum(body, "severity_override", v.SEVERITIES, required=False)

    incident = find_incident(incident_id)
    if incident["status"] != "INTAKE":
        raise ApiError("ERR_INVALID_INCIDENT_TRANSITION", "triage is legal only from INTAKE")

    incident["triaged_by_user_id"] = acting_user()
    incident["triaged_at"] = db.now_iso()
    if decision == "ACCEPT":
        if override is not None:
            incident["severity"] = override
        incident["severity_points"] = calc.SEVERITY_POINTS[incident["severity"]]
        incident["status"] = "TRIAGED"
    else:
        incident["severity_points"] = 0
        incident["status"] = "DISMISSED"
    touch(incident)
    return ok(public(incident))


@bp.route("/safety-incidents/<incident_id>/adjudicate", methods=["POST"])
@guard([SAFETY_OFFICER, PLATFORM_ADMIN])
def adjudicate_incident(incident_id):
    body = v.body()
    decision = v.s_enum(body, "decision", ["SUBSTANTIATE", "DISMISS"])
    note = v.s_str(body, "resolution_note", 0, 4000, required=False)

    incident = find_incident(incident_id)
    if incident["status"] != "TRIAGED":
        raise ApiError("ERR_INCIDENT_NOT_TRIAGED", "the incident is not TRIAGED")
    if acting_user() is not None and acting_user() == incident["triaged_by_user_id"]:
        raise ApiError("ERR_SOD_SAME_OFFICER", "the triaging officer may not adjudicate")

    incident["adjudicated_by_user_id"] = acting_user()
    incident["adjudicated_at"] = db.now_iso()
    incident["resolution_note"] = note
    cook = db.cooks[incident["cook_id"]]
    if decision == "SUBSTANTIATE":
        incident["status"] = "SUBSTANTIATED"
        touch(incident)
        services.apply_safety_score(cook, allow_standing_moves=True)
    else:
        incident["status"] = "UNSUBSTANTIATED"
        incident["severity_points"] = 0
        touch(incident)
        services.apply_safety_score(cook, allow_standing_moves=False)
    return ok(public(incident))
