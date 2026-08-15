"""Logical clock endpoint (PRD §2.4). DistrictAdmin only."""

from flask import Blueprint

import serializers
from db import now_clock, fmt_dt, store
from middleware import auth_context, get_body, req_iso_dt, require_roles
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth = auth_context()
    require_roles(auth[1], ("DistrictAdmin",))
    body = get_body()
    instant = req_iso_dt(body, "to_iso8601")
    store.clock = instant
    return success_object({"current_utc": fmt_dt(now_clock())}, status=200)
