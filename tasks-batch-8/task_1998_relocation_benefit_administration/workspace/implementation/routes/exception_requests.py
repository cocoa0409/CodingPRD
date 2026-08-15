from flask import Blueprint, request

from db import DB
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_already_terminal,
    err_case_not_open, err_stale_version, err_appeal_limit,
)
from middleware import get_actor, require_role, check_employee_owns_case
from response import success_object, success_list
from serializers import serialize_exception
from util import (
    require_fields, require_enum, require_string, require_positive_int, get_pagination,
)
from services.ledger import touch_entity, touch_case

bp = Blueprint("exception_requests", __name__)

ALL_ROLES = ["MobilityCoordinator", "FinanceSpecialist", "ProgramManager", "Employee", "Vendor"]

COMPONENTS = {"HHG", "TEMP_HOUSING", "TRAVEL", "MISC", "LOSS_ON_SALE"}


def _get_or_404(id):
    x = DB.exception_requests.get(id)
    if x is None:
        raise err_not_found("ExceptionRequest not found")
    return x


@bp.route("/exception-requests", methods=["POST"])
def create_exception():
    actor = get_actor()
    require_role(actor, ["Employee", "MobilityCoordinator"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["case_id", "component", "requested_cap_increase_cents", "justification"])
    case_id = require_string(payload, "case_id")
    component = require_enum(payload, "component", COMPONENTS)
    increase = require_positive_int(payload, "requested_cap_increase_cents")
    justification = require_string(payload, "justification")
    with DB.lock:
        case = DB.cases.get(case_id)
        if case is None:
            raise err_not_found("Case not found")
        if actor.role == "Employee":
            check_employee_owns_case(actor, case)
        if case["status"] != "IN_PROGRESS":
            raise err_case_not_open("Case is not IN_PROGRESS")
        now = DB.now()
        x = {
            "id": DB.new_id(),
            "case_id": case_id,
            "component": component,
            "requested_cap_increase_cents": increase,
            "justification": justification,
            "status": "PENDING",
            "decision_note": None,
            "appeal_count": 0,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": DB.next_seq(),
        }
        DB.exception_requests[x["id"]] = x
        return success_object(serialize_exception(x), status=201)


@bp.route("/exception-requests/<id>", methods=["GET"])
def get_exception(id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    with DB.lock:
        x = _get_or_404(id)
        return success_object(serialize_exception(x))


@bp.route("/relocation-cases/<case_id>/exception-requests", methods=["GET"])
def list_case_exceptions(case_id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    limit, offset = get_pagination(request.args)
    status = request.args.get("status")
    with DB.lock:
        case = DB.cases.get(case_id)
        if case is None:
            raise err_not_found("Case not found")
        items = [x for x in DB.exception_requests.values() if x["case_id"] == case_id]
        if status is not None:
            items = [x for x in items if x["status"] == status]
        items.sort(key=lambda x: (x["created_at"], x.get("_seq", 0)))
        total_count = len(items)
        page = items[offset:offset + limit]
        return success_list([serialize_exception(x) for x in page], limit, offset, total_count)


@bp.route("/exception-requests/<id>/approve", methods=["POST"])
def approve_exception(id):
    actor = get_actor()
    require_role(actor, ["ProgramManager"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["expected_case_version"])
    expected_case_version = payload.get("expected_case_version")
    if isinstance(expected_case_version, bool) or not isinstance(expected_case_version, int):
        raise err_invalid_request("expected_case_version must be an integer")
    decision_note = payload.get("decision_note")
    if decision_note is not None and not isinstance(decision_note, str):
        raise err_invalid_request("decision_note must be a string")
    with DB.lock:
        x = _get_or_404(id)
        if x["status"] == "APPROVED":
            raise err_already_terminal("Exception request already APPROVED")
        if x["status"] != "PENDING":
            raise err_invalid_state("Exception request is not PENDING")
        case = DB.cases.get(x["case_id"])
        if case is None:
            raise err_not_found("Case not found")
        if expected_case_version != case["version"]:
            raise err_stale_version("expected_case_version does not match current case version")
        if case["status"] != "IN_PROGRESS":
            raise err_case_not_open("Case is not IN_PROGRESS")
        x["status"] = "APPROVED"
        if decision_note is not None:
            x["decision_note"] = decision_note
        touch_entity(x)
        # approval mutates the parent case's effective cap landscape; bump case version
        touch_case(case)
        return success_object(serialize_exception(x))


@bp.route("/exception-requests/<id>/reject", methods=["POST"])
def reject_exception(id):
    actor = get_actor()
    require_role(actor, ["ProgramManager"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["decision_note"])
    decision_note = require_string(payload, "decision_note")
    with DB.lock:
        x = _get_or_404(id)
        if x["status"] == "APPROVED":
            raise err_already_terminal("Exception request already APPROVED")
        if x["status"] != "PENDING":
            raise err_invalid_state("Exception request is not PENDING")
        x["status"] = "REJECTED"
        x["decision_note"] = decision_note
        touch_entity(x)
        return success_object(serialize_exception(x))


@bp.route("/exception-requests/<id>/appeal", methods=["POST"])
def appeal_exception(id):
    actor = get_actor()
    require_role(actor, ["Employee", "MobilityCoordinator"])
    with DB.lock:
        x = _get_or_404(id)
        if x["status"] == "APPROVED":
            raise err_already_terminal("Exception request already APPROVED")
        if x["status"] != "REJECTED":
            raise err_invalid_state("Only REJECTED requests may be appealed")
        if actor.role == "Employee":
            case = DB.cases.get(x["case_id"])
            check_employee_owns_case(actor, case)
        if x.get("appeal_count", 0) >= 1:
            raise err_appeal_limit("Appeal limit reached")
        x["appeal_count"] = x.get("appeal_count", 0) + 1
        x["decision_note"] = None
        x["status"] = "PENDING"
        touch_entity(x)
        return success_object(serialize_exception(x))
