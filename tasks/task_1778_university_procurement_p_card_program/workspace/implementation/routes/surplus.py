"""Surplus property: redistribution window, sale floor + high-value gate, and
the proceeds waterfall (PRD 3.9)."""

from datetime import timedelta

import db
import services as svc
from middleware import authenticate, ROLES
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json,
    check_shape,
    pagination_params,
    paginate,
    apply_filters,
    require_fk,
    parse_dt,
)
from errors import (
    ApiError,
    ERR_SURPLUS_NOT_CLAIMABLE,
    ERR_SURPLUS_NOT_LISTABLE,
    ERR_SURPLUS_NOT_SELLABLE,
    ERR_SURPLUS_NOT_DONATABLE,
    ERR_SURPLUS_NOT_SCRAPPABLE,
    ERR_REDISTRIBUTION_WINDOW_EXPIRED,
    ERR_REDISTRIBUTION_WINDOW_ACTIVE,
    ERR_SELF_CLAIM_FORBIDDEN,
    ERR_SALE_PRICE_BELOW_FLOOR,
    ERR_HIGH_VALUE_SALE_REQUIRES_DIRECTOR,
)

bp = make_blueprint("surplus")

CONDITIONS = ["NEW", "GOOD", "FAIR", "POOR"]


def _window_end(asset):
    return parse_dt(asset["declared_at"]) + timedelta(days=svc.REDISTRIBUTION_WINDOW_DAYS)


@bp.post("/surplus-assets")
def declare_asset():
    authenticate(["SurplusManager"])
    body = body_json()
    if body.get("department_id") is not None and isinstance(body.get("department_id"), str):
        require_fk("departments", body["department_id"])  # p3 before shape
    check_shape(body, {
        "asset_tag": {"type": "string", "required": True},
        "department_id": {"type": "string", "required": True},
        "description": {"type": "string", "required": True},
        "condition": {"type": "enum", "values": CONDITIONS, "required": True},
        "estimated_value_cents": {"type": "integer", "required": True},
        "disposal_cost_cents": {"type": "integer"},
    })
    asset = db.new_entity("surplus_assets", {
        "asset_tag": body["asset_tag"],
        "department_id": body["department_id"],
        "description": body["description"],
        "condition": body["condition"],
        "estimated_value_cents": body["estimated_value_cents"],
        "disposal_cost_cents": body.get("disposal_cost_cents", 0),
        "status": "DECLARED",
        "declared_at": db.logical_ts(),
        "claiming_department_id": None,
        "sale_price_cents": None,
        "buyer_name": None,
        "recipient_name": None,
        "proceeds_cost_recovery_cents": None,
        "proceeds_dept_share_cents": None,
        "proceeds_central_share_cents": None,
    })
    return success_obj(db.public(asset), 201)


