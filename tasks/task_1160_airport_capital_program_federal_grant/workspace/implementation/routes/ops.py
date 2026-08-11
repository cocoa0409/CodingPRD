"""Test-driving operational endpoints: logical clock + fiscal checkpoint."""
from flask import Blueprint

from auth import require
from domain import run_checkpoint
from store import DB
from util import as_str, body, need, parse_dt, respond

bp = Blueprint("ops", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require("FAAManager")
def set_clock():
    b = body()
    raw = as_str(need(b, "to_iso8601"), "to_iso8601")
    dt = parse_dt(raw, "to_iso8601")
    DB.clock = dt
    DB.clock_raw = raw
    return respond({"current_utc": raw}, 200)


@bp.route("/_ops/run_checkpoint", methods=["POST"])
@require("FAAManager")
def checkpoint():
    return respond(run_checkpoint(), 200)
