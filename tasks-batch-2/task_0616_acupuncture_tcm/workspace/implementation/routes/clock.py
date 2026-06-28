"""Logical clock route (PRD 2.4, SCAFFOLD §1.5).

POST /_clock/set_current_utc — ClinicAdmin only. Advances the server logical
clock to the supplied to_iso8601 instant and echoes back the new current_utc.
"""

from flask import Blueprint

from clock import clock
from common import get_json_body, parse_iso8601, require_string
from errors import err
from middleware import get_auth, require_role
from response import success

bp = Blueprint("clock", __name__)


def _to_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_auth()
    require_role(role, ["ClinicAdmin"])
    body = get_json_body()
    require_string(body, "to_iso8601")
    dt = parse_iso8601(body["to_iso8601"])
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.")
    clock.set(dt)
    return success({"current_utc": _to_iso(clock.now())}, status=200)
