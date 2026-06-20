"""Lender endpoints — PRD §3.1, §4."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles
from response import object_response, array_response
from services.common import (
    serialize, get_json_body, require_enum, require_string,
    paginate, sort_by_created,
)

bp = Blueprint("lenders", __name__)

ALL_READ_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover", "InvestorServicer"]
LENDER_BORROWER_READ_ROLES = ["SbaOfficer", "LoanOfficer", "CreditApprover"]


@bp.post("/sba/lenders")
def create_lender():
    user_id, role = get_user_context()
    require_roles(role, ["SbaOfficer"])
    body = get_json_body()
    name = require_string(body, "name")
    program = require_enum(body, "program", {"7A", "504"})
    with db.LOCK:
        rec = db.init_record({
            "name": name,
            "program": program,
            "ongoing_fee_pool_cents": 0,
            "sold_guaranty_balance_cents": 0,
        })
        db.lenders[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/sba/lenders/<lender_id>")
def get_lender(lender_id):
    user_id, role = get_user_context()
    # GET lender is readable by all four roles (InvestorServicer reads pool balances).
    require_roles(role, ALL_READ_ROLES)
    with db.LOCK:
        rec = db.lenders.get(lender_id)
        if rec is None:
            raise errors.not_found("Lender not found")
        return object_response(serialize(rec), 200)


@bp.get("/sba/lenders/<lender_id>/borrowers")
def list_lender_borrowers(lender_id):
    user_id, role = get_user_context()
    require_roles(role, LENDER_BORROWER_READ_ROLES)
    with db.LOCK:
        if lender_id not in db.lenders:
            raise errors.not_found("Lender not found")
        items = [b for b in db.borrowers.values() if b["lender_id"] == lender_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.get("/sba/lenders/<lender_id>/guaranty-sales")
def list_lender_guaranty_sales(lender_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_READ_ROLES)
    with db.LOCK:
        if lender_id not in db.lenders:
            raise errors.not_found("Lender not found")
        items = [s for s in db.guaranty_sales.values() if s["lender_id"] == lender_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)
