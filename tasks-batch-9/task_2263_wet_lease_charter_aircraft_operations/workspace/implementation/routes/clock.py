"""The server-held logical UTC clock (PRD 2.4)."""

from flask import Blueprint

from db import db
from middleware import (
    require, LESSOR_OPS, BILLING_ADMIN, MAINTENANCE_CONTROLLER,
    INSURANCE_UNDERWRITER, REGULATORY_AUTHORITY,
)
from response import object_response
from services import workflows as W
import validate as V

bp = Blueprint("clock", __name__)

CLOCK_ROLES = (
    LESSOR_OPS, BILLING_ADMIN, MAINTENANCE_CONTROLLER,
    INSURANCE_UNDERWRITER, REGULATORY_AUTHORITY,
)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require(CLOCK_ROLES)
    body = V.json_body()
    _raw, current_utc = V.req_datetime(body, "current_utc")

    db.clock = current_utc
    W.apply_clock_effects()
    return object_response({})
