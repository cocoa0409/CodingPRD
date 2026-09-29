"""The logical clock — the sole source of "now" for the whole system.

A fresh process starts at 2026-08-01T00:00:00Z and time only ever moves through
this endpoint. It is deliberately unauthenticated and ignores the caller's role.
"""
from flask import Blueprint

from envelope import object_response
from store import store
from util import iso
from validators import body, get_timestamp

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    data = body()
    moment = get_timestamp(data, "to_iso8601")
    store.clock = moment
    return object_response({"current_utc": iso(store.clock)})
