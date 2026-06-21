from flask import Blueprint, request
import errors
from db import db
from middleware import require_auth
from response import success_object
from util import parse_iso
import validate as V

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth({"ProShop"})
    data = V.require_body(request.get_json(silent=True))
    to_iso = V.as_str(V.require_present(data, "to_iso8601"), "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except Exception:
        raise errors.validation("to_iso8601 must be ISO 8601.")
    db.current_utc = dt
    return success_object({}, 200)
