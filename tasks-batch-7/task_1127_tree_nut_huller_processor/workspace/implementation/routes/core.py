"""Grower and Buyer master data (PRD §3.1)."""
from flask import Blueprint

import db
import response
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_GROWER_NOT_FOUND, ERR_BUYER_NOT_FOUND,
)
from middleware import authenticate, require_roles, forbid_unless, body
from validate import req_string, req_int, check_range, is_num, need
from services.serialize import grower_out, buyer_out

bp = Blueprint("core", __name__)


@bp.route("/growers", methods=["POST"])
def create_grower():
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    b = body()
    name = req_string(b, "name")
    ranch_code = req_string(b, "ranch_code")
    base_price = check_range(req_int(b, "base_price_cents_per_lb"),
                             "base_price_cents_per_lb", gt=0)
    premium = b.get("premium_rate_pct", 0.0)
    if premium is None:
        premium = 0.0
    if not is_num(premium):
        raise ApiError(ERR_INVALID_REQUEST, 400, "premium_rate_pct must be a number")
    check_range(premium, "premium_rate_pct", ge=0, le=1)
    for g in db.store.growers.values():
        if g["ranch_code"] == ranch_code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "ranch_code must be unique across growers")
    rec = db.stamp({
        "id": db.new_id(),
        "name": name,
        "ranch_code": ranch_code,
        "base_price_cents_per_lb": base_price,
        "premium_rate_pct": premium,
    })
    db.store.growers[rec["id"]] = rec
    return response.ok(grower_out(rec), 201)


@bp.route("/growers", methods=["GET"])
def list_growers():
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    return response.paginate(list(db.store.growers.values()), grower_out)


@bp.route("/growers/<rid>", methods=["GET"])
def get_grower(rid):
    auth = authenticate()
    require_roles(auth, ["PlantAdmin", "Grower"])
    if auth.is_grower:
        forbid_unless(rid == auth.user_id)
    rec = db.store.growers.get(rid)
    if rec is None:
        raise ApiError(ERR_GROWER_NOT_FOUND, 404, "Grower not found: %s" % rid)
    return response.ok(grower_out(rec))


@bp.route("/buyers", methods=["POST"])
def create_buyer():
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    b = body()
    name = req_string(b, "name")
    buyer_code = req_string(b, "buyer_code")
    for x in db.store.buyers.values():
        if x["buyer_code"] == buyer_code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "buyer_code must be unique across buyers")
    rec = db.stamp({
        "id": db.new_id(),
        "name": name,
        "buyer_code": buyer_code,
    })
    db.store.buyers[rec["id"]] = rec
    return response.ok(buyer_out(rec), 201)


@bp.route("/buyers", methods=["GET"])
def list_buyers():
    auth = authenticate()
    require_roles(auth, ["PlantAdmin"])
    return response.paginate(list(db.store.buyers.values()), buyer_out)


@bp.route("/buyers/<rid>", methods=["GET"])
def get_buyer(rid):
    auth = authenticate()
    require_roles(auth, ["PlantAdmin", "Buyer"])
    if auth.is_buyer:
        forbid_unless(rid == auth.user_id)
    rec = db.store.buyers.get(rid)
    if rec is None:
        raise ApiError(ERR_BUYER_NOT_FOUND, 404, "Buyer not found: %s" % rid)
    return response.ok(buyer_out(rec))
