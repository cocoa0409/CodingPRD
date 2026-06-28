"""Logical-clock setter (PRD §2.4, §3.11). Open helper, manager-driven.

POST /_clock/set_current_utc { to_iso8601 } -> { now_utc }
Advancing the clock lazily expires packs whose expires_at has been reached.
"""
from flask import Blueprint

from clock import clock
from constants import ROLE_STUDIO_MANAGER
from middleware import require_auth, require_role
from response import success_object
from services import validate
from services import packs as pack_svc
from util import iso_z

bp = Blueprint("clock_route", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = require_auth()
    require_role(role, {ROLE_STUDIO_MANAGER})
    body = validate.get_body()
    to = validate.require_iso(body, "to_iso8601")
    clock.set(to)
    # Lazily expire packs whose expires_at <= now (PRD §2.4 side effect).
    pack_svc.expire_all_due()
    return success_object({"now_utc": iso_z(clock.now())}, 200)
