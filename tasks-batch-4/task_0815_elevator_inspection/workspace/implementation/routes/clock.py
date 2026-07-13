from flask import Blueprint

from auth import require
from common import get_body, require_int
from envelope import object_response
from store import db

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set", methods=["POST"])
@require("Registrar", "SafetyAdministrator")
def set_clock():
    body = get_body()
    to_period = require_int(body, "to_period_index")
    db.current_period_index = to_period
    return object_response({}, 200)
