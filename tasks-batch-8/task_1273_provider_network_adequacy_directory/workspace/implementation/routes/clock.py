"""POST /_clock/set_current_utc — logical clock with provider effectuation sweep."""

from flask import Blueprint

import db
import errors
import helpers
from middleware import require_roles
from response import success_object
from services.cascades import provider_effectuation_sweep

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("NetworkManager")
def set_clock(user_id, role):
    body = helpers.get_body()
    to_iso = helpers.req_str(body, "to_iso8601")
    new_clock = helpers.parse_iso_datetime(to_iso)
    db.clock_now = new_clock
    effectuated = provider_effectuation_sweep()
    return success_object({
        "current_utc": helpers.now_iso(),
        "effectuated_provider_ids": effectuated,
    })
