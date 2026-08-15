"""Car-hire statements (PRD 3.7)."""
from flask import Blueprint, g, request

import domain
import settlement_service
from calc import days_on_lease_in_month
from envelope import ok, ok_array, ok_list
from errors import ApiError, invalid_state, not_found
from http_util import get_body, parse_pagination, require_roles, v_int, v_month, v_str
from store import db, new_entity, touch

bp_statements = Blueprint("statements", __name__)

READ_ROLES = (
    "SystemAdmin", "LeaseAdmin", "FleetPlanner", "BillingAnalyst",
    "ComplianceOfficer", "LesseeRep",
)


def _load_statement(stmt_id):
    s = db.statements.get(stmt_id)
    if s is None:
        raise not_found("ERR_STATEMENT_NOT_FOUND", f"Car-hire statement {stmt_id} not found")
    return s


@bp_statements.route("/car-hire-statements/generate", methods=["POST"])
@require_roles("BillingAnalyst")
def generate_statements():
    body = get_body()
    month = v_month(body, "statement_month")
    created = []
    assignments = sorted(
        db.assignments.values(), key=lambda a: (a["created_at"], a["_created_seq"])
    )
    for a in assignments:
        if a["status"] not in ("ON_LEASE", "RETURNED", "SETTLED"):
            continue
        if a["actual_on_lease_date"] is None:
            continue
        if days_on_lease_in_month(a, month) <= 0:
            continue
        if any(
            s["lease_assignment_id"] == a["id"] and s["statement_month"] == month
            for s in db.statements.values()
        ):
            continue
        lease = db.leases.get(a["lease_id"])
        stmt = new_entity(
            {
                "lease_assignment_id": a["id"],
                "railcar_id": a["railcar_id"],
                "lessee_id": lease["lessee_id"] if lease else None,
                "statement_month": month,
                "days_on_lease": 0,
                "gross_car_hire_cents": 0,
                "loaded_miles_used": 0,
                "tier_excess_miles": 0,
                "mileage_credit_cents": 0,
                "provisional_net_cents": 0,
                "final_net_cents": None,
                "tariff_source": "CURRENT",
                "dispute_reason": None,
                "status": "PROVISIONAL",
            }
        )
        settlement_service.apply_provisional(stmt)
        db.statements[stmt["id"]] = stmt
        created.append(stmt)
    return ok_array([domain.serialize_statement(s) for s in created], status=201)


@bp_statements.route("/car-hire-statements", methods=["GET"])
@require_roles(*READ_ROLES)
def list_statements():
    limit, offset = parse_pagination()
    items = sorted(db.statements.values(), key=lambda s: (s["created_at"], s["_created_seq"]))
    if g.user_role == "LesseeRep":
        items = [s for s in items if s["lessee_id"] == g.user_id]
    assignment_id = request.args.get("lease_assignment_id")
    railcar_id = request.args.get("railcar_id")
    lessee_id = request.args.get("lessee_id")
    month = request.args.get("statement_month")
    status = request.args.get("status")
    if assignment_id is not None:
        items = [s for s in items if s["lease_assignment_id"] == assignment_id]
    if railcar_id is not None:
        items = [s for s in items if s["railcar_id"] == railcar_id]
    if lessee_id is not None:
        items = [s for s in items if s["lessee_id"] == lessee_id]
    if month is not None:
        items = [s for s in items if s["statement_month"] == month]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([domain.serialize_statement(s) for s in page], limit, offset, total)


@bp_statements.route("/car-hire-statements/<stmt_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_statement(stmt_id):
    s = _load_statement(stmt_id)
    domain.check_lessee_ownership(s["lessee_id"])
    return ok(domain.serialize_statement(s))


@bp_statements.route("/car-hire-statements/<stmt_id>/finalize", methods=["POST"])
@require_roles("BillingAnalyst")
def finalize_statement(stmt_id):
    s = _load_statement(stmt_id)
    if s["status"] != "PROVISIONAL":
        raise ApiError(
            "ERR_STATEMENT_NOT_PROVISIONAL", 409,
            "Finalize requires the statement to be PROVISIONAL",
        )
    rep = settlement_service.validated_report_for(s["lease_assignment_id"], s["statement_month"])
    if rep is None:
        raise ApiError(
            "ERR_REPORT_NOT_VALIDATED", 409,
            "The month's mileage report does not exist or is not VALIDATED",
        )
    final_net = settlement_service.apply_final(s)
    s["status"] = "FINALIZED"
    touch(s)
    lessee = db.lessees.get(s["lessee_id"])
    if lessee is not None:
        domain.balance_add(lessee, final_net)
    return ok(domain.serialize_statement(s))


@bp_statements.route("/car-hire-statements/<stmt_id>/dispute", methods=["POST"])
@require_roles("LesseeRep")
def dispute_statement(stmt_id):
    s = _load_statement(stmt_id)
    domain.check_lessee_ownership(s["lessee_id"])
    body = get_body()
    reason = v_str(body, "dispute_reason")
    if s["status"] != "PROVISIONAL":
        raise invalid_state(f"Statement in status {s['status']} cannot be disputed")
    s["status"] = "DISPUTED"
    s["dispute_reason"] = reason
    touch(s)
    return ok(domain.serialize_statement(s))


@bp_statements.route("/car-hire-statements/<stmt_id>/recompute", methods=["POST"])
@require_roles("BillingAnalyst")
def recompute_statement(stmt_id):
    s = _load_statement(stmt_id)
    if s["status"] != "DISPUTED":
        raise invalid_state(f"Statement in status {s['status']} cannot be recomputed")
    settlement_service.apply_provisional(s)
    s["status"] = "PROVISIONAL"
    s["dispute_reason"] = None
    touch(s)
    return ok(domain.serialize_statement(s))


@bp_statements.route("/car-hire-statements/<stmt_id>/settle", methods=["POST"])
@require_roles("BillingAnalyst")
def settle_statement(stmt_id):
    s = _load_statement(stmt_id)
    body = get_body()
    amount = v_int(body, "amount_cents")
    if s["status"] != "FINALIZED":
        raise invalid_state(f"Statement in status {s['status']} cannot be settled")
    if amount != s["final_net_cents"]:
        raise ApiError(
            "ERR_PAYMENT_MISMATCH", 422,
            "amount_cents must equal final_net_cents exactly",
        )
    s["status"] = "SETTLED"
    touch(s)
    lessee = db.lessees.get(s["lessee_id"])
    if lessee is not None:
        domain.balance_add(lessee, -amount)
    return ok(domain.serialize_statement(s))
