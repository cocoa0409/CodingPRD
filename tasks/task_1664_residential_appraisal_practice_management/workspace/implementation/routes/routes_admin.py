"""POST /_clock/set_current_utc - the FirmAdmin logical-clock endpoint (PRD 2.4)."""

from flask import request

import webbase as base
import envelope
import services
from services import require_instant
from timeutil import clock, parse_instant


def register(app):
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_current_utc():
        base.auth.require_roles("FirmAdmin")
        body = base.read_body()
        services.require_fields(body, ["to_iso8601"])
        raw = require_instant(body, "to_iso8601")
        clock.set(parse_instant(raw), raw)
        # PRD 2.4: the response echoes the operator-supplied reading verbatim.
        return envelope.object_response({"current_utc": clock.raw})
