from datetime import timedelta

from flask import Blueprint, request

from db import DB
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_already_terminal,
    err_forbidden, err_case_not_open, err_vendor_suspended, err_survey_conflict,
    err_stale_version, err_cap_exceeded,
)
from middleware import get_actor, require_role, check_vendor_owns_assignment, check_employee_owns_case
from response import success_object, success_list
from serializers import serialize_assignment
from util import (
    require_fields, require_string, require_positive_int, parse_datetime_field,
    get_pagination,
)
from services.caps import remaining_headroom
from services.ledger import touch_entity, commit, pay
from services.vendor_perf import recompute_vendor

bp = Blueprint("move_assignments", __name__)

ALL_ROLES = ["MobilityCoordinator", "FinanceSpecialist", "ProgramManager", "Employee", "Vendor"]

TERMINAL = {"PAID", "CANCELLED"}


def _get_assignment_or_404(id):
    a = DB.move_assignments.get(id)
    if a is None:
        raise err_not_found("MoveAssignment not found")
    return a


@bp.route("/move-assignments", methods=["POST"])
def create_assignment():
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["case_id", "vendor_id"])
    case_id = require_string(payload, "case_id")
    vendor_id = require_string(payload, "vendor_id")
    with DB.lock:
        case = DB.cases.get(case_id)
        if case is None:
            raise err_not_found("Case not found")
        vendor = DB.vendors.get(vendor_id)
        if vendor is None:
            raise err_not_found("Vendor not found")
        if case["status"] != "IN_PROGRESS":
            raise err_case_not_open("Case is not IN_PROGRESS")
        if vendor["status"] != "ACTIVE":
            raise err_vendor_suspended("Vendor is SUSPENDED")
        now = DB.now()
        a = {
            "id": DB.new_id(),
            "case_id": case_id,
            "vendor_id": vendor_id,
            "survey_at": None,
            "estimated_cents": None,
            "final_invoice_cents": None,
            "status": "REQUESTED",
            "rating": None,
            "rated_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": DB.next_seq(),
        }
        DB.move_assignments[a["id"]] = a
        return success_object(serialize_assignment(a), status=201)


@bp.route("/move-assignments", methods=["GET"])
def list_assignments():
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    limit, offset = get_pagination(request.args)
    case_id = request.args.get("case_id")
    vendor_id = request.args.get("vendor_id")
    status = request.args.get("status")
    with DB.lock:
        items = list(DB.move_assignments.values())
        if case_id is not None:
            items = [a for a in items if a["case_id"] == case_id]
        if vendor_id is not None:
            items = [a for a in items if a["vendor_id"] == vendor_id]
        if status is not None:
            items = [a for a in items if a["status"] == status]
        items.sort(key=lambda a: (a["created_at"], a.get("_seq", 0)))
        total_count = len(items)
        page = items[offset:offset + limit]
        return success_list([serialize_assignment(a) for a in page], limit, offset, total_count)


