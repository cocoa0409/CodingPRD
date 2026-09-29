"""Logical clock control (PRD 2.4). Every role may drive the clock."""

from flask import Blueprint

from auth import require
from constants import ANY_ROLE
from envelope import ok
from store import fmt_iso, store
from validation import field_datetime, get_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require(*ANY_ROLE)
def set_current_utc():
    body = get_body()
    _, target = field_datetime(body, "to_iso8601")
    store.set_clock(target)
    return ok({"current_utc": fmt_iso(store.now())})
