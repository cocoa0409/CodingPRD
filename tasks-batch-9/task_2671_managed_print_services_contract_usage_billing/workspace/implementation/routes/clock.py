"""Test-driving logical clock endpoint (PRD 2.5)."""
from flask import Blueprint

import validation as v
from auth import require
from envelope import ok
from store import db

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require("AccountManager", "BillingAnalyst", "FleetOpsController",
            "FieldTechnician", "CustomerAdmin")
    body = v.body()
    to_iso8601 = v.dt_field(body, "to_iso8601")
    db.clock = to_iso8601
    return ok({})
