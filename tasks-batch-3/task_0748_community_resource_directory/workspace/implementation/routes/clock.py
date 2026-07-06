from flask import request

from middleware import require_roles
from response import success
from services import advance_clock
from util import fmt_ts, parse_ts
from validate import require_body, require_str


def register(app):
    @app.post("/_clock/set_current_utc")
    @require_roles("PlatformAdmin")
    def set_clock():
        body = require_body(request.get_json(silent=True))
        to_iso = require_str(body, "to_iso8601")
        new_clock = parse_ts(to_iso)
        advance_clock(new_clock)
        return success({"current_utc": fmt_ts(new_clock)}, 200)
