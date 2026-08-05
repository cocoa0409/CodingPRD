"""The logical clock endpoint."""

from flask import Blueprint

import config
import ladder
from clock import clock

bp = Blueprint("system", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    def handler(ctx):
        return {"current_utc": clock.set(ctx.body["to_iso8601"])}

    return ladder.run(
        {
            "roles": [config.ROLE_PRACTICE_ADMIN],
            "shape": [("to_iso8601", "datetime", True)],
            "handler": handler,
            "status": 200,
        }
    )
