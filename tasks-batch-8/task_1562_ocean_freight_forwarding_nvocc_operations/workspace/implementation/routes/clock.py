"""Logical clock endpoint (PRD section 2.5)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from services import domain
from util import require_ts

bp = Blueprint("clock", __name__)


@bp.route("/freight/_clock/set_current_utc", methods=["POST"])
@require_roles("OperationsManager")
def set_current_utc(_user_id: str, _role: str):
    from util import get_json_body

    body = get_json_body()
    target = require_ts(body, "to_iso8601")
    if target < db.clock():
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be >= current logical time (monotonic)")
    db.set_clock(target)
    # Clock advance triggers lazy expiry evaluation for bonds and contracts.
    domain.lazy_expire_all()
    return success_object({}, 200)
