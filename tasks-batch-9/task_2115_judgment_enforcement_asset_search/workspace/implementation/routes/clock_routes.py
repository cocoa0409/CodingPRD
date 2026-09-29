"""POST /_clock/set_current_utc - the logical clock and the docket sweep."""

from auth import ALL_STAFF
from domain import run_sweep
from errors import ApiError
from store import store
from validators import json_body, parse_instant, require_string
from web import endpoint


def register(app):
    @endpoint(app, "/_clock/set_current_utc", "POST", ALL_STAFF, 200)
    def set_current_utc(ctx):
        body = json_body()
        raw = require_string(body, "to_iso8601")
        target = parse_instant(raw)
        if target is None:
            raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 UTC instant.")
        # rung 11 - the clock may only move forward or stay where it is
        if target < store.clock:
            raise ApiError("ERR_CLOCK_REGRESSION", "The logical clock may not move backwards.")
        store.clock = target
        store.clock_raw = raw
        counts = run_sweep(target)
        data = {"current_utc": raw}
        data.update(counts)
        return data