@bp.get("/surplus-assets")
def list_assets():
    authenticate(ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("surplus_assets"), ["department_id", "claiming_department_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(a) for a in page], limit, offset, total, has_more)


@bp.get("/surplus-assets/<aid>")
def get_asset(aid):
    authenticate(ROLES)
    asset = require_fk("surplus_assets", aid)
    return success_obj(db.public(asset), 200)


@bp.post("/surplus-assets/<aid>/claim")
def claim_asset(aid):
    """Claim for another department inside the half-open redistribution window
    [declared_at, declared_at + 10 days)."""
    authenticate(["Requester"])
    asset = require_fk("surplus_assets", aid)
    body = body_json()
    if body.get("claiming_department_id") is not None and isinstance(body.get("claiming_department_id"), str):
        require_fk("departments", body["claiming_department_id"])  # p3
    if asset["status"] != "DECLARED":
        raise ApiError(ERR_SURPLUS_NOT_CLAIMABLE, 409, "claim requires a DECLARED asset")
    check_shape(body, {"claiming_department_id": {"type": "string", "required": True}})
    if body["claiming_department_id"] == asset["department_id"]:
        raise ApiError(ERR_SELF_CLAIM_FORBIDDEN, 403, "the owning department may not claim its own asset")
    if not db.now() < _window_end(asset):
        raise ApiError(ERR_REDISTRIBUTION_WINDOW_EXPIRED, 409, "the redistribution window has elapsed")
    asset["status"] = "TRANSFERRED"
    asset["claiming_department_id"] = body["claiming_department_id"]
    db.touch(asset)
    return success_obj(db.public(asset), 200)


@bp.post("/surplus-assets/<aid>/list-for-sale")
def list_for_sale(aid):
    authenticate(["SurplusManager"])
    asset = require_fk("surplus_assets", aid)
    if asset["status"] != "DECLARED":
        raise ApiError(ERR_SURPLUS_NOT_LISTABLE, 409, "list-for-sale requires a DECLARED asset")
    if not db.now() >= _window_end(asset):
        raise ApiError(ERR_REDISTRIBUTION_WINDOW_ACTIVE, 409, "the redistribution window is still active")
    asset["status"] = "LISTED"
    db.touch(asset)
    return success_obj(db.public(asset), 200)


@bp.post("/surplus-assets/<aid>/sell")
def sell_asset(aid):
    _, role = authenticate(["SurplusManager", "ProcurementDirector"])
    asset = require_fk("surplus_assets", aid)
    if asset["status"] != "LISTED":
        raise ApiError(ERR_SURPLUS_NOT_SELLABLE, 409, "sell requires a LISTED asset")
    body = body_json()
    check_shape(body, {
        "sale_price_cents": {"type": "integer", "required": True},
        "buyer_name": {"type": "string"},
    })
    # p11 fiscal: floor first, then the value-conditional role gate (PRD 3.9
    # narrative order); the gate reports ERR_HIGH_VALUE_SALE_REQUIRES_DIRECTOR
    # rather than the generic role error.
    floor = svc.sale_floor_cents(asset)
    if body["sale_price_cents"] < floor:
        raise ApiError(ERR_SALE_PRICE_BELOW_FLOOR, 422, "sale price is below the floor")
    if asset["estimated_value_cents"] >= svc.HIGH_VALUE_SALE_CENTS and role != "ProcurementDirector":
        raise ApiError(ERR_HIGH_VALUE_SALE_REQUIRES_DIRECTOR, 403, "high-value sales require the ProcurementDirector")
    price = body["sale_price_cents"]
    cost_recovery, dept_share, central_share = svc.proceeds_waterfall(asset, price)
    asset["status"] = "SOLD"
    asset["sale_price_cents"] = price
    asset["buyer_name"] = body.get("buyer_name")
    asset["proceeds_cost_recovery_cents"] = cost_recovery
    asset["proceeds_dept_share_cents"] = dept_share
    asset["proceeds_central_share_cents"] = central_share
    db.touch(asset)
    return success_obj(db.public(asset), 200)


@bp.post("/surplus-assets/<aid>/donate")
def donate_asset(aid):
    authenticate(["SurplusManager"])
    asset = require_fk("surplus_assets", aid)
    if asset["status"] != "LISTED":
        raise ApiError(ERR_SURPLUS_NOT_DONATABLE, 409, "donate requires a LISTED asset")
    body = body_json()
    check_shape(body, {"recipient_name": {"type": "string", "required": True, "non_empty": True}})
    asset["status"] = "DONATED"
    asset["recipient_name"] = body["recipient_name"]
    db.touch(asset)
    return success_obj(db.public(asset), 200)


@bp.post("/surplus-assets/<aid>/scrap")
def scrap_asset(aid):
    authenticate(["SurplusManager"])
    asset = require_fk("surplus_assets", aid)
    if asset["status"] not in ("DECLARED", "LISTED"):
        raise ApiError(ERR_SURPLUS_NOT_SCRAPPABLE, 409, "scrap requires DECLARED or LISTED")
    body_json()  # optional reason accepted, not persisted
    asset["status"] = "SCRAPPED"
    db.touch(asset)
    return success_obj(db.public(asset), 200)
