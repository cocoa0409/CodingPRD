"""League operations: the sweep checkpoint and the logical clock."""
from flask import Blueprint

import validation as V
from db import db, fmt_ts
from response import ok
from services import sweep

bp = Blueprint("ops", __name__)
clock_bp = Blueprint("clock", __name__)


@bp.post("/protocol-sweeps")
def run_protocol_sweep():
    V.authenticate(["LeagueAdmin"])
    return ok(sweep.run_sweep())


@clock_bp.post("/_clock/set_current_utc")
def set_current_utc():
    V.authenticate(["LeagueAdmin"])
    b = V.body()
    current_utc = V.req_dt(b, "current_utc")
    db.now = current_utc
    return ok({"current_utc": fmt_ts(db.now)})
