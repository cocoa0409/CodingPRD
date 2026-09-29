"""Administrative logical-clock capability (PRD 2.4)."""

import re
from datetime import datetime, timezone

from flask import Blueprint

import validators as v
from db import db
from errors import fail
from middleware import ALL_ROLES, endpoint
from response import ok

bp = Blueprint("clock", __name__)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def _parse(value):
    match = _ISO_RE.match(value)
    if match is None:
        fail("ERR_INVALID_REQUEST", "Field 'current_utc' must be an ISO 8601 instant.")
    year, month, day, hour, minute, second, fraction, offset = match.groups()
    micro = 0
    if fraction:
        micro = int(round(float(fraction) * 1000000))
    try:
        moment = datetime(int(year), int(month), int(day), int(hour), int(minute),
                          int(second or 0), micro, tzinfo=timezone.utc)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field 'current_utc' is not a valid instant.")
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        digits = offset[1:].replace(":", "")
        delta_minutes = sign * (int(digits[0:2]) * 60 + int(digits[2:4]))
        moment = moment.fromtimestamp(moment.timestamp() - delta_minutes * 60,
                                     tz=timezone.utc)
    return moment


@bp.post("/_clock/set_current_utc")
@endpoint(*ALL_ROLES)
def set_current_utc():
    data = v.body()
    raw = v.get_string(data, "current_utc", min_len=1)
    db.clock = _parse(raw)
    db.clock_raw = raw
    return ok({"current_utc": raw})
