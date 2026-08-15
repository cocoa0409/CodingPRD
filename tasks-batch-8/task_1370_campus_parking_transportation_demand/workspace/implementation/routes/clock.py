"""Logical clock endpoint."""
from flask import Blueprint, request

import db
from errors import bad_request
from middleware import get_caller, require_roles
from response import success
from services.core import (
    serialize,
    touch,
    bump_allocation,
    extend_offers,
    parse_iso_datetime,
    logical_date,
)

bp = Blueprint("clock", __name__)


@bp.post("/parking/_clock/set_current_utc")
def set_clock():
    caller = get_caller()
    require_roles(caller, ["ParkingAdmin"])
    body = request.get_json(silent=True) or {}

    to_iso8601 = body.get("to_iso8601")
    new_time = parse_iso_datetime(to_iso8601, "to_iso8601")
    db.set_now(new_time)

    # Permit expiry sweep: ACTIVE permits whose valid_to is strictly before
    # the new logical date flip to EXPIRED.
    new_date = logical_date()
    freed_allocations = {}
    for permit in list(db.permits.values()):
        if permit["status"] != "ACTIVE":
            continue
        if permit["_valid_to"] < new_date:
            permit["status"] = "EXPIRED"
            touch(permit)
            alloc = db.allocations.get(permit["allocation_id"])
            if alloc is not None:
                alloc["allocated_count"] -= 1
                freed_allocations[alloc["id"]] = alloc
    for alloc in freed_allocations.values():
        bump_allocation(alloc)
    # Extend offers on freed seats (standard selector per allocation)
    for alloc in freed_allocations.values():
        extend_offers(alloc)

    return success({"current_utc": db.fmt_ts(db.now())}, 200)
