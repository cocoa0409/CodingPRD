"""Boutique CRUD + the deterministic store clock (PRD §3.1, §2.4)."""
from flask import Blueprint

import errors
from db import db, stamp_new, touch
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import success, list_success
from services.common import (
    get_or_404, require_str, require_int, parse_pagination, paginate,
    serialize, serialize_list,
)
from services.holds import sweep_expired_holds

bp = Blueprint("boutiques", __name__)


@bp.post("/boutiques")
def create_boutique():
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    body = get_json_body()

    name = require_str(body, "name")
    state_code = require_str(body, "state_code")
    if len(state_code) != 2 or not state_code.isupper():
        raise err(errors.ERR_INVALID_REQUEST, "state_code must be 2-letter uppercase")
    tax_rate_bps = require_int(body, "tax_rate_bps")
    if tax_rate_bps < 0 or tax_rate_bps > 2000:
        raise err(errors.ERR_INVALID_REQUEST, "tax_rate_bps must be in [0,2000]")
    return_window_days = require_int(body, "return_window_days", required=False, default=30)
    if return_window_days < 0:
        raise err(errors.ERR_INVALID_REQUEST, "return_window_days must be >= 0")

    rec = stamp_new({
        "name": name,
        "state_code": state_code,
        "tax_rate_bps": tax_rate_bps,
        "current_business_date": 0,
        "return_window_days": return_window_days,
        "store_credit_outstanding_cents": 0,
    })
    db.boutiques[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/boutiques/<rid>")
def get_boutique(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "Merchandiser", "StoreAssociate"})
    rec = get_or_404("boutique", rid)
    return success(serialize(rec))


@bp.get("/boutiques")
def list_boutiques():
    _, role = authenticate()
    require_role(role, {"StoreManager", "Merchandiser", "StoreAssociate"})
    limit, offset = parse_pagination()
    window, total = paginate(list(db.boutiques.values()), limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.post("/_clock/advance")
def advance_clock():
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    body = get_json_body()

    boutique_id = require_str(body, "boutique_id")
    to_business_date = require_int(body, "to_business_date")
    to_minute = require_int(body, "to_minute", required=False, default=None)

    boutique = get_or_404("boutique", boutique_id)
    boutique["current_business_date"] = to_business_date
    touch(boutique)

    sweep_expired_holds(boutique_id, to_business_date, to_minute)
    return success(serialize(boutique))
