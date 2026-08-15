"""Logical clock test-driving endpoint."""

from flask import Blueprint
import db
import validators as V
from middleware import require_roles
from response import success_object
from errors import raise_err, ERR_INVALID_REQUEST

bp = Blueprint("clock", __name__)


@bp.route("/science-fair/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    body = V.get_json_body()
    V.require_fields(body, ["to_iso8601"])
    to_iso8601 = V.req_str(body, "to_iso8601")

    require_roles("FairDirector")

    # Validate parseable ISO 8601
    try:
        db.parse_iso(to_iso8601)
    except Exception:
        raise_err(ERR_INVALID_REQUEST,
                  "to_iso8601 must be a valid ISO 8601 timestamp")

    db.clock_set_iso(to_iso8601)
    return success_object({"current_utc": db.clock_now_iso()})
