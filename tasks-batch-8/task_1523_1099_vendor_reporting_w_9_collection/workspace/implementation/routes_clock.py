from errors import ApiError
from middleware import guard
from response import success_envelope
from utils import json_body, reject_unknown, parse_dt
from db import set_clock, logical_now, fmt_ts


def register(app):
    @app.post("/tax1099/_clock/set_current_utc")
    @guard({"TaxAdmin"})
    def set_current_utc():
        b = json_body()
        reject_unknown(b, {"to_iso8601"})
        if "to_iso8601" not in b:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field 'to_iso8601'")
        dt = parse_dt(b["to_iso8601"], "to_iso8601")
        set_clock(dt)
        return success_envelope({"current_utc": fmt_ts(logical_now())})
