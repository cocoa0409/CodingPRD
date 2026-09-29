"""Grievances: the fork-join workflow, SLA verdict and escalation (PRD 3.8)."""
from flask import Blueprint

from core import (
    ApiError, Field, ROLE_COMPLIANCE_AUDITOR, ROLE_CONTRACT_ADMINISTRATOR,
    ROLE_GRIEVANCE_COORDINATOR, ROLE_REGISTERED_DIETITIAN, all_rows, authorize,
    base_row, body_json, filter_eq, insert, listing, now_logical, present,
    public, respond_object, touch, validate_fields,
)
from calc import apply_ledger, response_due_at
from ops import (
    apply_breach_escalation, apply_missed_meal_escalation, contract_of,
    need_diet_order, need_facility, need_grievance, need_inmate,
    need_service_record, not_terminal, require_state,
)

bp = Blueprint("grievance", __name__, url_prefix="/cfs")

CATEGORIES = ("RELIGIOUS_DIET_DENIAL", "DIET_NOT_HONORED", "PORTION_SIZE",
              "FOOD_TEMPERATURE", "FOREIGN_OBJECT")
ROUTES = ("INVESTIGATION", "DIET_REVIEW", "DUAL_TRACK")
BRANCHES = ("INVESTIGATION", "DIET_REVIEW")
REMEDIES = ("NO_ACTION", "MENU_CORRECTION", "MEAL_REFEED", "DIET_REINSTATEMENT")
GRIEVANCE_TERMINAL = ("RESPONDED", "ESCALATED", "CLOSED")
BRANCH_FLAG = {"INVESTIGATION": "investigation_complete",
               "DIET_REVIEW": "diet_review_complete"}
BRANCH_STATE = {"INVESTIGATION": ("UNDER_INVESTIGATION", "DUAL_TRACK"),
                "DIET_REVIEW": ("DIET_REVIEW", "DUAL_TRACK")}

READ_ROLES = (ROLE_GRIEVANCE_COORDINATOR, ROLE_REGISTERED_DIETITIAN,
              ROLE_CONTRACT_ADMINISTRATOR, ROLE_COMPLIANCE_AUDITOR)


@bp.route("/grievances", methods=["POST"])
def file_grievance():
    authorize(ROLE_GRIEVANCE_COORDINATOR)
    body = body_json()
    validate_fields(body, [
        Field("inmate_id", "string", required=True),
        Field("facility_id", "string", required=True),
        Field("category", "string", required=True, enum=CATEGORIES),
        Field("narrative", "string", required=True),
        Field("diet_order_id", "string"),
        Field("meal_service_record_id", "string"),
    ])
    inmate = need_inmate(body["inmate_id"])
    facility = need_facility(body["facility_id"])
    order = need_diet_order(body["diet_order_id"]) if present(body, "diet_order_id") else None
    record = need_service_record(body["meal_service_record_id"]) \
        if present(body, "meal_service_record_id") else None
    if inmate["facility_id"] != facility["id"]:
        raise ApiError("ERR_FACILITY_MISMATCH",
                       "The grievance facility must be the grievant's own facility.")
    if inmate["status"] != "IN_CUSTODY":
        raise ApiError("ERR_INMATE_NOT_IN_CUSTODY")
    filed_at = now_logical()
    row = base_row()
    row.update({
        "inmate_id": inmate["id"],
        "facility_id": facility["id"],
        "category": body["category"],
        "narrative": body["narrative"],
        "diet_order_id": order["id"] if order is not None else None,
        "meal_service_record_id": record["id"] if record is not None else None,
        "refeed_tray_count": 0,
        "responded_by_user_id": None,
        "filed_at": filed_at,
        "response_due_at": response_due_at(filed_at, body["category"]),
        "status": "FILED",
        "routed_branch": None,
        "investigation_complete": False,
        "diet_review_complete": False,
        "diet_remedy_required": False,
        "remedy": None,
        "response_at": None,
        "sla_breached": False,
    })
    insert("grievances", row)
    return respond_object(public(row), 201)


@bp.route("/grievances/<row_id>", methods=["GET"])
def read_grievance(row_id):
    authorize(*READ_ROLES)
    return respond_object(public(need_grievance(row_id)), 200)


@bp.route("/grievances", methods=["GET"])
def list_grievances():
    authorize(*READ_ROLES)
    rows = filter_eq(all_rows("grievances"), "inmate_id")
    rows = filter_eq(rows, "facility_id")
    rows = filter_eq(rows, "diet_order_id")
    rows = filter_eq(rows, "meal_service_record_id")
    rows = filter_eq(rows, "status")
    return listing(rows)


@bp.route("/grievances/<row_id>/route", methods=["POST"])
def route_grievance(row_id):
    authorize(ROLE_GRIEVANCE_COORDINATOR)
    body = body_json()
    validate_fields(body, [Field("route", "string", required=True, enum=ROUTES)])
    grievance = need_grievance(row_id)
    not_terminal(grievance, "status", GRIEVANCE_TERMINAL)
    require_state(grievance, "status", ("FILED",))
    route = body["route"]
    if route == "DIET_REVIEW" and not grievance.get("diet_order_id"):
        raise ApiError("ERR_INVALID_STATE",
                       "A diet review needs a diet_order_id to review.")
    if route == "DUAL_TRACK" and (not grievance.get("diet_order_id")
                                  or not grievance.get("meal_service_record_id")):
        raise ApiError("ERR_INVALID_STATE",
                       "A dual-track route needs both optional links.")
    if route == "INVESTIGATION":
        grievance["status"] = "UNDER_INVESTIGATION"
        grievance["routed_branch"] = "INVESTIGATION"
    elif route == "DIET_REVIEW":
        grievance["status"] = "DIET_REVIEW"
        grievance["routed_branch"] = "DIET_REVIEW"
    else:
        # The branch marker is BOTH while the status is DUAL_TRACK.
        grievance["status"] = "DUAL_TRACK"
        grievance["routed_branch"] = "BOTH"
    touch(grievance)
    return respond_object(public(grievance), 200)


