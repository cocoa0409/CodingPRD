from flask import Blueprint

from db import store, fmt_dt, parse_dt
from helpers import sweep_exchange_defaults
from middleware import get_json_body, require_roles, validate_body
from response import ok

bp = Blueprint("clock", __name__, url_prefix="/mro")


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("ShopManager")
def set_current_utc():
    body = validate_body(get_json_body(), {"to_iso8601": ("datetime", True)})
    store.clock = parse_dt(body["to_iso8601"])
    defaulted = sweep_exchange_defaults()
    return ok(
        {
            "current_utc": fmt_dt(store.clock),
            "defaulted_exchange_agreement_ids": defaulted,
        }
    )
