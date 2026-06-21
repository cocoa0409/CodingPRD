"""Test-driving logical clock endpoint (PRD 3.10)."""

from flask import Blueprint

import errors
from common import get_body, as_str
from db import store, parse_iso
from middleware import require_roles
from response import object_response

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set", methods=["POST"])
@require_roles("CaseWorker", "FinanceOfficer")
def set_clock(auth):
    body = get_body()
    to_iso = as_str(body, "to_iso8601")
    dt = parse_iso(to_iso)
    if dt is None:
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 timestamp")
    store.clock.set(dt)
    # output: null per the endpoint table -> empty data object.
    return object_response({}, 200)