@bp.route("/grievances/<row_id>/complete-branch", methods=["POST"])
def complete_branch(row_id):
    authorize(ROLE_GRIEVANCE_COORDINATOR, ROLE_REGISTERED_DIETITIAN)
    body = body_json()
    validate_fields(body, [
        Field("branch", "string", required=True, enum=BRANCHES),
        Field("finding", "string"),
    ])
    grievance = need_grievance(row_id)
    not_terminal(grievance, "status", GRIEVANCE_TERMINAL)
    branch = body["branch"]
    require_state(grievance, "status", BRANCH_STATE[branch])
    flag = BRANCH_FLAG[branch]
    if grievance[flag]:
        raise ApiError("ERR_INVALID_STATE", "That branch has already reported back.")

    grievance[flag] = True
    if branch == "DIET_REVIEW" and body.get("finding") == "KITCHEN_AT_FAULT":
        grievance["diet_remedy_required"] = True
    if grievance["status"] == "DUAL_TRACK":
        other = "diet_review_complete" if branch == "INVESTIGATION" else "investigation_complete"
        if grievance[other]:
            grievance["status"] = "READY_FOR_RESPONSE"
    else:
        grievance["status"] = "READY_FOR_RESPONSE"
    touch(grievance)
    return respond_object(public(grievance), 200)


@bp.route("/grievances/<row_id>/respond", methods=["POST"])
def respond_grievance(row_id):
    actor = authorize(ROLE_GRIEVANCE_COORDINATOR)
    body = body_json()
    validate_fields(body, [
        Field("remedy", "string", required=True, enum=REMEDIES),
        Field("refeed_tray_count", "integer"),
        Field("response_note", "string"),
    ])
    grievance = need_grievance(row_id)
    not_terminal(grievance, "status", GRIEVANCE_TERMINAL)
    if grievance["status"] != "READY_FOR_RESPONSE":
        raise ApiError("ERR_BRANCHES_INCOMPLETE")

    remedy = body["remedy"]
    record = None
    order = None
    if remedy == "NO_ACTION" and grievance["diet_remedy_required"]:
        raise ApiError("ERR_REMEDY_NOT_PERMITTED")
    if remedy == "MEAL_REFEED":
        record_id = grievance.get("meal_service_record_id")
        refeed = body.get("refeed_tray_count")
        if not record_id or refeed is None or int(refeed) < 1:
            raise ApiError("ERR_REFEED_TARGET_INVALID")
        record = need_service_record(record_id)
        if record["status"] != "CLOSED":
            raise ApiError("ERR_REFEED_TARGET_INVALID")
    if remedy == "DIET_REINSTATEMENT":
        order_id = grievance.get("diet_order_id")
        if not order_id:
            raise ApiError("ERR_REINSTATEMENT_TARGET_INVALID")
        order = need_diet_order(order_id)
        if order["status"] != "SUSPENDED":
            raise ApiError("ERR_REINSTATEMENT_TARGET_INVALID")

    response_at = now_logical()
    breached = response_at > grievance["response_due_at"]
    grievance["remedy"] = remedy
    if present(body, "refeed_tray_count"):
        grievance["refeed_tray_count"] = int(body["refeed_tray_count"])
    grievance["response_at"] = response_at
    grievance["responded_by_user_id"] = actor.user_id
    grievance["sla_breached"] = bool(breached)
    if breached:
        grievance["status"] = "ESCALATED"
    elif remedy == "NO_ACTION":
        grievance["status"] = "CLOSED"
    else:
        grievance["status"] = "RESPONDED"
    touch(grievance)

    facility = need_facility(grievance["facility_id"])
    contract = contract_of(facility)

    if remedy == "MEAL_REFEED" and record is not None:
        refeed = int(grievance["refeed_tray_count"])
        record["status"] = "DISPUTED"
        record["dispute_tray_count"] = refeed
        record["missed_meal_count"] = int(record["missed_meal_count"]) + refeed
        touch(record)
        record_facility = need_facility(record["facility_id"])
        record_contract = contract_of(record_facility)
        if record_contract is not None:
            record_contract["missed_meal_total"] = int(record_contract["missed_meal_total"]) + refeed
            apply_ledger(record_contract)
            touch(record_contract)
            apply_missed_meal_escalation(record_contract)

    if remedy == "DIET_REINSTATEMENT" and order is not None:
        order["status"] = "PENDING_VERIFICATION"
        order["reverification_count"] = int(order["reverification_count"]) + 1
        order["verified_by_user_id"] = None
        order["verified_at"] = None
        touch(order)

    if breached and contract is not None:
        contract["grievance_sla_breach_count"] = int(contract["grievance_sla_breach_count"]) + 1
        apply_ledger(contract)
        touch(contract)
        apply_breach_escalation(contract)

    return respond_object(public(grievance), 200)
