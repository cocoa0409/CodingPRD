"""Cases: open, assign/reassign, start-investigation, sar-decision, qa-review."""
from flask import Blueprint, request

import db
import response
from errors import ApiError
from middleware import ALL_ROLES, authn, authz, get_body, pagination_params
from services.core import LE_OPEN_STATUSES
from util import (CASE_DECISIONS, QA_OUTCOMES, base_entity, opt_str, req_enum,
                  req_int, req_str, serialize, sort_created, touch)

bp = Blueprint("cases", __name__)


def _get(store, rid, label):
    entity = store.get(rid)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} '{rid}' does not exist", 404)
    return entity


def _bump_analyst(analyst, delta):
    analyst["assigned_open_cases"] += delta
    touch(analyst)


@bp.route("/cases", methods=["POST"])
def create_case():
    body = get_body()
    customer_id = req_str(body, "customer_id")
    source_alert_id = opt_str(body, "source_alert_id")
    _, role = authn()
    authz(role, ["BSAAnalyst", "BSAManager"])
    customer = _get(db.customers, customer_id, "Customer")
    if source_alert_id is not None:
        _get(db.alerts, source_alert_id, "Alert")
    case = base_entity()
    case.update({
        "customer_id": customer["id"],
        "source_alert_id": source_alert_id,
        "assigned_analyst_id": None,
        "on_hold_inquiry_id": None,
        "status": "OPEN",
        "decision": "NONE",
        "decision_rationale": None,
        "decided_at": None,
        "initial_detection_at": None,
        "qa_reviewed_by": None,
        "closed_reason": None,
        "closed_at": None,
    })
    db.cases[case["id"]] = case
    return response.success(serialize(case), status=201)


@bp.route("/cases", methods=["GET"])
def list_cases():
    _, role = authn()
    authz(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = list(db.cases.values())
    for field in ("customer_id", "assigned_analyst_id", "source_alert_id",
                  "on_hold_inquiry_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [c for c in items if c.get(field) == value]
    items = sort_created(items)
    return response.paginated([serialize(c) for c in items], limit, offset)


@bp.route("/cases/<rid>", methods=["GET"])
def get_case(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    case = _get(db.cases, rid, "Case")
    return response.success(serialize(case), status=200)


@bp.route("/cases/<rid>/assign", methods=["POST"])
def assign_case(rid):
    body = get_body()
    analyst_id = req_str(body, "analyst_id")
    _, role = authn()
    authz(role, ["BSAManager"])
    case = _get(db.cases, rid, "Case")
    analyst = _get(db.analysts, analyst_id, "Analyst")
    if case["status"] not in {"OPEN", "ASSIGNED", "INVESTIGATING"}:
        raise ApiError("ERR_INVALID_STATE",
                       f"Case in status {case['status']} cannot be assigned", 409)
    previous_id = case["assigned_analyst_id"]
    if case["status"] in {"ASSIGNED", "INVESTIGATING"} and analyst_id == previous_id:
        raise ApiError("ERR_INVALID_STATE",
                       "Reassignment requires a different analyst_id", 409)
    if analyst["assigned_open_cases"] >= analyst["capacity_max_cases"]:
        raise ApiError("ERR_ANALYST_AT_CAPACITY",
                       "Analyst is already at capacity_max_cases open cases", 409)
    if previous_id is not None and case["status"] in {"ASSIGNED", "INVESTIGATING"}:
        previous = db.analysts.get(previous_id)
        if previous is not None:
            _bump_analyst(previous, -1)
    case["assigned_analyst_id"] = analyst_id
    case["status"] = "ASSIGNED"
    _bump_analyst(analyst, +1)
    touch(case)
    return response.success(serialize(case), status=200)


@bp.route("/cases/<rid>/start-investigation", methods=["POST"])
def start_investigation(rid):
    user_id, role = authn()
    authz(role, ["BSAAnalyst"])
    case = _get(db.cases, rid, "Case")
    if case["assigned_analyst_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Only the assigned analyst may start the investigation", 403)
    if case["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Case in status {case['status']} cannot start investigation", 409)
    case["status"] = "INVESTIGATING"
    touch(case)
    return response.success(serialize(case), status=200)


@bp.route("/cases/<rid>/sar-decision", methods=["POST"])
def sar_decision(rid):
    body = get_body()
    decision = req_enum(body, "decision", CASE_DECISIONS)
    rationale = req_str(body, "decision_rationale", allow_empty=True)
    expected_version = req_int(body, "expected_case_version")
    user_id, role = authn()
    authz(role, ["BSAAnalyst"])
    case = _get(db.cases, rid, "Case")
    if case["assigned_analyst_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Only the assigned analyst may record the SAR decision", 403)
    if case["status"] != "INVESTIGATING":
        raise ApiError("ERR_INVALID_STATE",
                       f"Case in status {case['status']} cannot take a SAR decision", 409)
    if expected_version != case["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_case_version does not match the case's current "
                       "version", 412)
    linked = [a for a in db.alerts.values()
              if a.get("case_id") == case["id"] and a["status"] == "LINKED"]
    initial_detection = (min(a["created_at"] for a in linked)
                         if linked else case["created_at"])
    case["decision"] = decision
    case["decision_rationale"] = rationale
    case["decided_at"] = db.now()
    case["initial_detection_at"] = initial_detection
    case["status"] = "SAR_IN_PROGRESS" if decision == "SAR_REQUIRED" else "PENDING_QA"
    touch(case)
    return response.success(serialize(case), status=200)


@bp.route("/cases/<rid>/qa-review", methods=["POST"])
def case_qa_review(rid):
    body = get_body()
    outcome = req_enum(body, "outcome", QA_OUTCOMES)
    notes = opt_str(body, "notes")
    user_id, role = authn()
    authz(role, ["QAReviewer"])
    case = _get(db.cases, rid, "Case")
    if case["assigned_analyst_id"] is not None and user_id == case["assigned_analyst_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Case QA reviewer must differ from the assigned analyst", 403)
    if case["status"] != "PENDING_QA":
        raise ApiError("ERR_INVALID_STATE",
                       f"Case in status {case['status']} is not pending QA", 409)
    if outcome == "PASS":
        open_inquiry = any(
            i.get("case_id") == case["id"] and i["status"] in LE_OPEN_STATUSES
            for i in db.inquiries.values())
        if open_inquiry:
            raise ApiError("ERR_LE_INQUIRY_OPEN",
                           "An open law-enforcement inquiry blocks case closure", 409)
        case["status"] = "CLOSED"
        case["closed_reason"] = ("NO_SAR_CONFIRMED" if case["decision"] == "NO_SAR"
                                 else "SAR_FILED")
        case["closed_at"] = db.now()
        assignee = db.analysts.get(case["assigned_analyst_id"])
        if assignee is not None:
            _bump_analyst(assignee, -1)
    else:
        case["status"] = "INVESTIGATING"
    case["qa_reviewed_by"] = user_id
    touch(case)
    return response.success(serialize(case), status=200)
