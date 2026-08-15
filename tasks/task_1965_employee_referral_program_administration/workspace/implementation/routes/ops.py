"""Test-driving / ops endpoints: logical clock and the operations sweep."""

from flask import Blueprint, request

from db import store
from middleware import require_role
from services import run_sweep
from util import req_dt, respond_object, iso

bp = Blueprint("ops", __name__)


@bp.post("/erp/_clock/set_current_utc")
def set_clock():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    to = req_dt(body, "to_iso8601")
    store.clock = to
    return respond_object({"now_iso8601": iso(store.clock)})


@bp.post("/erp/_ops/evaluate")
def evaluate():
    require_role("TalentAdmin")
    tallies = run_sweep()
    return respond_object(tallies)
