"""Aircraft routes (onboard, list, get, retire)."""

from flask import Blueprint, request

import errors
from db import db, new_common, public, sorted_by_created, touch
from errors import err
from middleware import (as_number, as_str, get_body, get_user_context,
                        parse_pagination, require_fields, require_role)
from response import list_success, success
from services.common import find_or_404

bp = Blueprint("aircraft", __name__)


@bp.post("/flight-school/aircraft")
def create_aircraft():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin"})
    body = get_body()
    require_fields(body, ["tail_number", "model", "rental_rate_cents_per_hour",
                          "billing_basis", "initial_hobbs", "initial_tach"])
    tail_number = as_str(body, "tail_number")
    model = as_str(body, "model")
    rate = body["rental_rate_cents_per_hour"]
    if isinstance(rate, bool) or not isinstance(rate, int) or rate <= 0:
        raise err(errors.ERR_INVALID_REQUEST, "rental_rate_cents_per_hour must be a positive integer.")
    billing_basis = body["billing_basis"]
    if billing_basis not in ("HOBBS", "TACH"):
        raise err(errors.ERR_INVALID_REQUEST, "billing_basis must be HOBBS or TACH.")
    initial_hobbs = as_number(body, "initial_hobbs")
    initial_tach = as_number(body, "initial_tach")
    is_complex = body.get("is_complex", False)
    if not isinstance(is_complex, bool):
        raise err(errors.ERR_INVALID_REQUEST, "is_complex must be a boolean.")

    record = new_common()
    record.update({
        "tail_number": tail_number,
        "model": model,
        "is_complex": is_complex,
        "rental_rate_cents_per_hour": rate,
        "billing_basis": billing_basis,
        "current_hobbs": initial_hobbs,
        "current_tach": initial_tach,
        "initial_hobbs": initial_hobbs,
        "initial_tach": initial_tach,
        "open_squawk_count": 0,
        "status": "AVAILABLE",
    })
    db.aircraft[record["id"]] = record
    return success(public(record), status=201)


@bp.get("/flight-school/aircraft")
def list_aircraft():
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor", "Mechanic"})
    limit, offset = parse_pagination()
    items = list(db.aircraft.values())
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sorted_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return list_success([public(a) for a in page], limit, offset, total)


@bp.get("/flight-school/aircraft/<aircraft_id>")
def get_aircraft(aircraft_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin", "Dispatcher", "Student", "Instructor", "Mechanic"})
    record = find_or_404(db.aircraft, aircraft_id)
    return success(public(record))


@bp.post("/flight-school/aircraft/<aircraft_id>/retire")
def retire_aircraft(aircraft_id):
    _, role = get_user_context()
    require_role(role, {"SchoolAdmin"})
    aircraft = find_or_404(db.aircraft, aircraft_id)
    # State: only AVAILABLE may be retired.
    if aircraft["status"] != "AVAILABLE":
        raise err(errors.ERR_AIRCRAFT_NOT_AVAILABLE,
                  "Aircraft must be AVAILABLE to retire.")
    # No active bookings.
    has_active = any(
        b["aircraft_id"] == aircraft_id
        and b["status"] in ("REQUESTED", "CONFIRMED", "DISPATCHED")
        for b in db.bookings.values()
    )
    if has_active:
        raise err(errors.ERR_AIRCRAFT_HAS_ACTIVE_BOOKINGS,
                  "Aircraft has active bookings and cannot be retired.")
    aircraft["status"] = "RETIRED"
    touch(aircraft)
    return success(public(aircraft))
