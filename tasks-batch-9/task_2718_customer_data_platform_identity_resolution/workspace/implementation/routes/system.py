"""System capabilities: the logical clock and the retention run."""

from flask import Blueprint

import db
import middleware
import response
import validators
from services import retention

bp = Blueprint("system", __name__)


@bp.post("/cdp/_clock/set_current_utc")
def set_clock():
    middleware.require_role(*middleware.ALL_ROLES)
    body = validators.body_object()
    moment = validators.req_ts(body, "current_utc")
    db.set_now(moment)
    return response.object_response({"current_utc": body["current_utc"]})


@bp.post("/cdp/retention-runs")
def retention_run():
    middleware.require_role(middleware.ROLE_ADMIN)
    validators.body_object(required=False)
    return response.object_response(retention.run(), 201)
