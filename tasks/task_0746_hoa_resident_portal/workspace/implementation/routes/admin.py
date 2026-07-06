"""Test-driving endpoints: /_clock/set_current_utc and /_config/grace-policy."""

from flask import Blueprint, request

import db
from auth import require_role
from clock import set_now, sweep_time_transitions, get_now_iso
from errors import raise_error
from response import success
from services import homeowner as homeowner_svc
from utils import require_enum, require_fields, require_str, require_json

bp = Blueprint("admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_role("HOAManager")
def set_clock():
    body = require_json(request)
    require_fields(body, "to_iso8601")
    to_iso = require_str(body, "to_iso8601")
    set_now(to_iso)
    sweep_time_transitions()
    return success({"current_utc": db.current_utc_iso})


@bp.route("/_config/grace-policy", methods=["POST"])
@require_role("HOAManager")
def set_grace_policy():
    body = require_json(request)
    require_fields(body, "grace_policy")
    policy = require_enum(body, "grace_policy", {"STRICT", "LENIENT"})
    db.community_config["grace_policy"] = policy
    # Full recompute of every homeowner (and their properties).
    now_iso = get_now_iso()
    from services import property as property_svc
    from clock import get_now
    now_dt = get_now()
    for p in db.properties.values():
        property_svc.recompute(p, now_iso, now_dt=now_dt)
    homeowner_svc.recompute_all(now_iso)
    return success({"grace_policy": policy})
