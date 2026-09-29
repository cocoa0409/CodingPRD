"""Buyer endpoints (PRD 3.1)."""

from flask import Blueprint

from db import base_row, db, public
from middleware import (BUYER_ADMIN, BUYER_TREASURY, PLATFORM_OPS, authenticate,
                        get_buyer, scope_buyer)
from response import ok, ok_list
from services import recompute as rc
from validation import (body, filter_arg, opt_bool, opt_int, paginate,
                        pagination, req_digits, req_int, req_str)

bp = Blueprint("buyers", __name__)

READ_ROLES = (PLATFORM_OPS, BUYER_ADMIN, BUYER_TREASURY)


@bp.post("/buyers")
def create_buyer():
    authenticate((PLATFORM_OPS,))
    b = body()
    legal_name = req_str(b, "legal_name", 1, 200)
    tax_id = req_digits(b, "tax_id", 9)
    credit_limit_cents = req_int(b, "credit_limit_cents", 0)
    self_funding_enabled = opt_bool(b, "self_funding_enabled", True)
    reclass_days_threshold = opt_int(b, "reclass_days_threshold", 0, None, 30)
    reclass_apr_threshold_bps = opt_int(b, "reclass_apr_threshold_bps", 0, None, 900)
    for existing in db.buyers.values():
        if existing["tax_id"] == tax_id:
            from validation import bad
            bad(detail="tax_id must be unique across buyers.")
    row = base_row()
    row.update(
        {
            "legal_name": legal_name,
            "tax_id": tax_id,
            "credit_limit_cents": credit_limit_cents,
            "credit_used_cents": 0,
            "self_funding_enabled": self_funding_enabled,
            "reclass_days_threshold": reclass_days_threshold,
            "reclass_apr_threshold_bps": reclass_apr_threshold_bps,
            "status": "ACTIVE",
        }
    )
    db.buyers[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/buyers/<buyer_id>")
def read_buyer(buyer_id):
    ctx = authenticate(READ_ROLES)
    buyer = get_buyer(buyer_id)
    scope_buyer(ctx, buyer["id"])
    return ok(public(buyer))


@bp.get("/buyers/<buyer_id>/programs")
def list_buyer_programs(buyer_id):
    ctx = authenticate(READ_ROLES)
    limit, offset = pagination()
    buyer = get_buyer(buyer_id)
    scope_buyer(ctx, buyer["id"])
    status = filter_arg("status")
    rows = rc.buyer_programs(buyer["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    page = paginate(rows, limit, offset)
    return ok_list([public(r) for r in page], limit, offset, total)
