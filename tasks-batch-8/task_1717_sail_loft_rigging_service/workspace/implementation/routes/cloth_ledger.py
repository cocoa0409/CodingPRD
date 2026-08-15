"""ClothLedgerEntry endpoints."""

from flask import Blueprint, request

import db
import util
from middleware import require_roles
from response import success_object, success_list
from services import domain

bp = Blueprint("cloth_ledger", __name__)

CLOTH_TIERS = ("CRUISE", "PERFORMANCE", "RACE", "GRAND_PRIX")


@bp.post("/lofts/cloth-ledger")
def create_bolt():
    require_roles("LoftManager")
    body = util.get_body()
    bolt_code = util.as_string(util.require_field(body, "bolt_code"), "bolt_code")
    cloth_tier = util.as_enum(util.require_field(body, "cloth_tier"), "cloth_tier", CLOTH_TIERS)
    total_sqm = util.as_number(util.require_field(body, "total_sqm"), "total_sqm")
    price_per_sqm_cents = util.as_int(util.require_field(body, "price_per_sqm_cents"), "price_per_sqm_cents")
    bolt = util.stamp_new({
        "bolt_code": bolt_code,
        "cloth_tier": cloth_tier,
        "total_sqm": total_sqm,
        "available_sqm": total_sqm,
        "price_per_sqm_cents": price_per_sqm_cents,
    })
    db.cloth_ledger[bolt["id"]] = bolt
    return success_object(domain.serialize(bolt), 201)


@bp.get("/lofts/cloth-ledger")
def list_bolts():
    require_roles("LoftManager", "Sailmaker")
    limit, offset = util.pagination_params()
    items = util.sort_by_created(list(db.cloth_ledger.values()))
    items = util.filter_exact(items, "cloth_tier", request.args.get("cloth_tier"))
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(b) for b in page], limit, offset, total)


@bp.get("/lofts/cloth-ledger/<boltId>")
def get_bolt(boltId):
    require_roles("LoftManager", "Sailmaker")
    bolt = domain.get_bolt_or_404(boltId)
    return success_object(domain.serialize(bolt))
