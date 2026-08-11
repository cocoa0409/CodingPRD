from flask import Blueprint, request
from decimal import Decimal
from middleware import get_caller, require_role, get_json_body
from services.common import (require_string, require_enum, require_int,
                             require_number, optional_string, parse_pagination,
                             round_half_up_cents)
from response import success_object, success_list
from errors import ApiError
from db import db, new_common, touch, CLOCK
from services.serialize import serialize

bp = Blueprint("improvements", __name__)
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}
PROJECT_TYPES = {"TILE_DRAINAGE", "IRRIGATION", "LIMING", "FENCING"}
REIMBURSEMENT_METHODS = {"STRAIGHT_LINE", "AGREED_VALUE"}


@bp.route("/improvements", methods=["POST"])
def create_improvement():
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    field_id = require_string(body, "field_id")
    lease_id = optional_string(body, "lease_id")
    project_type = require_enum(body, "project_type", PROJECT_TYPES)
    total_cost = require_int(body, "total_cost_cents", minimum=1)
    landlord_pct = require_number(body, "landlord_share_pct", minimum=0, maximum=1)
    tenant_pct = require_number(body, "tenant_share_pct", minimum=0, maximum=1)
    method = require_enum(body, "reimbursement_method", REIMBURSEMENT_METHODS)
    amort_years = require_int(body, "amortization_years", minimum=1, maximum=10)

    # Existence
    if field_id not in db.fields:
        raise ApiError("ERR_NOT_FOUND", 404, f"Field {field_id} not found")
    if lease_id is not None and lease_id not in db.leases:
        raise ApiError("ERR_NOT_FOUND", 404, f"Lease {lease_id} not found")

    # Cost share must equal exactly 1.0
    if Decimal(str(landlord_pct)) + Decimal(str(tenant_pct)) != Decimal("1"):
        raise ApiError("ERR_COST_SHARE_INVALID", 422,
                       "landlord_share_pct + tenant_share_pct must equal 1.0")

    tenant_paid = round_half_up_cents(Decimal(total_cost) * Decimal(str(tenant_pct)))

    rec = new_common()
    rec.update({
        "field_id": field_id,
        "lease_id": lease_id,
        "project_type": project_type,
        "total_cost_cents": total_cost,
        "landlord_share_pct": landlord_pct,
        "tenant_share_pct": tenant_pct,
        "reimbursement_method": method,
        "amortization_years": amort_years,
        "tenant_paid_cents": tenant_paid,
        "completed_at": None,
        "reimbursement_due_cents": None,
        "reimbursement_status": "NONE",
        "status": "PROPOSED",
    })
    db.improvements[rec["id"]] = rec
    return success_object(serialize("improvement", rec), status=201)


@bp.route("/improvements/<improvementId>", methods=["GET"])
def get_improvement(improvementId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.improvements.get(improvementId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Improvement {improvementId} not found")
    return success_object(serialize("improvement", rec))


@bp.route("/improvements", methods=["GET"])
def list_improvements():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.improvements.values(), key=lambda r: r["created_at"])
    for param, field in (("field_id", "field_id"), ("lease_id", "lease_id"),
                         ("status", "status")):
        q = request.args.get(param)
        if q is not None:
            items = [r for r in items if r.get(field) == q]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("improvement", r) for r in page], limit, offset, total)


def _load_and_check_owner(improvementId, user_id):
    rec = db.improvements.get(improvementId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Improvement {improvementId} not found")
    field = db.fields.get(rec["field_id"])
    if field is None or field["landlord_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller does not own the field")
    return rec


@bp.route("/improvements/<improvementId>/approve", methods=["POST"])
def approve_improvement(improvementId):
    user_id, role = get_caller()
    require_role(role, {"Landlord"})
    rec = _load_and_check_owner(improvementId, user_id)
    if rec["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Improvement in state {rec['status']} cannot be approved")
    if rec.get("lease_id") is not None:
        lease = db.leases.get(rec["lease_id"])
        if lease is None or lease["status"] != "ACTIVE":
            raise ApiError("ERR_IMPROVEMENT_LEASE_NOT_ACTIVE", 409,
                           "Linked lease is not ACTIVE")
    rec["status"] = "APPROVED"
    touch(rec)
    return success_object(serialize("improvement", rec))


@bp.route("/improvements/<improvementId>/reject", methods=["POST"])
def reject_improvement(improvementId):
    user_id, role = get_caller()
    require_role(role, {"Landlord"})
    rec = _load_and_check_owner(improvementId, user_id)
    if rec["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Improvement in state {rec['status']} cannot be rejected")
    rec["status"] = "REJECTED"
    touch(rec)
    return success_object(serialize("improvement", rec))


@bp.route("/improvements/<improvementId>/complete", methods=["POST"])
def complete_improvement(improvementId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.improvements.get(improvementId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Improvement {improvementId} not found")
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Improvement in state {rec['status']} cannot be completed")
    rec["status"] = "COMPLETED"
    rec["completed_at"] = CLOCK.get()
    touch(rec)
    if rec["project_type"] == "TILE_DRAINAGE":
        field = db.fields.get(rec["field_id"])
        if field is not None:
            field["drainage_status"] = "TILED"
            touch(field)
    return success_object(serialize("improvement", rec))


@bp.route("/improvements/<improvementId>/cancel", methods=["POST"])
def cancel_improvement(improvementId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.improvements.get(improvementId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Improvement {improvementId} not found")
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Improvement in state {rec['status']} cannot be cancelled")
    rec["status"] = "CANCELLED"
    touch(rec)
    return success_object(serialize("improvement", rec))


@bp.route("/improvements/<improvementId>/mark_reimbursed", methods=["POST"])
def mark_reimbursed(improvementId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.improvements.get(improvementId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Improvement {improvementId} not found")
    if rec["status"] != "COMPLETED" or rec["reimbursement_status"] != "DUE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Improvement has no DUE reimbursement to mark paid")
    rec["reimbursement_status"] = "PAID"
    touch(rec)
    return success_object(serialize("improvement", rec))
