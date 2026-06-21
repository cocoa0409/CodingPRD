from flask import Blueprint, request

import errors
from db import db
from middleware import authenticate, require_roles
from response import success, list_success
from services import validate as V
from services.common import new_common, paginate, page_slice
from services.serialize import pass_product_out

bp = Blueprint("pass_products", __name__)

READ_ROLES = {"NetworkAdmin", "ResortOps", "RefundAdmin"}
TIERS = {"LOCAL", "EPIC_DAY", "FULL_EPIC"}


@bp.post("/pass-products")
def create_pass_product():
    _, role = authenticate()
    require_roles(role, {"NetworkAdmin"})
    body = V.get_body(request)
    tier = V.require_enum(body, "tier", TIERS)
    price_cents = V.require_int(body, "price_cents", minimum=0)
    blackout_dates = V.optional_date_list(body, "blackout_dates", [])
    buddy_allotment = V.optional_int(body, "buddy_ticket_allotment", 0, minimum=0)
    buddy_price = V.optional_int(body, "buddy_ticket_price_cents", 0, minimum=0)
    ikon = V.optional_bool(body, "ikon_interchange_enabled", False)

    # Uniqueness of tier (ERR_DUPLICATE_TIER, priority 5 — after ERR_VALIDATION).
    for p in db.pass_products.values():
        if p["tier"] == tier:
            raise errors.ApiError(errors.ERR_DUPLICATE_TIER, 409,
                                  "A pass product with this tier already exists")

    rec = new_common({
        "tier": tier,
        "price_cents": price_cents,
        "blackout_dates": blackout_dates,
        "buddy_ticket_allotment": buddy_allotment,
        "buddy_ticket_price_cents": buddy_price,
        "ikon_interchange_enabled": ikon,
    })
    db.pass_products[rec["id"]] = rec
    return success(pass_product_out(rec), status=201)


@bp.get("/pass-products")
def list_pass_products():
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    limit, offset = paginate(request.args)
    tier = request.args.get("tier")
    records = list(db.pass_products.values())
    if tier is not None:
        records = [p for p in records if p["tier"] == tier]
    window, total = page_slice(records, limit, offset)
    return list_success([pass_product_out(p) for p in window], limit, offset, total)


@bp.get("/pass-products/<pid>")
def get_pass_product(pid):
    _, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.pass_products.get(pid)
    if rec is None:
        raise errors.not_found("Pass product not found")
    return success(pass_product_out(rec))
