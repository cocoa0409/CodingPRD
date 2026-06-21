"""Logical UTC clock test-driving capability (§2.9 / §3.11).

POST /_clock/set_current_utc — any of the three roles. Sets the logical clock
used for all subsequent time-gated comparisons. Returns no resource body
(empty object data, 200)."""

from flask import Blueprint

import db
import errors
import response
import util
from middleware import authenticate, require_role

bp = Blueprint("clock", __name__)

ALL_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        body = util.get_json_body()
        if "to_iso8601" not in body or body["to_iso8601"] is None:
            raise errors.invalid_request("Missing required field 'to_iso8601'.")
        val = body["to_iso8601"]
        if not isinstance(val, str):
            raise errors.invalid_request("'to_iso8601' must be an ISO 8601 string.")
        dt = util.parse_iso_string(val)
        if dt is None:
            raise errors.invalid_request("'to_iso8601' is not a valid ISO 8601 timestamp.")
        db.set_logical_clock(dt)
        return response.object_response({})
