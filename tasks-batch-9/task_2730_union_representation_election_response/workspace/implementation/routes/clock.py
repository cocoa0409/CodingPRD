"""The administrative logical-clock capability, mounted outside /labor-relations."""

from flask import Blueprint

import auth
import clockutil
import envelope
import validate

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@auth.endpoint(auth.ALL_ROLES)
def set_current_utc(user_id, role):
    schema = validate.Schema(validate.body())
    current_utc = schema.datetime("current_utc")
    clockutil.CLOCK.set(clockutil.parse_dt(current_utc))
    return envelope.empty_response()
