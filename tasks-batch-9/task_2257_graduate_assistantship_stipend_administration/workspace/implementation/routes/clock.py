"""Administrative logical-clock repositioning.  Mutates no entity."""
from datetime import datetime, timezone

from flask import Blueprint

import validate as v
from db import set_clock, now_iso
from middleware import authenticate
from response import ok

bp = Blueprint("clock", __name__)


def _parse_instant(raw):
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise v.invalid("Field 'to_iso8601' must be an ISO 8601 timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(["GradSchoolAdmin"])
    body = v.body_dict()
    raw = v.field_str(body, "to_iso8601")
    set_clock(_parse_instant(raw))
    return ok({"current_utc": now_iso()})
