"""ShippingStateRule endpoints."""
from flask import Blueprint

import db as _db
from db import db, new_entity
from errors import duplicate
from helpers import (body, get_or_404, opt_int, paginate, pagination_params,
                     parse_bool_param, public, req_bool, req_int, req_str)
from middleware import require
from response import success

bp = Blueprint("shipping_rules", __name__)


@bp.post("/shipping-state-rules")
def create_rule():
    require(["PlatformAdmin", "ComplianceOfficer"])
    data = body()
    state_code = req_str(data, "state_code", min_len=2, max_len=2)
    allows_dtc = req_bool(data, "allows_dtc")
    min_age = req_int(data, "min_age_years", min_v=0)
    abv_cap = req_int(data, "abv_cap_basis_points", min_v=0)
    surcharge = opt_int(data, "surcharge_cents_per_order", 0, min_v=0)
    tax_rate = req_int(data, "tax_rate_bps", min_v=0, max_v=5000)
    for rule in db["shipping_state_rules"].values():
        if rule["state_code"] == state_code:
            raise duplicate("state_code already exists")
    ent = new_entity({
        "state_code": state_code,
        "allows_dtc": allows_dtc,
        "min_age_years": min_age,
        "abv_cap_basis_points": abv_cap,
        "surcharge_cents_per_order": surcharge,
        "tax_rate_bps": tax_rate,
    })
    db["shipping_state_rules"][ent["id"]] = ent
    return success(public(ent), status=201)


@bp.get("/shipping-state-rules")
def list_rules():
    require(["PlatformAdmin", "ShopStaff", "ComplianceOfficer", "Member",
             "Anonymous"])
    limit, offset = pagination_params()
    allows = parse_bool_param("allows_dtc")
    items = list(db["shipping_state_rules"].values())
    if allows is not None:
        items = [r for r in items if r["allows_dtc"] == allows]
    page, pg = paginate(items, limit, offset)
    return success([public(r) for r in page], response_type="array",
                   pagination=pg)


@bp.get("/shipping-state-rules/<rid>")
def get_rule(rid):
    require(["PlatformAdmin", "ShopStaff", "ComplianceOfficer"])
    ent = get_or_404(db["shipping_state_rules"], rid)
    return success(public(ent))
