"""Lessor + logical-clock endpoints — PRD §3.1, §2.8, §4."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_roles, ALL_ROLES
from response import object_response
from services.common import (
    get_json_body, require_string, require_nonneg_int, require_fields,
    parse_iso8601, to_iso,
)
from services import domain

bp = Blueprint("lessors", __name__)


@bp.post("/lessors")
def create_lessor():
    user_id, role = get_user_context()
    require_roles(role, ["FundingOfficer"])
    body = get_json_body()
    legal_name = require_string(body, "legal_name")
    home_state_code = require_string(body, "home_state_code")
    sales_tax_rate_bps = require_nonneg_int(body, "sales_tax_rate_bps")
    property_tax_rate_bps = require_nonneg_int(body, "property_tax_rate_bps")
    with db.LOCK:
        rec = db.init_record({
            "legal_name": legal_name,
            "home_state_code": home_state_code,
            "sales_tax_rate_bps": sales_tax_rate_bps,
            "property_tax_rate_bps": property_tax_rate_bps,
            "portfolio_value_cents": 0,
            # Logical clock initialized at lessor creation (PRD §2.8).
            "clock_utc": db.now_ts(),
        })
        db.lessors[rec["id"]] = rec
        return object_response(domain.serialize_lessor(rec), 201)


@bp.get("/lessors/<lessor_id>")
def get_lessor(lessor_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        rec = domain.get_lessor_or_404(lessor_id)
        return object_response(domain.serialize_lessor(rec), 200)


@bp.post("/lessors/<lessor_id>/_clock/set")
def set_clock(lessor_id):
    user_id, role = get_user_context()
    require_roles(role, ["FundingOfficer", "Servicer"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        body = get_json_body()
        require_fields(body, ["to_iso8601"])
        target = parse_iso8601(body["to_iso8601"])
        lessor["clock_utc"] = to_iso(target)
        db.touch(lessor)
        # UCC lapse and equipment depreciation are derived from clock_utc at read
        # time (PRD §3.7/§3.8), so no eager state mutation is needed here.
        return object_response(domain.serialize_lessor(lessor), 200)
