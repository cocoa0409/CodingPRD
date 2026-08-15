"""GrowerAccount and Field endpoints."""

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_GROWER_HAS_OPEN_ORDERS,
    ERR_GROWER_NOT_SETTLED,
    ERR_FIELD_HAS_ACTIVE_PLOTS,
    ERR_NOT_FOUND,
)
from middleware import authenticate, check_grower_ownership, GROWER
from response import success_obj, success_list
from routes import make_blueprint
from util import body_json, check_shape, pagination_params, paginate, apply_filters, require_fk, exist_body_fks

bp = make_blueprint("growers")

ALL_ROLES = ["DealerAdmin", "SalesRep", "Agronomist", "Grower", "ClaimsAdjuster"]
SOILS = ["CLAY", "LOAM", "SAND", "SILT"]
DRAINAGES = ["POOR", "MODERATE", "WELL"]
PREV_CROPS = ["CORN", "SOYBEAN", "WHEAT", "FALLOW", "OTHER"]


# --- GrowerAccount ----------------------------------------------------------

@bp.post("/growers")
def create_grower():
    authenticate(["DealerAdmin", "SalesRep"])
    body = body_json()
    check_shape(body, {
        "account_name": {"type": "string", "required": True},
        "external_ref": {"type": "string", "required": True},
        "credit_limit_cents": {"type": "integer", "required": True, "min": 0},
    })
    grower = db.new_entity("growers", {
        "account_name": body["account_name"],
        "external_ref": body["external_ref"],
        "credit_limit_cents": body["credit_limit_cents"],
        "status": "ACTIVE",
        "outstanding_balance_cents": 0,
        "prepay_balance_cents": 0,
    })
    return success_obj(db.public(grower), 201)


@bp.get("/growers/<gid>")
def get_grower(gid):
    uid, role = authenticate(ALL_ROLES)
    grower = require_fk("growers", gid, "grower")
    check_grower_ownership(uid, role, grower["id"])
    return success_obj(db.public(grower), 200)


@bp.get("/growers")
def list_growers():
    authenticate(["DealerAdmin", "SalesRep"])
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("growers"), ["status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(g) for g in page], limit, offset, total, has_more)


@bp.post("/growers/<gid>/hold")
def hold_grower(gid):
    authenticate(["DealerAdmin"])
    grower = require_fk("growers", gid, "grower")
    if grower["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an ACTIVE grower can be put on hold")
    grower["status"] = "CREDIT_HOLD"
    db.touch(grower)
    return success_obj(db.public(grower), 200)


@bp.post("/growers/<gid>/release_hold")
def release_grower_hold(gid):
    authenticate(["DealerAdmin"])
    grower = require_fk("growers", gid, "grower")
    if grower["status"] != "CREDIT_HOLD":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a CREDIT_HOLD grower can be released")
    grower["status"] = "ACTIVE"
    db.touch(grower)
    return success_obj(db.public(grower), 200)


@bp.post("/growers/<gid>/deactivate")
def deactivate_grower(gid):
    authenticate(["DealerAdmin"])
    grower = require_fk("growers", gid, "grower")
    if grower["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an ACTIVE grower can be deactivated")
    for order in db.all_of("orders"):
        if order["grower_id"] == grower["id"] and order["status"] in ("DRAFT", "CONFIRMED", "COMPLIANCE_HOLD"):
            raise ApiError(ERR_GROWER_HAS_OPEN_ORDERS, 409, "grower has open orders")
    if grower["outstanding_balance_cents"] != 0 or grower["prepay_balance_cents"] != 0:
        raise ApiError(ERR_GROWER_NOT_SETTLED, 409, "grower balances must both be zero")
    grower["status"] = "INACTIVE"
    db.touch(grower)
    return success_obj(db.public(grower), 200)


@bp.post("/growers/<gid>/refund_prepay")
def refund_prepay(gid):
    authenticate(["DealerAdmin"])
    grower = require_fk("growers", gid, "grower")
    body = body_json()
    check_shape(body, {"order_id": {"type": "string", "required": True}})
    order = db.get("orders", body["order_id"])
    if order is None or order["grower_id"] != grower["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, "order not found for this grower")
    if order["payment_status"] != "PREPAID":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "order is not PREPAID")
    grower["prepay_balance_cents"] -= order["prepaid_amount_cents"]
    order["prepaid_amount_cents"] = 0
    order["prepay_discount_cents"] = 0
    order["net_amount_cents"] = order["gross_amount_cents"] - order["rebate_amount_cents"]
    order["payment_status"] = "UNPAID"
    db.touch(grower)
    db.touch(order)
    return success_obj(db.public(grower), 200)


# --- Field ------------------------------------------------------------------

@bp.post("/fields")
def create_field():
    uid, role = authenticate(["DealerAdmin", "SalesRep", "Grower"])
    body = body_json()
    if role == GROWER and "grower_id" in body:
        check_grower_ownership(uid, role, body["grower_id"])
    exist_body_fks(body, {"grower_id": ("growers", "grower")})
    check_shape(body, {
        "grower_id": {"type": "string", "required": True},
        "name": {"type": "string", "required": True},
        "acres": {"type": "number", "required": True, "min": 0, "min_exclusive": True},
        "soil_type": {"type": "enum", "required": True, "values": SOILS},
        "drainage": {"type": "enum", "required": True, "values": DRAINAGES},
        "irrigated": {"type": "boolean", "required": True},
        "prev_crop": {"type": "enum", "required": True, "values": PREV_CROPS},
        "maturity_zone": {"type": "integer", "required": True, "min": 1, "max": 13},
    })
    if role == GROWER:
        check_grower_ownership(uid, role, body["grower_id"])
    field = db.new_entity("fields", {
        "grower_id": body["grower_id"],
        "name": body["name"],
        "acres": body["acres"],
        "soil_type": body["soil_type"],
        "drainage": body["drainage"],
        "irrigated": body["irrigated"],
        "prev_crop": body["prev_crop"],
        "maturity_zone": body["maturity_zone"],
        "status": "ACTIVE",
    })
    return success_obj(db.public(field), 201)


@bp.get("/fields/<fid>")
def get_field(fid):
    uid, role = authenticate(ALL_ROLES)
    field = require_fk("fields", fid, "field")
    check_grower_ownership(uid, role, field["grower_id"])
    return success_obj(db.public(field), 200)


@bp.get("/fields")
def list_fields():
    uid, role = authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("fields")
    if role == GROWER:
        items = [f for f in items if f["grower_id"] == uid]
    items = apply_filters(items, ["grower_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(f) for f in page], limit, offset, total, has_more)


@bp.post("/fields/<fid>/retire")
def retire_field(fid):
    authenticate(["DealerAdmin", "SalesRep"])
    field = require_fk("fields", fid, "field")
    if field["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only an ACTIVE field can be retired")
    for trial in db.all_of("plot_trials"):
        if trial["field_id"] == field["id"] and trial["status"] in ("PLANNED", "PLANTED"):
            raise ApiError(ERR_FIELD_HAS_ACTIVE_PLOTS, 409, "field has active plot trials")
    field["status"] = "RETIRED"
    db.touch(field)
    return success_obj(db.public(field), 200)
