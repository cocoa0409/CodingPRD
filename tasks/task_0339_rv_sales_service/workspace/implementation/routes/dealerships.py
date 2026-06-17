"""Dealership routes + deterministic clock (PRD 3.1, 2.4)."""

from flask import Blueprint

import db
from common import (DOC_FEE_CAP_CENTS, body, new_entity, touch, require_str,
                    require_int, paginate, get_or_404, parse_iso)
from middleware import get_auth, require_role
from response import ok, created, ok_list

bp = Blueprint("dealerships", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_auth()
    require_role(role, {"DealerManager"})
    data = body()
    did = data.get("dealership_id")
    dealership = get_or_404("dealerships", did)
    if "to_iso8601" not in data:
        from common import invalid
        invalid("to_iso8601 is required.")
    parse_iso(data.get("to_iso8601"), "to_iso8601")
    dealership["current_utc"] = data["to_iso8601"]
    touch(dealership)
    return ok(dealership)


@bp.post("/dealerships")
def create_dealership():
    _, role = get_auth()
    require_role(role, {"DealerManager"})
    data = body()
    name = require_str(data, "name")
    state_code = require_str(data, "state_code")
    doc_fee = require_int(data, "doc_fee_cents", minimum=0)
    tax_rate = require_int(data, "sales_tax_rate_bps", minimum=0)
    if doc_fee > DOC_FEE_CAP_CENTS:
        from errors import err
        err("ERR_DOC_FEE_OVER_CAP", "doc_fee_cents exceeds the documentation-fee cap.")
    rec = new_entity({
        "name": name,
        "state_code": state_code,
        "doc_fee_cents": doc_fee,
        "sales_tax_rate_bps": tax_rate,
        "current_utc": "1970-01-01T00:00:00.000Z",
    })
    db.store["dealerships"][rec["id"]] = rec
    return created(rec)


@bp.get("/dealerships")
def list_dealerships():
    _, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor"})
    page, limit, offset, total = paginate(list(db.store["dealerships"].values()))
    return ok_list(page, limit, offset, total)


@bp.get("/dealerships/<dealership_id>")
def get_dealership(dealership_id):
    user_id, role = get_auth()
    require_role(role, {"DealerManager", "SalesAgent", "ServiceAdvisor", "Customer"})
    rec = get_or_404("dealerships", dealership_id)
    return ok(rec)
