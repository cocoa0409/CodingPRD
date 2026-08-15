"""Grower settlement endpoints: reads and provisional advances (PRD 3.6)."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_NO_ATTRIBUTED_CARTONS,
    ERR_POOL_INVALID_STATE,
    ERR_SETTLEMENT_INVALID_STATE,
)
from middleware import authorized, check_grower_scope
from response import success_object
from routes.helpers import list_response, public, sorted_items
from services.core import touch
from services.domain import ADVANCE_RATE
from util import cents
from validate import get_body, require_path_resource

bp = Blueprint("settlements", __name__)

SETTLEMENT_READ_ROLES = ["Admin", "PoolManager", "Grower"]


@bp.get("/settlements/<settlementId>")
def get_settlement_route(settlementId):
    caller = authorized(SETTLEMENT_READ_ROLES)
    settlement = require_path_resource("settlements", settlementId)
    check_grower_scope(caller, settlement["grower_id"])
    return success_object(public(settlement))


@bp.get("/settlements")
def list_settlements():
    caller = authorized(SETTLEMENT_READ_ROLES)
    items = sorted_items("settlements")
    if caller.role == "Grower":
        # Force-filtered to the caller's own rows (PRD 2.1).
        items = [s for s in items if s["grower_id"] == caller.user_id]
    f_grower = request.args.get("grower_id")
    f_pool = request.args.get("pool_id")
    f_status = request.args.get("status")
    if f_grower is not None and caller.role != "Grower":
        items = [s for s in items if s["grower_id"] == f_grower]
    if f_pool is not None:
        items = [s for s in items if s["pool_id"] == f_pool]
    if f_status is not None:
        items = [s for s in items if s["status"] == f_status]
    return list_response(items)


@bp.post("/settlements/<settlementId>/advance")
def pay_advance(settlementId):
    authorized(["Admin", "PoolManager"])
    settlement = require_path_resource("settlements", settlementId)
    get_body()
    pool = db["pools"][settlement["pool_id"]]
    # Tier 8 state gates, fixed order: pool before settlement.
    if pool["status"] != "OPEN":
        raise_error(ERR_POOL_INVALID_STATE,
                    f"advances are paid only while the pool is OPEN, found {pool['status']}")
    if settlement["status"] != "ACCRUING":
        raise_error(ERR_SETTLEMENT_INVALID_STATE,
                    f"advance requires an ACCRUING settlement, found {settlement['status']}")
    # Tier 12: at least one attributed carton.
    if settlement["attributed_cartons"] < 1:
        raise_error(ERR_NO_ATTRIBUTED_CARTONS,
                    "settlement has no attributed cartons")
    # calc settlement_value, variant advance: 60% of the floored estimate.
    settlement["advance_amount_cents"] = cents(
        Decimal(settlement["attributed_cartons"])
        * Decimal(pool["estimated_price_cents"])
        * ADVANCE_RATE)
    settlement["status"] = "ADVANCE_PAID"
    touch(settlement)
    return success_object(public(settlement))
