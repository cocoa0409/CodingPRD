"""Ops / test-driving routes: logical clock control + TTL expiry sweeps.

POST /_clock/set_current_utc is OPEN (no auth) per PRD §2.1.
"""
from datetime import timedelta

from flask import Blueprint

import constants as C
import db
import serialize
from common import parse_body, require_fields, parse_datetime, touch, now
from clock import clock
from errors import err, ERR_INVALID_REQUEST
from middleware import auth_and_role
from response import object_response, array_response

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    # Open endpoint: no auth.
    body = parse_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_datetime(body["to_iso8601"])
    if dt is None:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO8601 instant")
    clock.set(dt)
    return object_response({}, 200)


@bp.post("/_ops/expire-applications")
def expire_applications():
    auth_and_role(["Underwriter"])
    swept = []
    cutoff = timedelta(days=C.APPLICATION_TTL_DAYS)
    current = now()
    for a in db.applications.values():
        if a["status"] == "SUBMITTED" and (current - a["_updated_dt"]) >= cutoff:
            a["status"] = "EXPIRED"
            touch(a)
            swept.append(a)
    swept.sort(key=lambda a: a["_seq"])
    items = [serialize.application(a) for a in swept]
    return array_response(items, limit=len(items), offset=0, total_count=len(items))


@bp.post("/_ops/expire-renewals")
def expire_renewals():
    auth_and_role(["CreditOfficer"])
    swept = []
    cutoff = timedelta(days=C.RENEWAL_TTL_DAYS)
    current = now()
    for r in db.renewal_offers.values():
        if r["status"] == "OFFERED" and (current - r["_created_dt"]) >= cutoff:
            r["status"] = "EXPIRED"
            touch(r)
            swept.append(r)
    swept.sort(key=lambda r: r["_seq"])
    items = [serialize.renewal_offer(r) for r in swept]
    return array_response(items, limit=len(items), offset=0, total_count=len(items))
