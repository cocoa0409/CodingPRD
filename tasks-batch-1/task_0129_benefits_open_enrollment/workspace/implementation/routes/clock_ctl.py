"""Clock control endpoint (PRD §2.7, §3.1 / SCAFFOLD POST /_clock/advance).

Setting the clock to an absolute instant elapses every crossed WaitingPeriod and
re-evaluates owning-employee eligibility (bubble-up). BenefitsAdmin-only.
Returns 200 with an empty data object (output: null).
"""
from __future__ import annotations

from flask import Blueprint

import errors as E
from middleware import authenticate, authorize, BENEFITS_ADMIN
import response
from services import common as C
from services import domain as D

bp = Blueprint("clock_ctl", __name__)


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN})
    body = C.get_body()
    C.require_fields(body, ["to_iso8601"])
    to_iso = body.get("to_iso8601")
    dt = C.parse_iso(to_iso)
    D.advance_clock_and_reevaluate(dt)
    return response.ok_object({}, 200)
