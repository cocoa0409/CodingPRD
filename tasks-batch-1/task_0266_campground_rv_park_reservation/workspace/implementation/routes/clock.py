"""Test-driving clock endpoint (PRD §3.10)."""
from datetime import datetime, timezone

from flask import Blueprint

from db import store
import errors
from middleware import get_principal, require_role, ROLE_OPERATOR
from response import success
from services import validate as V

bp = Blueprint("clock", __name__)


def _parse_utc(value):
    """Parse a current_utc string into an aware UTC datetime, or raise."""
    if not isinstance(value, str):
        raise errors.err(errors.ERR_CLOCK_INVALID, "current_utc must be a string")
    s = value.strip()
    candidate = s
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except (ValueError, TypeError):
        # Fall back to a plain date.
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_CLOCK_INVALID, "Unparseable current_utc")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    _, role = get_principal()
    require_role(role, {ROLE_OPERATOR})
    body = V.get_json_body()
    V.require_fields(body, ["current_utc"])
    dt = _parse_utc(body["current_utc"])
    store.clock = dt
    # ISO 8601 UTC echo with three fractional digits.
    echo = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return success({"current_utc": echo}, 200)
