"""The logical-clock capability (PRD §2.4)."""

from flask import Blueprint, request

import constants as K
import envelope
from clock import CLOCK, parse_instant
from context import Ctx

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    ctx = Ctx(request, [K.ROLE_PLATFORM_ADMIN])
    ctx.load_body()
    fields = ctx.validate([{"name": "to_iso8601", "type": "datetime", "required": True}])
    literal = fields["to_iso8601"]
    moment = parse_instant(literal)
    previous_literal = CLOCK.set(moment, literal)
    # Caller-supplied literals are echoed verbatim (see clock.py adjudication).
    # Moving the clock mutates no persisted row.
    return envelope.ok({"current_utc": literal, "previous_utc": previous_literal})
