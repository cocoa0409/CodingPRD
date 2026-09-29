"""Defective returns, failure analysis and the credit decision (PRD 3.9)."""
from flask import Blueprint, g

import db
from db import base_row, setf
from errors import ApiError
from middleware import COMPLIANCE_OFFICER, FAILURE_ANALYSIS_ENGINEER, PROGRAM_ADMIN, \
    REPAIR_PROVIDER_TECH, SELF_REPAIR_CUSTOMER, check_order_ownership, \
    check_provider_scope, endpoint
from response import collection, created, ok
from routes.helpers import filter_eq, get_case, get_line
from serializers import case_json
from services.orders import NO_CREDIT_ROOT_CAUSES, analysis_final, goodwill_provisional
from validation import F, int_range, read_body

bp = Blueprint("returns", __name__)

FAILURE_CODES = ("NO_POWER", "INTERMITTENT", "PHYSICAL_DAMAGE", "CALIBRATION_DRIFT",
                 "AUTHENTICATION_FAILURE")
ROOT_CAUSES = ("MANUFACTURING_DEFECT", "PROVIDER_INSTALL_ERROR", "CUSTOMER_MISUSE",
               "PART_AUTHENTICATION_FAILURE", "UNDETERMINED")
INCOMPLETE_CALIBRATION = ("CALIBRATION_REQUIRED", "CALIBRATION_IN_PROGRESS",
                          "CALIBRATION_FAILED", "CALIBRATION_ESCALATED")

READ_ROLES = [PROGRAM_ADMIN, FAILURE_ANALYSIS_ENGINEER, SELF_REPAIR_CUSTOMER,
              REPAIR_PROVIDER_TECH, COMPLIANCE_OFFICER]


def _line_of(case):
    return db.db.lines.get(case["order_line_id"])


@bp.post("/defective-returns")
@endpoint([SELF_REPAIR_CUSTOMER, REPAIR_PROVIDER_TECH])
def create_case():
    body = read_body([
        F("order_line_id", "string", required=True),
        F("reported_failure_code", "enum", required=True, enum=FAILURE_CODES),
        F("quantity", "int", required=True),
    ])
    int_range(body["quantity"], "quantity", 1, None)

    line = get_line(body["order_line_id"])
    order = db.db.orders.get(line["order_id"])
    if order is not None:
        check_order_ownership(order)
        check_provider_scope(order.get("provider_id"))

    claimed = body["quantity"]
    for existing in db.db.cases.all():
        if existing["order_line_id"] == line["id"] and existing["status"] != "REJECTED":
            claimed += existing["quantity"]
    if claimed > line["quantity"]:
        raise ApiError("ERR_RETURN_QUANTITY_EXCEEDS_LINE")

    row = base_row()
    row.update({
        "order_line_id": line["id"],
        "part_id": line["part_id"],
        "quantity": body["quantity"],
        "reported_failure_code": body["reported_failure_code"],
        "status": "REQUESTED",
        "root_cause_code": None,
        "defect_confirmed": None,
        "analyzed_by_user_id": None,
        "decided_by_user_id": None,
        "provisional_credit_cents": 0,
        "final_credit_cents": None,
        "received_at": None,
    })
    db.db.cases.add(row)
    return created(case_json(row))


@bp.get("/defective-returns/<case_id>")
@endpoint(READ_ROLES)
def read_case(case_id):
    return ok(case_json(get_case(case_id)))


@bp.get("/defective-returns")
@endpoint(READ_ROLES)
def list_cases():
    rows = db.db.cases.all()
    for field in ("order_line_id", "part_id", "status", "root_cause_code",
                  "reported_failure_code"):
        rows = filter_eq(rows, field)
    return collection(rows, case_json)


@bp.post("/defective-returns/<case_id>/receive")
@endpoint([PROGRAM_ADMIN])
def receive_case(case_id):
    body = read_body([F("received_at", "datetime")])
    case = get_case(case_id)

    if case["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    setf(case, "received_at",
         body["received_at"] if body["received_at"] is not None else db.now())
    line = _line_of(case)
    if line is not None:
        setf(case, "provisional_credit_cents", goodwill_provisional(case, line))
    setf(case, "status", "RECEIVED")
    return ok(case_json(case))


@bp.post("/defective-returns/<case_id>/analysis")
@endpoint([FAILURE_ANALYSIS_ENGINEER])
def analyse_case(case_id):
    body = read_body([
        F("root_cause_code", "enum", required=True, enum=ROOT_CAUSES),
        F("defect_confirmed", "bool", required=True),
        F("analysis_note", "string"),
    ])
    case = get_case(case_id)

    if case["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    setf(case, "root_cause_code", body["root_cause_code"])
    setf(case, "defect_confirmed", body["defect_confirmed"])
    setf(case, "analyzed_by_user_id", g.user_id)
    setf(case, "status", "ANALYSIS_COMPLETE")
    return ok(case_json(case))


@bp.post("/defective-returns/<case_id>/credit-decision")
@endpoint([PROGRAM_ADMIN, FAILURE_ANALYSIS_ENGINEER])
def decide_case(case_id):
    body = read_body([
        F("decision", "enum", required=True, enum=("ISSUE_CREDIT", "REJECT")),
        F("decision_note", "string"),
    ])
    case = get_case(case_id)
    line = _line_of(case)

    # band 5
    if case.get("analyzed_by_user_id") is not None \
            and case["analyzed_by_user_id"] == g.user_id:
        raise ApiError("ERR_SELF_DECISION_FORBIDDEN")

    # band 6
    if body["decision"] == "ISSUE_CREDIT" and line is not None:
        if line["calibration_status"] in INCOMPLETE_CALIBRATION \
                or line["authentication_status"] == "PENDING_AUTHENTICATION":
            raise ApiError("ERR_CALIBRATION_INCOMPLETE")

    # band 7
    if case["status"] != "ANALYSIS_COMPLETE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if body["decision"] == "ISSUE_CREDIT" \
            and case.get("root_cause_code") in NO_CREDIT_ROOT_CAUSES:
        raise ApiError("ERR_CREDIT_NOT_ALLOWED_FOR_ROOT_CAUSE")

    setf(case, "decided_by_user_id", g.user_id)
    if body["decision"] == "ISSUE_CREDIT":
        setf(case, "final_credit_cents",
             analysis_final(case, line) if line is not None else 0)
        setf(case, "status", "CREDIT_ISSUED")
    else:
        setf(case, "final_credit_cents", 0)
        setf(case, "status", "REJECTED")
    return ok(case_json(case))
