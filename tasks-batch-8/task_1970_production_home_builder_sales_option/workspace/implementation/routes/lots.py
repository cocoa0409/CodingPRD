"""Lot endpoints: create / list / get / release / reserve / release-reservation
(PRD section 3.2)."""

from datetime import timedelta

import db
from constants import READ_ROLES, LOT_TYPES, HOLD_HOURS, ROLE_BUYER, ROLE_SALES_DIRECTOR
from errors import (
    ApiError,
    ERR_COMMUNITY_NOT_FOUND,
    ERR_COMMUNITY_NOT_SELLING,
    ERR_LOT_NOT_FOUND,
    ERR_BUYER_NOT_FOUND,
    ERR_NOT_RESOURCE_OWNER,
    ERR_LOT_INVALID_STATE,
    ERR_LOT_NOT_RELEASED,
    ERR_LOT_HOLD_ACTIVE,
    ERR_DUPLICATE_LOT_NUMBER,
)
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from services import ser_lot, lot_release_price
from util import (
    body_json,
    check_shape,
    require_fk,
    parse_dt,
    pagination_params,
    paginate,
    apply_filters,
)

bp = make_blueprint("lots")

CREATE_SPEC = {
    "community_id": {"type": "string", "required": True},
    "lot_number": {"type": "string", "required": True},
    "base_price_cents": {"type": "integer", "required": True, "min": 1},
    "lot_type": {"type": "enum", "required": True, "values": LOT_TYPES},
    "view_adjustment_cents": {"type": "integer", "min": 0},
}

RESERVE_SPEC = {
    "buyer_id": {"type": "string", "required": True},
}


@bp.post("/lots")
def create_lot():
    authenticate(["SalesDirector"])
    body = body_json()
    check_shape(body, CREATE_SPEC)
    require_fk("communities", body["community_id"], ERR_COMMUNITY_NOT_FOUND, "community")
    # Uniqueness (tier 9): lot_number unique within the community.
    for existing in db.all_of("lots"):
        if (
            existing["community_id"] == body["community_id"]
            and existing["lot_number"] == body["lot_number"]
        ):
            raise ApiError(ERR_DUPLICATE_LOT_NUMBER, 409, "lot_number already exists within the community")
    lot = db.new_entity("lots", {
        "community_id": body["community_id"],
        "lot_number": body["lot_number"],
        "base_price_cents": body["base_price_cents"],
        "lot_type": body["lot_type"],
        "view_adjustment_cents": body.get("view_adjustment_cents", 0),
        "release_price_cents": None,  # null while DRAFT
        "release_count": 0,
        "reserved_buyer_id": None,
        "hold_expires_at": None,
        "status": "DRAFT",
    })
    return success_obj(ser_lot(lot), 201)


@bp.get("/lots")
def list_lots():
    authenticate(READ_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("lots"), ["community_id", "reserved_buyer_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([ser_lot(l) for l in page], limit, offset, total, has_more)


@bp.get("/lots/<lid>")
def get_lot(lid):
    authenticate(READ_ROLES)
    lot = require_fk("lots", lid, ERR_LOT_NOT_FOUND, "lot")
    return success_obj(ser_lot(lot), 200)


@bp.post("/lots/<lid>/release")
def release_lot(lid):
    authenticate(["SalesDirector"])
    lot = require_fk("lots", lid, ERR_LOT_NOT_FOUND, "lot")
    # State tier (scaffold order): lot must be DRAFT, then community SELLING.
    if lot["status"] != "DRAFT":
        raise ApiError(ERR_LOT_INVALID_STATE, 409, "only a DRAFT lot can be released")
    community = db.get("communities", lot["community_id"])
    if community is None or community["status"] != "SELLING":
        raise ApiError(ERR_COMMUNITY_NOT_SELLING, 409, "community is not open for sales")
    lot["release_price_cents"] = lot_release_price(lot, db.now())
    lot["status"] = "RELEASED"
    db.touch(lot)
    return success_obj(ser_lot(lot), 200)


@bp.post("/lots/<lid>/reserve")
def reserve_lot(lid):
    user_id, role = authenticate(["Buyer"])
    body = body_json()
    check_shape(body, RESERVE_SPEC)
    # Existence (tier 4): path id first, then the body FK.
    lot = require_fk("lots", lid, ERR_LOT_NOT_FOUND, "lot")
    require_fk("buyers", body["buyer_id"], ERR_BUYER_NOT_FOUND, "buyer")
    # Ownership (tier 5): the body's buyer_id must equal the acting Buyer.
    if body["buyer_id"] != user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "buyer_id must equal the acting buyer")
    # State tier (tier 7): community SELLING, then lot state.
    community = db.get("communities", lot["community_id"])
    if community is None or community["status"] != "SELLING":
        raise ApiError(ERR_COMMUNITY_NOT_SELLING, 409, "community is not open for sales")
    if lot["status"] == "RESERVED":
        hold_expires = parse_dt(lot["hold_expires_at"], "hold_expires_at")
        if hold_expires <= db.now():
            # Expired-but-unswept hold: reported from the state tier.
            raise ApiError(ERR_LOT_NOT_RELEASED, 409, "lot is not RELEASED")
        # Active hold: temporal tier (tier 8), evaluated after state.
        raise ApiError(ERR_LOT_HOLD_ACTIVE, 409, "another buyer's reservation hold is still active")
    if lot["status"] != "RELEASED":
        raise ApiError(ERR_LOT_NOT_RELEASED, 409, "lot is not RELEASED")
    lot["status"] = "RESERVED"
    lot["reserved_buyer_id"] = body["buyer_id"]
    lot["hold_expires_at"] = db.fmt_ts(db.now() + timedelta(hours=HOLD_HOURS))
    db.touch(lot)
    return success_obj(ser_lot(lot), 200)


@bp.post("/lots/<lid>/release-reservation")
def release_reservation(lid):
    user_id, role = authenticate(["Buyer", "SalesDirector"])
    lot = require_fk("lots", lid, ERR_LOT_NOT_FOUND, "lot")
    # Ownership (tier 5): a Buyer caller must be the reservation holder;
    # SalesDirector is exempt.
    if role == ROLE_BUYER and lot["reserved_buyer_id"] != user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403, "buyer does not hold this reservation")
    if lot["status"] != "RESERVED":
        raise ApiError(ERR_LOT_INVALID_STATE, 409, "lot is not RESERVED")
    # Hold churn never reprices: release_price_cents and release_count unchanged.
    lot["status"] = "RELEASED"
    lot["reserved_buyer_id"] = None
    lot["hold_expires_at"] = None
    db.touch(lot)
    return success_obj(ser_lot(lot), 200)
