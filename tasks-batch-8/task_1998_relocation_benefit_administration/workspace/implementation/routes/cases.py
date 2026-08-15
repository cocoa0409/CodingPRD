from flask import Blueprint, request

from db import DB
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_already_terminal,
    err_policy_not_found, err_employee_not_active, err_employee_not_terminated,
)
from middleware import get_actor, require_role
from response import success_object, success_list
from serializers import serialize_case
from util import (
    require_fields, require_enum, require_string, parse_datetime_field, get_pagination,
)
from services.ledger import touch_entity, touch_case, release
from services.repayment import compute_months_remaining, compute_schedule
from services.vendor_perf import recompute_vendor

bp = Blueprint("cases", __name__)

MOVE_SCOPES = {"DOMESTIC", "INTERNATIONAL"}
ALL_ROLES = ["MobilityCoordinator", "FinanceSpecialist", "ProgramManager", "Employee", "Vendor"]

CASE_TERMINAL = {"CLOSED", "CLOSED_EARLY", "CANCELLED"}
ASSIGNMENT_NONTERMINAL = {
    "REQUESTED", "SURVEY_SCHEDULED", "ESTIMATE_SUBMITTED",
    "ESTIMATE_APPROVED", "DELIVERED", "INVOICED",
}
ASSIGNMENT_HELD = {"ESTIMATE_APPROVED", "DELIVERED", "INVOICED"}


def _resolve_policy(employee, move_scope):
    candidates = [
        p for p in DB.policies.values()
        if p["job_level"] == employee["job_level"]
        and p["move_scope"] == move_scope
        and p["home_ownership"] == employee["home_ownership"]
    ]
    if not candidates:
        return None
    # tie-break: created_at ASC, then insertion seq (deterministic)
    candidates.sort(key=lambda p: (p["created_at"], p.get("_seq", 0)))
    return candidates[0]


@bp.route("/relocation-cases", methods=["POST"])
def create_case():
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["employee_id", "move_scope", "origin_city", "destination_city", "expected_move_date"])
    employee_id = require_string(payload, "employee_id")
    move_scope = require_enum(payload, "move_scope", MOVE_SCOPES)
    origin_city = require_string(payload, "origin_city")
    destination_city = require_string(payload, "destination_city")
    expected_move_date = parse_datetime_field(payload, "expected_move_date", required=True)

    with DB.lock:
        employee = DB.employees.get(employee_id)
        if employee is None:
            raise err_not_found("Employee not found")
        if employee["employment_status"] != "ACTIVE":
            raise err_employee_not_active("Employee is not ACTIVE")
        policy = _resolve_policy(employee, move_scope)
        if policy is None:
            raise err_policy_not_found("No matching policy tier")
        now = DB.now()
        c = {
            "id": DB.new_id(),
            "employee_id": employee_id,
            "policy_id": policy["id"],
            "move_scope": move_scope,
            "origin_city": origin_city,
            "destination_city": destination_city,
            "expected_move_date": expected_move_date,
            "status": "DRAFT",
            "authorized_at": None,
            "total_committed_cents": 0,
            "total_paid_cents": 0,
            "total_released_cents": 0,
            "cumulative_taxable_paid_cents": 0,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": DB.next_seq(),
        }
        DB.cases[c["id"]] = c
        return success_object(serialize_case(c), status=201)


@bp.route("/relocation-cases", methods=["GET"])
def list_cases():
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    limit, offset = get_pagination(request.args)
    employee_id = request.args.get("employee_id")
    policy_id = request.args.get("policy_id")
    status = request.args.get("status")
    with DB.lock:
        items = list(DB.cases.values())
        if employee_id is not None:
            items = [c for c in items if c["employee_id"] == employee_id]
        if policy_id is not None:
            items = [c for c in items if c["policy_id"] == policy_id]
        if status is not None:
            items = [c for c in items if c["status"] == status]
        items.sort(key=lambda c: (c["created_at"], c.get("_seq", 0)))
        total_count = len(items)
        page = items[offset:offset + limit]
        return success_list([serialize_case(c) for c in page], limit, offset, total_count)


