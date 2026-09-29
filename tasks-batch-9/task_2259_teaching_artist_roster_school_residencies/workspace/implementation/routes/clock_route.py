"""Logical-clock control (PRD 2.4). Mutates no entity and fires no cascade."""
from datetime import timezone

from flask import Blueprint, request

import clock
import middleware as mw
import response
from validators import Payload, bad, parse_iso_instant

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    mw.auth("ProgramDirector")
    body = Payload(request.get_json(silent=True))
    raw = body.string("to_iso8601", required=True)
    moment = parse_iso_instant(raw)
    if moment is None:
        bad("to_iso8601 must be an ISO 8601 instant")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    clock.set_logical(moment)
    return response.ok({})
