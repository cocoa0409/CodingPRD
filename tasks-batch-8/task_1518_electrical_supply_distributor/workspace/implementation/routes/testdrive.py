"""Test-driving endpoints (PRD §2.5): logical clock and commodity index."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import atomic, require_roles
from response import success_object
from util import (
    format_instant,
    get_json_body,
    is_valid_month,
    num,
    parse_instant,
    require_number,
    require_string,
)

bp = Blueprint("testdrive", __name__, url_prefix="/distributor")


@bp.post("/_clock/set_current_utc")
@require_roles("BranchManager")
@atomic
def set_current_utc():
    body = get_json_body()
    raw = require_string(body, "to_iso8601")
    instant = parse_instant(raw)
    if instant is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 instant")
    db.set_clock(instant)
    return success_object({"current_utc": format_instant(instant)})


@bp.post("/_index-readings/set")
@require_roles("BranchManager")
@atomic
def set_index_reading():
    body = get_json_body()
    month = require_string(body, "month")
    if not is_valid_month(month):
        raise_err(ERR_INVALID_REQUEST, "month must be a YYYY-MM year-month string")
    index_value = require_number(body, "index_value")
    # Upsert: month is unique; a repeated month replaces the stored value.
    db.index_readings[month] = index_value
    return success_object({"month": month, "index_value": num(index_value)})
