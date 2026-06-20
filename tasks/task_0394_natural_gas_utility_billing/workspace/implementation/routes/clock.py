"""Clock and test-driving injection endpoints (PRD §2.8)."""

from flask import Blueprint

from db import store
from middleware import authenticate, require_role
from response import success
from services.common import get_body, optional_int, parse_dt, to_iso
from services.serialize import view_clock, view_account
from services import lookup

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    principal = authenticate()
    require_role(principal, {"BillingAdmin"})
    body = get_body()
    with store.lock:
        if "current_utc" in body and body["current_utc"] is not None:
            dt = parse_dt(body["current_utc"])
            store.clock["current_utc"] = to_iso(dt)
        if "heating_season_active" in body and body["heating_season_active"] is not None:
            val = body["heating_season_active"]
            if not isinstance(val, bool):
                from errors import ERR_INVALID_REQUEST, err
                raise err(ERR_INVALID_REQUEST, "heating_season_active must be a boolean")
            store.clock["heating_season_active"] = val
        return success(view_clock(store.clock), 200)


@bp.route("/_clock", methods=["GET"])
def get_clock():
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "FieldTech"})
    return success(view_clock(store.clock), 200)


@bp.route("/_inject/account-ontime-count", methods=["POST"])
def inject_ontime_count():
    principal = authenticate()
    require_role(principal, {"BillingAdmin"})
    body = get_body()
    from services.common import require_fields, require_string, require_int
    require_fields(body, ["account_id", "count"])
    account_id = require_string(body, "account_id")
    count = require_int(body, "count", minimum=0)
    with store.lock:
        account = lookup.get_account(account_id)
        account["consecutive_ontime_payments"] = count
        return success(view_account(account), 200)