@bp.route("/move-assignments/<id>", methods=["GET"])
def get_assignment(id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    with DB.lock:
        a = _get_assignment_or_404(id)
        return success_object(serialize_assignment(a))


@bp.route("/move-assignments/<id>/schedule-survey", methods=["POST"])
def schedule_survey(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["survey_at"])
    survey_at = parse_datetime_field(payload, "survey_at", required=True)
    with DB.lock:
        a = _get_assignment_or_404(id)
        if a["status"] in TERMINAL:
            raise err_already_terminal("Assignment is terminal")
        if a["status"] != "REQUESTED":
            raise err_invalid_state("Assignment is not REQUESTED")
        case = DB.cases.get(a["case_id"])
        if case is None or case["status"] != "IN_PROGRESS":
            raise err_case_not_open("Case is not IN_PROGRESS")
        vendor = DB.vendors.get(a["vendor_id"])
        if vendor is None or vendor["status"] != "ACTIVE":
            raise err_vendor_suspended("Vendor is SUSPENDED")
        # 2h buffer: any other SURVEY_SCHEDULED assignment of same vendor within +/-2h
        window = timedelta(hours=2)
        for other in DB.move_assignments.values():
            if other["id"] == a["id"]:
                continue
            if other["vendor_id"] != a["vendor_id"]:
                continue
            if other["status"] != "SURVEY_SCHEDULED":
                continue
            other_at = other.get("survey_at")
            if other_at is None:
                continue
            if abs(other_at - survey_at) < window:
                raise err_survey_conflict("Vendor has another survey within 2 hours")
        a["survey_at"] = survey_at
        a["status"] = "SURVEY_SCHEDULED"
        touch_entity(a)
        return success_object(serialize_assignment(a))


@bp.route("/move-assignments/<id>/submit-estimate", methods=["POST"])
def submit_estimate(id):
    actor = get_actor()
    require_role(actor, ["Vendor"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["estimated_cents"])
    estimated = require_positive_int(payload, "estimated_cents")
    with DB.lock:
        a = _get_assignment_or_404(id)
        check_vendor_owns_assignment(actor, a)
        if a["status"] in TERMINAL:
            raise err_already_terminal("Assignment is terminal")
        if a["status"] != "SURVEY_SCHEDULED":
            raise err_invalid_state("Assignment is not SURVEY_SCHEDULED")
        a["estimated_cents"] = estimated
        a["status"] = "ESTIMATE_SUBMITTED"
        touch_entity(a)
        return success_object(serialize_assignment(a))


@bp.route("/move-assignments/<id>/approve-estimate", methods=["POST"])
def approve_estimate(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["expected_case_version"])
    expected_case_version = payload.get("expected_case_version")
    if isinstance(expected_case_version, bool) or not isinstance(expected_case_version, int):
        raise err_invalid_request("expected_case_version must be an integer")
    with DB.lock:
        a = _get_assignment_or_404(id)
        if a["status"] in TERMINAL:
            raise err_already_terminal("Assignment is terminal")
        if a["status"] != "ESTIMATE_SUBMITTED":
            raise err_invalid_state("Assignment is not ESTIMATE_SUBMITTED")
        case = DB.cases.get(a["case_id"])
        if case is None:
            raise err_not_found("Case not found")
        if expected_case_version != case["version"]:
            raise err_stale_version("expected_case_version does not match current case version")
        if case["status"] != "IN_PROGRESS":
            raise err_case_not_open("Case is not IN_PROGRESS")
        policy = DB.policies.get(case["policy_id"])
        headroom = remaining_headroom(case, policy, "HHG")
        if a["estimated_cents"] > headroom:
            raise err_cap_exceeded("Estimate exceeds remaining HHG headroom")
        a["status"] = "ESTIMATE_APPROVED"
        touch_entity(a)
        commit(case, a["estimated_cents"])
        return success_object(serialize_assignment(a))


@bp.route("/move-assignments/<id>/reject-estimate", methods=["POST"])
def reject_estimate(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    with DB.lock:
        a = _get_assignment_or_404(id)
        if a["status"] in TERMINAL:
            raise err_already_terminal("Assignment is terminal")
        if a["status"] != "ESTIMATE_SUBMITTED":
            raise err_invalid_state("Assignment is not ESTIMATE_SUBMITTED")
        a["survey_at"] = None
        a["estimated_cents"] = None
        a["status"] = "REQUESTED"
        touch_entity(a)
        return success_object(serialize_assignment(a))


@bp.route("/move-assignments/<id>/mark-delivered", methods=["POST"])
def mark_delivered(id):
    actor = get_actor()
    require_role(actor, ["Vendor"])
    with DB.lock:
        a = _get_assignment_or_404(id)
        check_vendor_owns_assignment(actor, a)
        if a["status"] in TERMINAL:
            raise err_already_terminal("Assignment is terminal")
        if a["status"] != "ESTIMATE_APPROVED":
            raise err_invalid_state("Assignment is not ESTIMATE_APPROVED")
        a["status"] = "DELIVERED"
        touch_entity(a)
        return success_object(serialize_assignment(a))


@bp.route("/move-assignments/<id>/submit-invoice", methods=["POST"])
def submit_invoice(id):
    actor = get_actor()
    require_role(actor, ["Vendor"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["final_invoice_cents"])
    final_invoice = require_positive_int(payload, "final_invoice_cents")
    with DB.lock:
        a = _get_assignment_or_404(id)
        check_vendor_owns_assignment(actor, a)
        if a["status"] in TERMINAL:
            raise err_already_terminal("Assignment is terminal")
        if a["status"] != "DELIVERED":
            raise err_invalid_state("Assignment is not DELIVERED")
        a["final_invoice_cents"] = final_invoice
        a["status"] = "INVOICED"
        touch_entity(a)
        return success_object(serialize_assignment(a))


@bp.route("/move-assignments/<id>/mark-paid", methods=["POST"])
def mark_paid(id):
    actor = get_actor()
    require_role(actor, ["FinanceSpecialist"])
    with DB.lock:
        a = _get_assignment_or_404(id)
        if a["status"] in TERMINAL:
            raise err_already_terminal("Assignment is terminal")
        if a["status"] != "INVOICED":
            raise err_invalid_state("Assignment is not INVOICED")
        case = DB.cases.get(a["case_id"])
        if case is None:
            raise err_not_found("Case not found")
        a["status"] = "PAID"
        touch_entity(a)
        # committed -= estimated_cents, paid += final_invoice_cents
        pay(case, a.get("estimated_cents") or 0, a.get("final_invoice_cents") or 0)
        vendor = DB.vendors.get(a["vendor_id"])
        if vendor is not None:
            vendor["completed_moves"] = vendor.get("completed_moves", 0) + 1
            vendor["updated_at"] = DB.now()
            vendor["version"] = vendor.get("version", 0) + 1
        return success_object(serialize_assignment(a))


@bp.route("/move-assignments/<id>/rate", methods=["POST"])
def rate_assignment(id):
    actor = get_actor()
    require_role(actor, ["Employee"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["rating"])
    rating = payload.get("rating")
    if isinstance(rating, bool) or not isinstance(rating, int) or rating < 1 or rating > 5:
        raise err_invalid_request("rating must be an integer 1..5")
    with DB.lock:
        a = _get_assignment_or_404(id)
        case = DB.cases.get(a["case_id"])
        check_employee_owns_case(actor, case)
        if a["status"] == "CANCELLED":
            raise err_already_terminal("Assignment is CANCELLED")
        if a["status"] != "PAID":
            raise err_invalid_state("Assignment is not PAID")
        if a.get("rating") is not None:
            raise err_invalid_state("Assignment already rated")
        a["rating"] = rating
        a["rated_at"] = DB.now()
        touch_entity(a)
        recompute_vendor(a["vendor_id"])
        return success_object(serialize_assignment(a))
