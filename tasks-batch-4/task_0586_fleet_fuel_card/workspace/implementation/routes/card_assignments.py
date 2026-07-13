"""Card assignments: card x vehicle x driver junction (PRD §3.3)."""
from datetime import datetime, timezone

from flask import Blueprint, g, request

import response
from db import base_record, db, touch
from errors import err
from middleware import (body, check_fleet, is_fleet_manager, paginate, query_enum, req_int,
                        req_str, require_roles)
from services import serialize
from services.cascade import end_assignment
from services.store import (ASSIGNMENT_STATUSES, account_of_assignment, get_assignment, get_card,
                            get_driver, get_vehicle)
from util import parse_dt

bp = Blueprint("card_assignments", __name__)

OPEN_ENDED = datetime.max.replace(tzinfo=timezone.utc)


def _dt_field(data, field, required):
    raw = data.get(field)
    if raw is None:
        if required:
            raise err("ERR_VALIDATION", "Field '%s' is required." % field)
        return None, None
    if not isinstance(raw, str):
        raise err("ERR_VALIDATION", "Field '%s' must be an ISO 8601 datetime string." % field)
    try:
        return raw, parse_dt(raw)
    except ValueError:
        raise err("ERR_VALIDATION", "Field '%s' must be an ISO 8601 datetime string." % field)


def _end_or_open(assignment):
    return assignment["_effective_to_dt"] or OPEN_ENDED


@bp.post("/card-assignments")
@require_roles("FleetManager")
def create_assignment():
    data = body()
    card_id = req_str(data, "card_id")
    vehicle_id = req_str(data, "vehicle_id")
    driver_id = req_str(data, "driver_id")
    effective_from_raw, effective_from = _dt_field(data, "effective_from", True)
    expected_card_version = req_int(data, "expected_card_version")
    effective_to_raw, effective_to = _dt_field(data, "effective_to", False)

    # 3. Existence, left to right.
    card = get_card(card_id)
    vehicle = get_vehicle(vehicle_id)
    driver = get_driver(driver_id)

    # 4. Fleet ownership.
    check_fleet(card["fleet_account_id"])
    check_fleet(vehicle["fleet_account_id"])
    check_fleet(driver["fleet_account_id"])

    # 6. Vehicle operational status.
    if vehicle["status"] != "ACTIVE":
        raise err("ERR_VEHICLE_OUT_OF_SERVICE", "Assignment requires an ACTIVE vehicle.")

    # 11. Interval well-formedness.
    if effective_to is not None and not (effective_from < effective_to):
        raise err("ERR_INVALID_INTERVAL",
                  "'effective_from' must be strictly earlier than 'effective_to'.")

    # 12. Driver double-booking — half-open intervals; touching endpoints do not overlap.
    new_end = effective_to or OPEN_ENDED
    for other in db.card_assignments.values():
        if other["driver_id"] != driver_id or other["status"] != "ACTIVE":
            continue
        if effective_from < _end_or_open(other) and other["_effective_from_dt"] < new_end:
            raise err("ERR_DRIVER_DOUBLE_BOOKED",
                      "Driver already has an ACTIVE assignment overlapping this interval.")

    # 18. Optimistic concurrency on the card's version.
    if expected_card_version != card["version"]:
        raise err("ERR_STALE_CARD_VERSION")

    record = base_record()
    record.update({
        "card_id": card_id,
        "vehicle_id": vehicle_id,
        "driver_id": driver_id,
        "effective_from": effective_from_raw,
        "effective_to": effective_to_raw,
        "status": "ACTIVE",
        "_effective_from_dt": effective_from,
        "_effective_to_dt": effective_to,
    })

    # Side effects: supersede the card's prior ACTIVE assignment, bump the card.
    for other in list(db.card_assignments.values()):
        if other["card_id"] == card_id and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)

    db.card_assignments[record["id"]] = record
    touch(card)
    return response.created(serialize.card_assignment(record))


@bp.get("/card-assignments/<assignment_id>")
@require_roles("FleetManager", "ProgramAdmin")
def fetch_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    check_fleet(account_of_assignment(assignment))
    return response.ok(serialize.card_assignment(assignment))


@bp.get("/card-assignments")
@require_roles("FleetManager", "ProgramAdmin")
def list_assignments():
    card_filter = request.args.get("card_id")
    vehicle_filter = request.args.get("vehicle_id")
    driver_filter = request.args.get("driver_id")
    status_filter = query_enum("status", ASSIGNMENT_STATUSES)

    records = list(db.card_assignments.values())
    if is_fleet_manager():
        records = [a for a in records if account_of_assignment(a) == g.user_id]
    if card_filter is not None:
        records = [a for a in records if a["card_id"] == card_filter]
    if vehicle_filter is not None:
        records = [a for a in records if a["vehicle_id"] == vehicle_filter]
    if driver_filter is not None:
        records = [a for a in records if a["driver_id"] == driver_filter]
    if status_filter is not None:
        records = [a for a in records if a["status"] == status_filter]

    page, total, limit, offset = paginate(records)
    return response.listing([serialize.card_assignment(a) for a in page], limit, offset, total)


@bp.post("/card-assignments/<assignment_id>/end")
@require_roles("FleetManager")
def end(assignment_id):
    assignment = get_assignment(assignment_id)
    check_fleet(account_of_assignment(assignment))
    if assignment["status"] != "ACTIVE":
        raise err("ERR_INVALID_CARD_STATE", "Only an ACTIVE assignment can be ended.")
    end_assignment(assignment)
    return response.ok(serialize.card_assignment(assignment))
