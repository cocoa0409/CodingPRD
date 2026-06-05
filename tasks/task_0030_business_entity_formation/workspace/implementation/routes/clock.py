"""Clock routes — set the server's current UTC for time-gated tests."""
from __future__ import annotations

from flask import Blueprint

import db
import errors
import middleware
import response
from routes._helpers import parse_json_body_required
from services import core

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    # PRD §2.1: "the clock-advance endpoint ... still requires a role from
    # StateAdmin or ComplianceOfficer but is exempted from the entity-ownership
    # check". SCAFFOLD §1.4 priority 10 also exempts this endpoint from
    # ERR_UNAUTHENTICATED. Practically we still validate role-set membership:
    # any caller presenting an unrecognized role gets 401; a recognized role
    # not in the endpoint's allowed list gets 403; absent headers also 401
    # because the role test cannot pass without one.
    middleware.require_auth(["StateAdmin", "ComplianceOfficer"])
    body = parse_json_body_required()
    iso = body.get("to_iso8601")
    if not isinstance(iso, str):
        raise errors.err_invalid_request("to_iso8601 must be a string.")
    try:
        db.set_clock(iso)
    except ValueError as e:
        raise errors.err_invalid_request(str(e))

    # Re-evaluate time-gated transitions
    core.reevaluate_time_gated_transitions()

    snapshot = {
        "current_utc": db.iso_format(db.now_utc()),
    }
    return response.success_object(snapshot)
