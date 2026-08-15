"""RepricingCycle endpoints."""

from flask import Blueprint

from db import STORE
from errors import ApiError, ERR_PRODUCT_NOT_FOUND, not_found
from middleware import get_body, paginate, query_enum, require_roles
from response import ok_object
from serialize import cycle_status, serialize, serialize_many
from utils import bump, req_int, req_str, stamp_new

bp = Blueprint("cycles", __name__)


def _find_cycle(product_id, market_code):
    for c in STORE["cycles"].values():
        if c["product_id"] == product_id and c["market_code"] == market_code:
            return c
    return None


@bp.post("/repricing-cycles")
@require_roles("PricingAnalyst")
def upsert_cycle():
    data = get_body()
    product_id = req_str(data, "product_id")
    market_code = req_str(data, "market_code")
    cadence_days = req_int(data, "cadence_days", minimum=1)
    if product_id not in STORE["products"]:
        raise ApiError(ERR_PRODUCT_NOT_FOUND, 422, "Referenced product_id does not exist")
    existing = _find_cycle(product_id, market_code)
    if existing is not None:
        # Create-or-replace: the pair key is unique; posting again replaces the
        # cadence configuration while preserving review history.
        existing["cadence_days"] = cadence_days
        bump(existing)
        return ok_object(serialize("cycles", existing), 201)
    row = {
        "product_id": product_id,
        "market_code": market_code,
        "cadence_days": cadence_days,
        "last_reviewed_at": None,
    }
    stamp_new(row)
    STORE["cycles"][row["id"]] = row
    return ok_object(serialize("cycles", row), 201)


@bp.get("/repricing-cycles")
@require_roles("PricingAnalyst", "PricingCommittee")
def list_cycles():
    from flask import request
    product_id = request.args.get("product_id")
    market_code = request.args.get("market_code")
    status = query_enum("status", ("CURRENT", "OVERDUE"))
    rows = list(STORE["cycles"].values())
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if market_code is not None:
        rows = [r for r in rows if r["market_code"] == market_code]
    if status is not None:
        rows = [r for r in rows if cycle_status(r) == status]
    return paginate(serialize_many("cycles", rows))


@bp.get("/repricing-cycles/<cycle_id>")
@require_roles("PricingAnalyst", "PricingCommittee")
def get_cycle(cycle_id):
    row = STORE["cycles"].get(cycle_id)
    if row is None:
        raise not_found("Repricing cycle not found")
    return ok_object(serialize("cycles", row))
