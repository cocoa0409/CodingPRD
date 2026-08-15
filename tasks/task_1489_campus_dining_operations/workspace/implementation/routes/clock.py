"""Logical clock endpoint (PRD section 2.4)."""
from flask import Blueprint

from db import CLOCK
from middleware import auth
from response import ok
from services import run_sweeps
from util import as_iso_dt, body, parse_dt, required

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(["DiningAdmin"])
    data = body()
    to_iso8601 = as_iso_dt(required(data, "to_iso8601"), "to_iso8601")
    CLOCK["value"] = to_iso8601
    CLOCK["dt"] = parse_dt(to_iso8601)
    expired_contract_ids, overdue_ids = run_sweeps(CLOCK["dt"])
    return ok(
        {
            "current_utc": CLOCK["value"],
            "expired_contract_ids": expired_contract_ids,
            "overdue_corrective_action_ids": overdue_ids,
        }
    )
