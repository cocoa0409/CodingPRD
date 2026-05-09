"""Fee-bill issuance, list/get with refresh, waiver."""
from __future__ import annotations

from flask import Blueprint, g, request

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import require_roles
from response import success, success_list
from services.fees import (
    issue_bills_for_period,
    read_with_refresh,
    waive_bill,
)
from utils import get_body, paginate, parse_pagination, require_field

bp = Blueprint("fee_bills", __name__)


@bp.post("/fee-bills/issue")
@require_roles("PropertyManager")
def issue():
    body = get_body()
    period_year = require_field(body, "period_year")
    period_month = require_field(body, "period_month")
    if not isinstance(period_year, int) or not isinstance(period_month, int):
        raise APIError(ERR_VALIDATION, "period_year and period_month must be integers.", 422)
    if not (1 <= period_month <= 12):
        raise APIError(ERR_VALIDATION, "period_month must be in [1,12].", 422)
    issued = issue_bills_for_period(period_year, period_month)
    return success(issued, status=201)


def _bill_visible_to_owner(bill: dict, user_id: str) -> bool:
    prop = db.properties.get(bill.get("property_id"))
    return bool(prop and prop.get("owner_id") == user_id)


@bp.get("/fee-bills/<bid>")
@require_roles("PropertyManager", "Owner")
def get_bill(bid):
    bill = db.fee_bills.get(bid)
    if bill is None:
        raise APIError(ERR_NOT_FOUND, f"FeeBill {bid} not found.", 404)
    if g.user_role == "Owner" and not _bill_visible_to_owner(bill, g.user_id):
        raise APIError(ERR_FORBIDDEN, "Owner cannot read others' bills.", 403)
    read_with_refresh(bill)
    return success(bill)


@bp.get("/fee-bills")
@require_roles("PropertyManager", "Owner")
def list_bills():
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    dunning_stage = request.args.get("dunning_stage")

    items = list(db.fee_bills.values())
    if g.user_role == "Owner":
        items = [b for b in items if _bill_visible_to_owner(b, g.user_id)]
    if property_id:
        items = [b for b in items if b.get("property_id") == property_id]
    if status:
        items = [b for b in items if b.get("status") == status]
    if dunning_stage:
        items = [b for b in items if b.get("dunning_stage") == dunning_stage]

    # Refresh on read for non-terminal bills.
    for b in items:
        read_with_refresh(b)

    items.sort(key=lambda b: (b.get("created_at", ""), b.get("id", "")))
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.post("/fee-bills/<bid>/waive")
@require_roles("PropertyManager")
def waive(bid):
    bill = db.fee_bills.get(bid)
    if bill is None:
        raise APIError(ERR_NOT_FOUND, f"FeeBill {bid} not found.", 404)
    body = get_body()
    reason = require_field(body, "reason")
    if bill.get("status") in ("PAID", "WAIVED"):
        raise APIError(
            __import__("errors").ERR_INVALID_STATE,
            "Bill is in a terminal state.",
            409,
        )
    waive_bill(bill, reason=reason)
    return success(bill)
