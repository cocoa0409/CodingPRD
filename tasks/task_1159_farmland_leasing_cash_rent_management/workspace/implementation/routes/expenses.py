from flask import Blueprint, request
from decimal import Decimal
from middleware import get_caller, require_role, get_json_body
from services.common import (require_string, require_enum, require_int,
                             require_datetime, parse_pagination, round_half_up_cents)
from response import success_object, success_list
from errors import ApiError
from db import db, new_common, touch, CLOCK
from services.serialize import serialize

bp = Blueprint("expenses", __name__)
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}
CATEGORIES = {"SEED", "FERTILIZER", "CHEMICAL", "FUEL", "OTHER"}


@bp.route("/expenses", methods=["POST"])
def create_expense():
    user_id, role = get_caller()
    require_role(role, {"Tenant"})
    body = get_json_body()
    lease_id = require_string(body, "lease_id")
    category = require_enum(body, "category", CATEGORIES)
    total_cost = require_int(body, "total_cost_cents", minimum=1)
    incurred = require_datetime(body, "incurred_date")
    crop_year = require_int(body, "crop_year")

    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Lease {lease_id} not found")

    # Ownership: caller is the lease tenant
    if lease["tenant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the lease tenant")

    # State: lease must be ACTIVE
    if lease["status"] != "ACTIVE":
        raise ApiError("ERR_LEASE_NOT_ACTIVE", 409, "Expense creation requires lease ACTIVE")

    # Type applicability: CASH leases have no input sharing
    if lease["lease_type"] == "CASH":
        raise ApiError("ERR_INPUT_SHARING_NOT_APPLICABLE", 409,
                       "Expense records do not apply to CASH leases")

    pct = lease.get("input_share_pct") or 0
    share_cents = round_half_up_cents(Decimal(total_cost) * Decimal(str(pct)))

    rec = new_common()
    rec.update({
        "lease_id": lease_id,
        "category": category,
        "total_cost_cents": total_cost,
        "incurred_date": incurred,
        "crop_year": crop_year,
        "landlord_share_pct": pct,
        "landlord_share_cents": share_cents,
        "approved_at": None,
        "status": "SUBMITTED",
    })
    db.expenses[rec["id"]] = rec
    return success_object(serialize("expense", rec), status=201)


@bp.route("/expenses/<expenseId>", methods=["GET"])
def get_expense(expenseId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.expenses.get(expenseId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Expense {expenseId} not found")
    return success_object(serialize("expense", rec))


@bp.route("/expenses", methods=["GET"])
def list_expenses():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.expenses.values(), key=lambda r: r["created_at"])
    lease_q = request.args.get("lease_id")
    if lease_q is not None:
        items = [r for r in items if r["lease_id"] == lease_q]
    status_q = request.args.get("status")
    if status_q is not None:
        items = [r for r in items if r["status"] == status_q]
    cy_q = request.args.get("crop_year")
    if cy_q is not None:
        try:
            cy = int(cy_q)
            items = [r for r in items if r["crop_year"] == cy]
        except ValueError:
            raise ApiError("ERR_VALIDATION", 400, "crop_year must be an integer")
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("expense", r) for r in page], limit, offset, total)


@bp.route("/expenses/<expenseId>/approve", methods=["POST"])
def approve_expense(expenseId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.expenses.get(expenseId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Expense {expenseId} not found")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Expense in state {rec['status']} cannot be approved")
    rec["status"] = "APPROVED"
    rec["approved_at"] = CLOCK.get()
    touch(rec)
    return success_object(serialize("expense", rec))


@bp.route("/expenses/<expenseId>/reject", methods=["POST"])
def reject_expense(expenseId):
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    rec = db.expenses.get(expenseId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Expense {expenseId} not found")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Expense in state {rec['status']} cannot be rejected")
    rec["status"] = "REJECTED"
    touch(rec)
    return success_object(serialize("expense", rec))
