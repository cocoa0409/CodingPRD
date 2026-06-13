"""Reservation endpoints (PRD §3.7, §2.9 OCC)."""

from flask import Blueprint, request

import clock
import db
import errors
import response
from middleware import (
    authenticate, require_roles, require_owner_if_patron,
    ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER,
)
from services import serialize, derive, reservation as res_svc
from routes import helpers
from timeutil import parse

bp = Blueprint("reservations", __name__)

RESERVATION_STATUSES = {
    "REQUESTED", "CONFIRMED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED",
}


def _branch_for_patron(patron):
    return db.branches.get(patron["branch_id"])


@bp.post("/library/reservations")
def create_reservation():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN})
    body = helpers.get_json_body()

    helpers.require_fields(
        body, ["resource_id", "patron_id", "start_at", "end_at", "expected_resource_version"]
    )
    resource_id = helpers.require_string(body, "resource_id")
    patron_id = helpers.require_string(body, "patron_id")
    expected_version = helpers.required_int(body, "expected_resource_version")

    # existence (priority 3), left-to-right: resource then patron
    resource = helpers.find_or_404(db.resources, resource_id)
    patron = helpers.find_or_404(db.patrons, patron_id)

    # ownership (priority 2): a Patron may only book for themselves
    require_owner_if_patron(caller, patron_id)

    # request well-formedness (priority 4): valid datetimes, end_at > start_at
    try:
        start_at = parse(body["start_at"])
        end_at = parse(body["end_at"])
    except (ValueError, TypeError):
        raise errors.invalid_request("start_at/end_at must be ISO 8601 datetimes.")
    if not (end_at > start_at):
        raise errors.invalid_request("end_at must be strictly after start_at.")

    # priority 6: resource IN_SERVICE
    if resource["status"] != "IN_SERVICE":
        raise errors.ApiError(errors.ERR_RESOURCE_NOT_AVAILABLE, 409, "Resource is OUT_OF_SERVICE.")

    # priority 7: card ACTIVE
    if patron["card_status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_CARD_NOT_ACTIVE, 409, "Patron card is not ACTIVE.")

    # priority 8: patron CLEAR
    derive.reconcile_patron(patron)
    if patron["borrowing_status"] == "BLOCKED":
        raise errors.ApiError(errors.ERR_PATRON_BLOCKED, 409, "Patron is BLOCKED.")

    # priority 9: interval conflict
    branch = _branch_for_patron(patron)
    buffer_minutes = branch["reservation_buffer_minutes"] if branch else 0
    if res_svc.has_conflict(resource, start_at, end_at, buffer_minutes):
        raise errors.ApiError(errors.ERR_RESERVATION_CONFLICT, 409, "Reservation interval conflicts.")

    # priority 12: OCC on resource.version
    if expected_version != resource["version"]:
        raise errors.ApiError(
            errors.ERR_STALE_RESOURCE_VERSION, 412,
            "expected_resource_version does not match the resource version.",
        )

    record = {
        "resource_id": resource_id,
        "patron_id": patron_id,
        "status": "REQUESTED",
        "start_at": start_at,
        "end_at": end_at,
        "checked_in_at": None,
    }
    db.stamp_create(record)
    db.reservations[record["id"]] = record

    # successful create advances resource.version by one (OCC advance)
    db.touch(resource)

    return response.object_response(serialize.reservation(record), status=201)


@bp.get("/library/reservations/<rid>")
def get_reservation(rid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.reservations, rid)
    return response.object_response(serialize.reservation(record))


@bp.get("/library/reservations")
def list_reservations():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    resource_id = request.args.get("resource_id")
    patron_id = request.args.get("patron_id")
    status = helpers.enum_filter("status", RESERVATION_STATUSES)
    records = [
        r for r in db.reservations.values()
        if (resource_id is None or r["resource_id"] == resource_id)
        and (patron_id is None or r["patron_id"] == patron_id)
        and (status is None or r["status"] == status)
    ]
    return helpers.list_response(records, serialize.reservation)


def _resource_for(reservation):
    return db.resources.get(reservation["resource_id"])


@bp.post("/library/reservations/<rid>/confirm")
def confirm(rid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN})
    res = helpers.find_or_404(db.reservations, rid)

    # state (priority 5)
    if res["status"] != "REQUESTED":
        raise errors.invalid_state("Reservation is not REQUESTED.")

    # priority 6: resource must be IN_SERVICE
    resource = _resource_for(res)
    if resource is None or resource["status"] != "IN_SERVICE":
        raise errors.ApiError(errors.ERR_RESOURCE_NOT_AVAILABLE, 409, "Resource is OUT_OF_SERVICE.")

    res["status"] = "CONFIRMED"
    db.touch(res)
    return response.object_response(serialize.reservation(res))


@bp.post("/library/reservations/<rid>/checkin")
def checkin(rid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN})
    res = helpers.find_or_404(db.reservations, rid)

    # state (priority 5)
    if res["status"] != "CONFIRMED":
        raise errors.invalid_state("Reservation is not CONFIRMED.")

    # priority 6: resource IN_SERVICE
    resource = _resource_for(res)
    if resource is None or resource["status"] != "IN_SERVICE":
        raise errors.ApiError(errors.ERR_RESOURCE_NOT_AVAILABLE, 409, "Resource is OUT_OF_SERVICE.")

    now = clock.now()
    if now < res["start_at"]:
        raise errors.ApiError(errors.ERR_NOT_YET_DUE, 409, "Reservation has not started yet.")

    res["status"] = "CHECKED_IN"
    res["checked_in_at"] = now
    db.touch(res)
    return response.object_response(serialize.reservation(res))


@bp.post("/library/reservations/<rid>/complete")
def complete(rid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN})
    res = helpers.find_or_404(db.reservations, rid)
    if res["status"] != "CHECKED_IN":
        raise errors.invalid_state("Reservation is not CHECKED_IN.")
    res["status"] = "COMPLETED"
    db.touch(res)
    return response.object_response(serialize.reservation(res))


@bp.post("/library/reservations/<rid>/no-show")
def no_show(rid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN})
    res = helpers.find_or_404(db.reservations, rid)

    if res["status"] != "CONFIRMED":
        raise errors.invalid_state("Reservation is not CONFIRMED.")

    now = clock.now()
    if now < res["end_at"]:
        raise errors.ApiError(errors.ERR_NOT_YET_DUE, 409, "Reservation window has not ended yet.")

    res["status"] = "NO_SHOW"
    db.touch(res)
    return response.object_response(serialize.reservation(res))


@bp.post("/library/reservations/<rid>/cancel")
def cancel(rid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN})
    res = helpers.find_or_404(db.reservations, rid)

    # ownership (priority 2)
    require_owner_if_patron(caller, res["patron_id"])

    if res["status"] not in ("REQUESTED", "CONFIRMED"):
        raise errors.invalid_state("Reservation is not REQUESTED or CONFIRMED.")

    res["status"] = "CANCELLED"
    db.touch(res)
    return response.object_response(serialize.reservation(res))
