"""Logical clock control (Regulator only)."""

from flask import Blueprint

import errors
import serializers  # noqa: F401  (kept for symmetry)
from db import fmt_dt, store, sweep
from envelope import ok
from validators import as_dt, body, endpoint, req

bp = Blueprint("clock", __name__)


@bp.route("/hazmat/_clock/set_current_utc", methods=["POST"])
@endpoint(["Regulator"])
def set_clock(uid, role):
    b = body()
    target = as_dt(req(b, "to_iso8601"), "to_iso8601")
    store.clock = target
    sweep()
    return ok({"current_utc": fmt_dt(store.clock)}, 200)
