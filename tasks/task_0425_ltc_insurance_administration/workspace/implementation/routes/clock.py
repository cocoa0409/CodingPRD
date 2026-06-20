"""Deterministic system clock endpoints (PRD §3.10)."""
from flask import Blueprint

from db import STORE
from middleware import authenticate, authorize
from response import object_response
from services import common, core

bp = Blueprint("clock", __name__)


@bp.route("/_clock/advance_to", methods=["POST"])
def advance_clock():
    caller = authenticate()
    authorize(caller, ["Underwriter"])
    body = common.get_json_body()
    to_iso = common.require_str(body, "to_iso8601")
    core.advance_clock(to_iso)
    return object_response({}, 200)


@bp.route("/_clock", methods=["GET"])
def read_clock():
    caller = authenticate()
    authorize(caller, ["Underwriter", "ClaimsExaminer", "Regulator", "Policyholder", "CareAssessor"])
    return object_response({"now_iso8601": STORE.clock_iso}, 200)
