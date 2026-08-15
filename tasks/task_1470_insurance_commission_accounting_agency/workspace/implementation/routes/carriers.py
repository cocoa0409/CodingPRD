"""Carrier endpoints including trust remittance."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import auth, ADMIN, ADMIN_ACCT, ALL_ROLES
from response import ok
from services import new_resource, remittable_cents, ser_carrier, touch
from util import as_pos_int, as_str, get_body, is_int, req

bp = Blueprint("carriers", __name__)


@bp.post("/agency/carriers")
def create_carrier():
    auth(ADMIN_ACCT)
    data = get_body()
    name = as_str(req(data, "name"), "name")
    carrier_code = as_str(req(data, "carrier_code"), "carrier_code")
    c = new_resource({
        "name": name,
        "carrier_code": carrier_code,
        "trust_balance_cents": 0,
        "total_remitted_cents": 0,
    })
    DB["carriers"][c["id"]] = c
    return ok(ser_carrier(c), 201)


@bp.get("/agency/carriers/<carrierId>")
def get_carrier(carrierId):
    auth(ALL_ROLES)
    c = DB["carriers"].get(carrierId)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Carrier not found")
    return ok(ser_carrier(c))


@bp.post("/agency/carriers/<carrierId>/remit")
def remit_carrier(carrierId):
    auth(ADMIN)
    c = DB["carriers"].get(carrierId)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Carrier not found")
    data = get_body()
    # Priority 9: fiscal limit — 0 < amount <= remittable.
    amount = data.get("amount_cents")
    if is_int(amount) and amount > 0 and amount > remittable_cents(c):
        raise ApiError(
            "ERR_REMIT_EXCEEDS_REMITTABLE",
            409,
            "Remittance exceeds trust balance minus retained commission",
        )
    # Priority 10: shape.
    amount = as_pos_int(req(data, "amount_cents"), "amount_cents")
    c["trust_balance_cents"] -= amount
    c["total_remitted_cents"] += amount
    touch(c)
    return ok(ser_carrier(c))
