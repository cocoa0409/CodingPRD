"""Promotion endpoints (PRD §3.4)."""
from flask import Blueprint

from db import DB
from middleware import auth_context, require_role
from common import (
    stamp_create, touch, public_view, get_json_body, as_int, as_str,
    as_bool, as_enum,
)
from response import success
from errors import err, ERR_NOT_FOUND, ERR_DUPLICATE_RESOURCE, ERR_INVALID_STATE

bp = Blueprint("promotions", __name__)

PROMO_KINDS = {"PERCENT_OFF", "AMOUNT_OFF", "BOGO_50"}


@bp.route("/promotions", methods=["POST"])
def create_promotion():
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    body = get_json_body()
    code = as_str(body, "code")
    kind = as_enum(body, "kind", PROMO_KINDS)
    value = as_int(body, "value", minimum=0)
    min_subtotal_cents = as_int(body, "min_subtotal_cents", required=False,
                                default=0, minimum=0)
    stackable = as_bool(body, "stackable", default=False)

    with DB.lock:
        for p in DB.promotions.values():
            if p["code"] == code:
                raise err(ERR_DUPLICATE_RESOURCE, "Promo code already exists")
        promo = {
            "code": code,
            "kind": kind,
            "value": value,
            "min_subtotal_cents": min_subtotal_cents,
            "stackable": stackable,
            "status": "ACTIVE",
        }
        stamp_create(promo)
        DB.promotions[promo["id"]] = promo
        return success(public_view(promo), status=201)


@bp.route("/promotions/<promo_id>", methods=["GET"])
def get_promotion(promo_id):
    _, role = auth_context()
    require_role(role, {"StoreManager", "Cashier"})
    with DB.lock:
        promo = DB.promotions.get(promo_id)
        if promo is None:
            raise err(ERR_NOT_FOUND, "Promotion not found")
        return success(public_view(promo))


@bp.route("/promotions/<promo_id>/disable", methods=["POST"])
def disable_promotion(promo_id):
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    with DB.lock:
        promo = DB.promotions.get(promo_id)
        if promo is None:
            raise err(ERR_NOT_FOUND, "Promotion not found")
        if promo["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Promotion is not ACTIVE")
        promo["status"] = "DISABLED"
        touch(promo)
        return success(public_view(promo))
