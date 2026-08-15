"""Ticket products: configure, read, list, deactivate."""
from flask import Blueprint

import db
from db import serialize, touch
from helpers import get_or_404, paginate, qparam, parse_bool_param
from middleware import authenticate, scope_to_fair
from response import ok
from validators import get_body, reject_unknown, req_str, req_int, req_enum

bp = Blueprint("products", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]

PRODUCT_KINDS = ["RIDE_TICKET", "CREDIT_BUNDLE", "WRISTBAND"]


@bp.post("/ticket-products")
def create_product():
    ctx = authenticate(["FairManager"])
    body = get_body()
    reject_unknown(body, {"fair_id", "name", "kind", "base_price_cents"})
    fair_id = req_str(body, "fair_id")
    name = req_str(body, "name")
    kind = req_enum(body, "kind", PRODUCT_KINDS)
    base_price = req_int(body, "base_price_cents", lo=1)
    scope_to_fair(ctx, fair_id if db.get("fairs", fair_id) else None)
    fair = get_or_404("fairs", fair_id)
    scope_to_fair(ctx, fair["id"])
    product = db.register(
        "products",
        {
            "fair_id": fair_id,
            "name": name,
            "kind": kind,
            "base_price_cents": base_price,
            "active": True,
        },
    )
    return ok(serialize(product), 201)


@bp.get("/ticket-products/<pid>")
def get_product(pid):
    ctx = authenticate(ALL)
    product = get_or_404("products", pid)
    scope_to_fair(ctx, product["fair_id"])
    return ok(serialize(product))


@bp.get("/ticket-products")
def list_products():
    authenticate(ALL)
    return paginate(
        "products",
        {
            "fair_id": qparam("fair_id"),
            "kind": qparam("kind"),
            "active": parse_bool_param("active"),
        },
    )


@bp.post("/ticket-products/<pid>/deactivate")
def deactivate_product(pid):
    ctx = authenticate(["FairManager"])
    product = get_or_404("products", pid)
    scope_to_fair(ctx, product["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    if product["active"] is not False:
        product["active"] = False
        touch(product)
    return ok(serialize(product))
