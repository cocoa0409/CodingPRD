"""Security endpoints (PRD §3.2, §4)."""
from flask import Blueprint

import errors
from db import db
from middleware import get_identity, require_role
from models import make_security, security_dict
from response import object_response
from routes.common import get_json_body, get_security
from services.account import recompute_positions_for_account_via_security

bp = Blueprint("securities", __name__)


@bp.post("/securities")
def register_security():
    _, role = get_identity()
    require_role(role, {"ClearingSystem", "ComplianceOfficer"})
    body = get_json_body()

    symbol = body.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise errors.err(errors.ERR_INVALID_REQUEST, "symbol is required")

    instrument_type = body.get("instrument_type")
    if instrument_type not in ("EQUITY", "OPTION"):
        raise errors.err(errors.ERR_INVALID_REQUEST, "instrument_type must be EQUITY or OPTION")

    last_price = body.get("last_price_cents")
    if not isinstance(last_price, int) or isinstance(last_price, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "last_price_cents must be an integer")

    fractional_enabled = body.get("fractional_enabled", True)
    if not isinstance(fractional_enabled, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "fractional_enabled must be a boolean")

    maintenance_rate_bps = body.get("maintenance_rate_bps", 2500)
    if not isinstance(maintenance_rate_bps, int) or isinstance(maintenance_rate_bps, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "maintenance_rate_bps must be an integer")

    required_options_level = body.get("required_options_level", 0)
    if (not isinstance(required_options_level, int) or isinstance(required_options_level, bool)
            or required_options_level not in (0, 1, 2, 3)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "required_options_level must be 0..3")

    extended_hours_eligible = body.get("extended_hours_eligible", True)
    if not isinstance(extended_hours_eligible, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "extended_hours_eligible must be a boolean")

    sec = make_security(symbol, instrument_type, last_price, fractional_enabled,
                        maintenance_rate_bps, required_options_level, extended_hours_eligible)
    return object_response(security_dict(sec), 201)


@bp.patch("/securities/<security_id>/quote")
def push_quote(security_id):
    _, role = get_identity()
    require_role(role, {"MarketData", "ClearingSystem"})
    sec = get_security(security_id)
    body = get_json_body()

    last_price = body.get("last_price_cents")
    if not isinstance(last_price, int) or isinstance(last_price, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "last_price_cents must be an integer")

    sec["last_price_cents"] = last_price
    # Quote update revalues every position on this security and recomputes the
    # owning accounts' equity/maintenance/buying_power/posture (PRD §3.2).
    recompute_positions_for_account_via_security(security_id)
    return object_response(security_dict(sec), 200)
