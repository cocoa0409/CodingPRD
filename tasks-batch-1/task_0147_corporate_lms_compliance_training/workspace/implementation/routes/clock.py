"""Deterministic logical clock endpoints (PRD §2.5)."""

from flask import Blueprint

import errors
import serializers as ser
from db import db, fmt_ts
from middleware import authenticate, require_roles, ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER
from response import object_response
from services.common import require_body, req_field, check_str
from timeutil import parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set", methods=["POST"])
def set_clock():
    p = authenticate(require_user_id=False)
    require_roles(p, [ROLE_ADMIN])
    body = require_body()
    current_utc = check_str(req_field(body, "current_utc"), "current_utc")
    try:
        dt = parse_iso(current_utc)
    except (ValueError, TypeError):
        raise errors.invalid_request("current_utc must be ISO 8601")
    db.clock["current_utc"] = fmt_ts(dt)
    db.clock["version"] = db.clock.get("version", 1) + 1
    db.clock["updated_at"] = db.clock["current_utc"]
    return object_response(ser.clock(db.clock))


@bp.route("/_clock", methods=["GET"])
def get_clock():
    p = authenticate(require_user_id=False)
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    return object_response(ser.clock(db.clock))
