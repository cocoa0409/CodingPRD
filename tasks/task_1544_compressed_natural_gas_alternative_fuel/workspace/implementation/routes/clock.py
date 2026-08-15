"""Logical clock endpoint."""
from __future__ import annotations

from flask import Blueprint

from db import CLOCK, isoformat
from middleware import get_caller, require_role
from response import success_object
from services.core import run_epoch_sweeps
from validators import body, require_fields, require_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    caller = get_caller()
    require_role(caller, ["NetworkOperator"])
    data = body()
    require_fields(data, ["to_iso8601"])
    target = require_datetime(data, "to_iso8601")
    CLOCK.set(target)
    sweeps = run_epoch_sweeps()
    return success_object({
        "current_utc": isoformat(CLOCK.now()),
        "sweeps_applied": sweeps,
    })
