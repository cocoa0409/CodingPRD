"""Test-driving clock + renewal-run endpoints (PRD §3.12, §4)."""
from flask import Blueprint

from db import db
from common import get_body, require_field, parse_datetime
from middleware import authenticate, require_roles
from response import success
from errors import err, ERR_INVALID_REQUEST
from services.renewal import run_renewal

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate()
    require_roles("CurationAdmin")
    body = get_body()
    to_iso = require_field(body, "to_iso8601")
    dt = parse_datetime(to_iso, "to_iso8601")
    db.set_clock(dt)
    return success({}, status=200)


@bp.post("/_renewal/run")
def renewal_run():
    authenticate()
    require_roles("CurationAdmin")
    body = get_body()
    target = body.get("subscription_id")
    charge_outcome = body.get("charge_outcome")
    if charge_outcome is not None and charge_outcome not in ("PAID", "FAILED"):
        raise err(ERR_INVALID_REQUEST, "charge_outcome must be PAID or FAILED.")
    run_renewal(target_subscription_id=target, charge_outcome=charge_outcome)
    return success({}, status=200)
