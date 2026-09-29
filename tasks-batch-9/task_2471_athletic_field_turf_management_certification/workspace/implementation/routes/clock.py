"""The logical clock (PRD 2.4). The only endpoint that moves time forward."""

import derive
import middleware
import response
import validate
from db import bump, by_creation, db
from errors import ApiError
from routes.blueprint import clock_bp


@clock_bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.authenticate(["FacilitiesDirector"])
    body = validate.Body(required=["to_iso8601"])
    target = body.instant("to_iso8601")

    # priority 31 - the logical clock never moves backwards
    if target.dt <= db.clock.dt:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC", 422,
                       "to_iso8601 must be strictly later than the current "
                       "logical clock value.")

    fields = by_creation(list(db.fields.values()))
    before = {f["id"]: derive.snapshot(f) for f in fields}

    db.clock = target

    recomputed = 0
    for field in fields:
        derive.recompute_field(field)
        # PRD 2.4: only the fields whose derived values actually changed are bumped
        if derive.snapshot(field) != before[field["id"]]:
            bump(field)
            recomputed += 1

    return response.ok({"current_utc": db.clock.raw,
                        "fields_recomputed": recomputed})
