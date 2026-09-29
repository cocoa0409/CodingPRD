"""Operational endpoints: logical clock control and the risk epoch run (PRD §2.5, §3.9)."""

from flask import Blueprint

import clock
import config as C
import envelope
import services
import validators
from auth import authenticate

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(C.ROLE_SYSTEM_OPERATOR)
    payload = validators.body()
    instant = validators.req_instant(payload, "current_utc")
    clock.set_now(instant)
    return envelope.success({"current_utc": clock.iso(instant)})


@bp.post("/_ops/risk-run")
def risk_run():
    authenticate(C.ROLE_SYSTEM_OPERATOR)
    return envelope.success(services.risk_run())
