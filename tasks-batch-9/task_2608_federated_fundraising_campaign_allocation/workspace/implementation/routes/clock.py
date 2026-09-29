"""Out-of-band logical clock control (PRD 2.7, 4)."""

from datetime import datetime

from flask import Blueprint

from auth import authenticate
from envelope import ok
from store import iso, now, set_clock
from validators import bad, body, get_str

from services import aggregates

bp = Blueprint("clock", __name__)


def _parse_instant(raw):
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad("Field 'to_iso8601' must be a valid ISO 8601 instant.")
    if parsed.tzinfo is not None:
        offset = parsed.utcoffset()
        parsed = parsed.replace(tzinfo=None)
        if offset:
            parsed = parsed - offset
    return parsed


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(("UnitedFundAdmin",))
    data = body()
    raw = get_str(data, "to_iso8601", min_len=1)
    set_clock(_parse_instant(raw))
    aggregates.recompute_all_agency_delinquency()
    return ok({"current_utc": iso(now())})
