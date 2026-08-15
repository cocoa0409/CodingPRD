"""Logical clock administration (PRD §2.4)."""
from flask import Blueprint

from db import set_clock, now_iso
from middleware import get_auth, require_roles
from response import success_object
from services.core import get_body, req_dt, sweep_overdue

bp = Blueprint("clock", __name__)


@bp.post("/safety/_clock/set_current_utc")
def set_current_utc():
    auth = get_auth()
    require_roles(auth, ("PlatformAdmin",))
    data = get_body()
    target = req_dt(data, "to_iso8601")
    set_clock(target)
    # Every clock repositioning triggers the compliance sweep.
    sweep_overdue()
    return success_object({"current_utc": now_iso()})
