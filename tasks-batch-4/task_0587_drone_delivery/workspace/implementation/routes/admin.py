"""Simulator endpoints: the logical clock and the LAANC authority (PRD 2.4, 3.5)."""
from flask import Blueprint

import serializers
import validation as v
from auth import require
from db import db, get_or_404, touch
from errors import err
from response import ok
from timeutil import compact14

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
@require("PlatformAdmin")
def set_clock():
    body = v.body()
    target = v.as_datetime(body, "to_iso8601")
    db.set_clock(target)
    return ok({})


@bp.post("/_laanc/decision")
@require("PlatformAdmin")
def laanc_decision():
    body = v.body()
    authorization_id = v.as_string(body, "authorization_id")
    outcome = v.as_enum(body, "outcome", ("APPROVED", "DENIED"))

    auth = get_or_404("AirspaceAuthorization", authorization_id)
    if auth["status"] != "PENDING":
        raise err("ERR_AUTHORIZATION_NOT_PENDING")

    if outcome == "APPROVED":
        auth["status"] = "APPROVED"
        auth["auth_code"] = "LAANC-" + compact14(auth["created_at"])
    else:
        auth["status"] = "DENIED"
        auth["auth_code"] = None
    touch(auth)
    return ok(serializers.authorization(auth))
