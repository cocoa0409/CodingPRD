"""The settable logical clock (PRD section 2.5)."""

from flask import Blueprint

import db
import middleware as M
import response
import validators as V
from services import engine

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    M.authenticate(M.ANY_ROLE)
    body = M.json_body()
    current_utc = V.as_dt(body, "current_utc", required=True)
    if current_utc < db.db.clock:
        V.bad("current_utc may not move the logical clock backwards")
    expired, rejected, recomputed = engine.advance_clock(current_utc)
    return response.object_response({
        "current_utc": current_utc,
        "expired_permit_ids": expired,
        "rejected_acquisition_request_ids": rejected,
        "recomputed_exhibit_ids": recomputed,
    })
