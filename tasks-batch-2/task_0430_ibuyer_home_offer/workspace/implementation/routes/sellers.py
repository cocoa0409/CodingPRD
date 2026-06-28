"""Seller endpoints (PRD §3.1)."""

from flask import Blueprint, request

from constants import PAYOUT_METHODS
from db import store
from errors import err
from helpers import get_seller_or_404
from middleware import authenticate, require_role
from models import serialize, stamp_create
from response import object_response
from validators import as_enum, as_string, get_body, require

bp = Blueprint("sellers", __name__)


@bp.route("/sellers", methods=["POST"])
def create_seller():
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "Seller"})

    body = get_body(request)
    email = as_string(require(body, "email"), "email")
    full_name = as_string(require(body, "full_name"), "full_name")

    payout_method = "ACH"
    if body.get("payout_method") is not None:
        payout_method = as_enum(body["payout_method"], "payout_method", PAYOUT_METHODS)

    # email unique across sellers
    for s in store.sellers.values():
        if s["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique across sellers")

    rec = {
        "email": email,
        "full_name": full_name,
        "payout_method": payout_method,
    }
    stamp_create(rec)
    store.sellers[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/sellers/<seller_id>", methods=["GET"])
def get_seller(seller_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "Seller", "PricingAnalyst"})
    rec = get_seller_or_404(seller_id)
    return object_response(serialize(rec), 200)
