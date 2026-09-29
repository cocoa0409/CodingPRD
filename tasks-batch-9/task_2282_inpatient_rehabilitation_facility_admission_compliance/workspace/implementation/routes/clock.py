"""The server-held logical UTC clock (PRD §2.4, §3.2, §3.9)."""

from flask import Blueprint, request

from auth import authenticate
from db import store
from response import envelope
from services import run_clock_sweeps
from util import Body, iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(("ComplianceOfficer",))
    body = Body(request.get_json(silent=True))
    target = body.dt_field("to_iso8601")

    store.clock = target
    expired, missed = run_clock_sweeps()

    return envelope({
        "current_utc": iso(store.clock),
        "expired_screening_count": expired,
        "missed_assessment_count": missed,
    }, 200)
