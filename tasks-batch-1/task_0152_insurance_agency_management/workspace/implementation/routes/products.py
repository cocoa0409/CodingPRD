"""Product endpoints (PRD §3.1)."""
from flask import Blueprint, request

import serialize
from db import store, new_common
from middleware import auth, get_json_body, lookup, paginate
from response import object_response, array_response
from util import require_str, require_enum, opt_fraction

bp = Blueprint("products", __name__)

ALL_ROLES = {"AgencyAdmin", "Producer", "AccountManager", "TrustAccountant"}
LOB = {"AUTO", "HOME", "GL", "WC", "UMBRELLA"}
CANCEL_BASIS = {"PRO_RATA", "SHORT_RATE"}


@bp.post("/products")
def create_product():
    auth({"AgencyAdmin"})
    body = get_json_body()
    carrier_id = require_str(body, "carrier_id")
    with store.lock:
        lookup(store.carriers, carrier_id)  # existence (404)
        lob = require_enum(body, "line_of_business", LOB)
        name = require_str(body, "name")
        nb = opt_fraction(body, "new_business_commission_pct", default=None)
        rn = opt_fraction(body, "renewal_commission_pct", default=None)
        basis = require_enum(body, "cancellation_basis", CANCEL_BASIS)
        rec = new_common()
        rec.update(
            carrier_id=carrier_id,
            line_of_business=lob,
            name=name,
            new_business_commission_pct=nb,
            renewal_commission_pct=rn,
            cancellation_basis=basis,
        )
        store.products[rec["id"]] = rec
        return object_response(serialize.product(rec), 201)


@bp.get("/products/<pid>")
def get_product(pid):
    auth(ALL_ROLES)
    rec = lookup(store.products, pid)
    return object_response(serialize.product(rec))


@bp.get("/products")
def list_products():
    auth(ALL_ROLES)
    carrier_id = request.args.get("carrier_id")
    lob = request.args.get("line_of_business")
    recs = [
        p
        for p in store.products.values()
        if (carrier_id is None or p["carrier_id"] == carrier_id)
        and (lob is None or p["line_of_business"] == lob)
    ]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.product(p) for p in page], limit, offset, total)