@bp.route("/relocation-cases/<id>", methods=["GET"])
def get_case(id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    with DB.lock:
        c = DB.cases.get(id)
        if c is None:
            raise err_not_found("Case not found")
        return success_object(serialize_case(c))


@bp.route("/relocation-cases/<id>/authorize", methods=["POST"])
def authorize_case(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    with DB.lock:
        c = DB.cases.get(id)
        if c is None:
            raise err_not_found("Case not found")
        if c["status"] in CASE_TERMINAL:
            raise err_already_terminal("Case is terminal")
        if c["status"] != "DRAFT":
            raise err_invalid_state("Case is not DRAFT")
        employee = DB.employees.get(c["employee_id"])
        if employee is None or employee["employment_status"] != "ACTIVE":
            raise err_employee_not_active("Employee is not ACTIVE")
        c["status"] = "AUTHORIZED"
        c["authorized_at"] = DB.now()
        touch_entity(c)
        return success_object(serialize_case(c))


@bp.route("/relocation-cases/<id>/start", methods=["POST"])
def start_case(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    with DB.lock:
        c = DB.cases.get(id)
        if c is None:
            raise err_not_found("Case not found")
        if c["status"] in CASE_TERMINAL:
            raise err_already_terminal("Case is terminal")
        if c["status"] != "AUTHORIZED":
            raise err_invalid_state("Case is not AUTHORIZED")
        c["status"] = "IN_PROGRESS"
        touch_entity(c)
        return success_object(serialize_case(c))


def _cascade_cancel_children(case):
    """Cancel every non-terminal MoveAssignment and HELD/CONFIRMED ServiceBooking.
    Releases committed funds where applicable. Bumps each child's version, and
    the case version once per release (child-mutation -> parent ledger mutation).
    """
    for a in list(DB.move_assignments.values()):
        if a["case_id"] != case["id"]:
            continue
        if a["status"] in ASSIGNMENT_NONTERMINAL:
            held = a.get("estimated_cents") or 0
            was_holding = a["status"] in ASSIGNMENT_HELD
            a["status"] = "CANCELLED"
            touch_entity(a)
            if was_holding and held > 0:
                release(case, held)
    for b in list(DB.service_bookings.values()):
        if b["case_id"] != case["id"]:
            continue
        if b["status"] in ("HELD", "CONFIRMED"):
            was_confirmed = b["status"] == "CONFIRMED"
            b["status"] = "CANCELLED"
            touch_entity(b)
            if was_confirmed:
                release(case, b.get("total_cents") or 0)


@bp.route("/relocation-cases/<id>/cancel", methods=["POST"])
def cancel_case(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    with DB.lock:
        c = DB.cases.get(id)
        if c is None:
            raise err_not_found("Case not found")
        if c["status"] in CASE_TERMINAL:
            raise err_already_terminal("Case is terminal")
        if c["status"] not in ("AUTHORIZED", "IN_PROGRESS"):
            raise err_invalid_state("Case cannot be cancelled from this state")
        if c["status"] == "IN_PROGRESS":
            _cascade_cancel_children(c)
        c["status"] = "CANCELLED"
        touch_entity(c)
        return success_object(serialize_case(c))


@bp.route("/relocation-cases/<id>/terminate-early", methods=["POST"])
def terminate_early_case(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    with DB.lock:
        c = DB.cases.get(id)
        if c is None:
            raise err_not_found("Case not found")
        if c["status"] in CASE_TERMINAL:
            raise err_already_terminal("Case is terminal")
        if c["status"] != "IN_PROGRESS":
            raise err_invalid_state("Case is not IN_PROGRESS")
        employee = DB.employees.get(c["employee_id"])
        if employee is None or employee["employment_status"] != "TERMINATED":
            raise err_employee_not_terminated("Employee is not TERMINATED")
        policy = DB.policies.get(c["policy_id"])
        # cascade: cancel children, release committed funds
        _cascade_cancel_children(c)
        # case ledger paid is final now
        c["status"] = "CLOSED_EARLY"
        touch_entity(c)
        # repayment assessment
        months_remaining = compute_months_remaining(
            employee["termination_date"],
            c["authorized_at"],
            policy["repayment_window_months"],
        )
        if months_remaining > 0:
            total_owed, installments_count, installment_cents, final_installment_cents = compute_schedule(
                c["total_paid_cents"], months_remaining, policy["repayment_window_months"]
            )
            now = DB.now()
            r = {
                "id": DB.new_id(),
                "case_id": c["id"],
                "total_owed_cents": total_owed,
                "installments_count": installments_count,
                "installment_cents": installment_cents,
                "final_installment_cents": final_installment_cents,
                "signed_at": None,
                "next_due_date": None,
                "paid_to_date_cents": 0,
                "balance_cents": total_owed,
                "status": "DRAFT",
                "created_at": now,
                "updated_at": now,
                "version": 0,
                "_seq": DB.next_seq(),
            }
            DB.repayment_agreements[r["id"]] = r
        return success_object(serialize_case(c))


@bp.route("/relocation-cases/<id>/close", methods=["POST"])
def close_case(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    with DB.lock:
        c = DB.cases.get(id)
        if c is None:
            raise err_not_found("Case not found")
        if c["status"] in ("CLOSED", "CANCELLED"):
            raise err_already_terminal("Case is terminal")
        if c["status"] == "CLOSED_EARLY":
            # only gate: repayment agreement must be SETTLED
            for r in DB.repayment_agreements.values():
                if r["case_id"] == c["id"] and r["status"] != "SETTLED":
                    raise err_invalid_state("Repayment agreement not settled")
            c["status"] = "CLOSED"
            touch_entity(c)
            return success_object(serialize_case(c))
        if c["status"] != "IN_PROGRESS":
            raise err_invalid_state("Case is not IN_PROGRESS")
        # IN_PROGRESS -> CLOSED gates
        for a in DB.move_assignments.values():
            if a["case_id"] == c["id"] and a["status"] in ASSIGNMENT_NONTERMINAL:
                raise err_invalid_state("Open move assignment blocks closure")
        for b in DB.service_bookings.values():
            if b["case_id"] == c["id"] and b["status"] in ("HELD", "CONFIRMED"):
                raise err_invalid_state("Open service booking blocks closure")
        for cl in DB.expense_claims.values():
            if cl["case_id"] == c["id"] and cl["status"] in ("SUBMITTED", "APPROVED"):
                raise err_invalid_state("Open expense claim blocks closure")
        for h in DB.home_sales.values():
            if h["case_id"] == c["id"] and h["status"] in ("LISTED", "SOLD"):
                raise err_invalid_state("Open home-sale transaction blocks closure")
        for r in DB.repayment_agreements.values():
            if r["case_id"] == c["id"] and r["status"] != "SETTLED":
                raise err_invalid_state("Repayment agreement not settled")
        c["status"] = "CLOSED"
        touch_entity(c)
        return success_object(serialize_case(c))
