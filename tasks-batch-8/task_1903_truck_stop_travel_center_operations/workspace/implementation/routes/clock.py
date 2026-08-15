"""Logical clock test-driving endpoints (PRD 2.5)."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized, ALL_ROLES
from response import success_object
from util import CLOCK, is_valid_dt
from validate import get_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized(["GeneralManager"])
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not is_valid_dt(to_iso):
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 UTC datetime")
    CLOCK.set(to_iso)
    # Lazy derivations keyed off the clock recompute on next read/write; the
    # site retail mirrors are refreshed here so the new windows take effect.
    from db import db
    from services.core import recompute_site_mirrors
    for site in db["sites"].values():
        recompute_site_mirrors(site)
    return success_object({"current_utc": CLOCK.now_iso()})


@bp.get("/_clock")
def read_clock():
    authorized(ALL_ROLES)
    return success_object({"current_utc": CLOCK.now_iso()})
