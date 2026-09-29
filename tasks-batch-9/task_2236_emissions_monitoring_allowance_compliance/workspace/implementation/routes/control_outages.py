"""Control equipment outage windows (PRD 3.1). Intervals are half-open
``[start_utc, end_utc)`` and overlap is scoped per control device.
"""

from flask import Blueprint

from constants import (
    API_PREFIX,
    DEFAULT_MAX_CONCURRENT_OUTAGES,
    OUTAGE_ACTIONS,
    OUTAGE_DEVICES,
    OUTAGE_STATUSES,
    OUTAGE_TYPES,
    ROLE_FACILITY_OPERATOR,
)
from db import base_record, db, public, public_list, sort_rows, touch
from errors import fail
from lookup import facility_of_unit, find, get, outages_of_unit, units_of_facility
from middleware import ANY_ROLE, authenticate, enforce_facility_scope
from response import array_response, object_response
from validation import (
    apply_pagination,
    body_dict,
    dt_field,
    enum_field,
    match_filters,
    pagination,
    query_filters,
    str_field,
)

bp = Blueprint("control_outages", __name__)

BLOCKING_STATUSES = ("PLANNED", "ACTIVE")


@bp.route(API_PREFIX + "/units/<unit_id>/control-outages", methods=["POST"])
def plan_outage(unit_id):
    caller = authenticate((ROLE_FACILITY_OPERATOR,))
    body = body_dict()
    enforce_facility_scope(caller, facility_of_unit(find("unit", unit_id)))

    start_raw, start = dt_field(body, "start_utc", required=True)
    end_raw, end = dt_field(body, "end_utc", required=True)
    outage_type = enum_field(body, "outage_type", OUTAGE_TYPES, required=True)
    control_device = enum_field(body, "control_device", OUTAGE_DEVICES, required=True)

    unit = get("unit", unit_id)

    if unit["control_device"] != control_device:
        fail("ERR_INVALID_REQUEST", "control_device must equal the unit's own control device.")

    if start >= end:
        fail("ERR_INVALID_INTERVAL", "end_utc must be strictly later than start_utc.")

    for other in outages_of_unit(unit["id"]):
        if other["control_device"] != control_device:
            continue
        if other["status"] not in BLOCKING_STATUSES:
            continue
        if start < other["_end"] and other["_start"] < end:
            fail(
                "ERR_CONTROL_OUTAGE_OVERLAP",
                "Another live window already covers part of this interval for the device.",
            )

    outage = base_record()
    outage.update(
        {
            "unit_id": unit["id"],
            "start_utc": start_raw,
            "end_utc": end_raw,
            "outage_type": outage_type,
            "control_device": control_device,
            "status": "PLANNED",
            "activated_utc": None,
            "closed_utc": None,
            "cancellation_reason": None,
            "_start": start,
            "_end": end,
        }
    )
    db.control_outages[outage["id"]] = outage
    return object_response(public(outage), 201)


@bp.route(API_PREFIX + "/control-outages", methods=["GET"])
def list_outages():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {
            "unit_id": "str",
            "status": OUTAGE_STATUSES,
            "outage_type": OUTAGE_TYPES,
            "control_device": OUTAGE_DEVICES,
        }
    )
    limit, offset = pagination()
    rows = match_filters(list(db.control_outages.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/control-outages/<outage_id>", methods=["GET"])
def read_outage(outage_id):
    authenticate(ANY_ROLE)
    return object_response(public(get("control_outage", outage_id)))


@bp.route(API_PREFIX + "/control-outages/<outage_id>/transition", methods=["POST"])
def transition_outage(outage_id):
    caller = authenticate((ROLE_FACILITY_OPERATOR,))
    body = body_dict()

    outage = find("control_outage", outage_id)
    unit = db.units.get(outage["unit_id"]) if outage else None
    enforce_facility_scope(caller, facility_of_unit(unit))

    action = enum_field(body, "action", OUTAGE_ACTIONS, required=True)
    reason = str_field(body, "reason")

    outage = get("control_outage", outage_id)
    unit = get("unit", outage["unit_id"])

    if action == "ACTIVATE":
        if outage["status"] != "PLANNED":
            fail("ERR_INVALID_STATE_TRANSITION", "Only a PLANNED window may be activated.")
        if unit["dispatch_state"] not in ("OFFLINE", "RESERVE_SHUTDOWN"):
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "The unit must be OFFLINE or RESERVE_SHUTDOWN to take its control device out.",
            )
        facility = facility_of_unit(unit)
        ceiling = DEFAULT_MAX_CONCURRENT_OUTAGES
        if facility is not None:
            ceiling = facility["max_concurrent_control_outages"]
            unit_ids = {u["id"] for u in units_of_facility(facility["id"])}
        else:
            unit_ids = {unit["id"]}
        active = [
            o for o in db.control_outages.values()
            if o["unit_id"] in unit_ids and o["status"] == "ACTIVE"
        ]
        if len(active) + 1 > ceiling:
            fail(
                "ERR_CONCURRENT_OUTAGE_LIMIT",
                "The facility already carries its maximum of concurrent active outages.",
            )
        outage["status"] = "ACTIVE"
        outage["activated_utc"] = db.now_str()
        touch(outage)
        unit["control_status"] = "OUT_OF_SERVICE"
        touch(unit)

    elif action == "CLOSE":
        if outage["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE window may be closed.")
        outage["status"] = "CLOSED"
        outage["closed_utc"] = db.now_str()
        touch(outage)
        still_active = [
            o for o in outages_of_unit(unit["id"])
            if o["id"] != outage["id"] and o["status"] == "ACTIVE"
        ]
        if not still_active:
            unit["control_status"] = "AVAILABLE"
        touch(unit)

    else:  # CANCEL
        if outage["status"] != "PLANNED":
            fail("ERR_INVALID_STATE_TRANSITION", "Only a PLANNED window may be cancelled.")
        if reason is None or not reason.strip():
            fail("ERR_REASON_REQUIRED", "reason is required to cancel a window.")
        outage["status"] = "CANCELLED"
        outage["cancellation_reason"] = reason
        touch(outage)

    return object_response(public(outage))
