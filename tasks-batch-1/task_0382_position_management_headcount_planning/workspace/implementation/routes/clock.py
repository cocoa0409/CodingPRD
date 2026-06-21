"""Test-driving clock endpoint (PRD §3.5, §4)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import require_auth
from response import success
from services.common import get_body
from services.cascade import snapshot_postures, recompute_all_postures
from util import parse_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_auth(["FinanceController"])
    body = get_body()
    to_iso = body.get("to_iso8601")
    if to_iso is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is required")
    dt = parse_datetime(to_iso)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is malformed")

    # Capture posture before the clock moves, advance the clock, then recompute
    # every cost center's posture and fire freeze/un-freeze cascades for windows
    # that just opened or closed (PRD §3.5).
    prev = snapshot_postures()
    db.current_utc = dt
    recompute_all_postures(prev)
    return success({})
