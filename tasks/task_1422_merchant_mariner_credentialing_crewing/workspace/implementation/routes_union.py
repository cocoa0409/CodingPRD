"""Union halls and registrations (PRD 3.7 union side)."""

from flask import Blueprint, request

from db import store
from errors import err
from helpers import (
    get_body,
    paginate,
    req_dt,
    req_str,
    require_roles,
    scope_dispatcher_hall,
    scope_mariner_id,
    sorted_items,
)
from response import success
from serialize import ser_union_hall, ser_union_registration

bp = Blueprint("union", __name__)

ALL_ROLES = (
    "FleetAdmin",
    "CrewingManager",
    "CredentialingOfficer",
    "PortCaptain",
    "UnionDispatcher",
    "Mariner",
)


def _get_hall(hall_id):
    h = store.union_halls.get(hall_id)
    if h is None:
        raise err("ERR_UNION_HALL_NOT_FOUND", "Union hall %s not found" % hall_id)
    return h


def _get_registration_under_hall(hall_id, registration_id):
    r = store.union_registrations.get(registration_id)
    if r is None or r["hall_id"] != hall_id:
        raise err(
            "ERR_UNION_REGISTRATION_NOT_FOUND",
            "Union registration %s not found" % registration_id,
        )
    return r


@bp.route("/union-halls", methods=["POST"])
@require_roles("FleetAdmin")
def create_hall():
    body = get_body()
    local_number = req_str(body, "local_number")
    name = req_str(body, "name")
    region = req_str(body, "region")
    if any(h["local_number"] == local_number for h in store.union_halls.values()):
        raise err(
            "ERR_INVALID_REQUEST", "local_number %s already exists" % local_number
        )
    h = {"local_number": local_number, "name": name, "region": region}
    store.stamp(h)
    store.union_halls[h["id"]] = h
    return success(ser_union_hall(h), code=201)


@bp.route("/union-halls", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_halls():
    items = sorted_items(store.union_halls.values())
    page, meta = paginate(items)
    return success(
        [ser_union_hall(h) for h in page], response_type="array", pagination=meta
    )


@bp.route("/union-halls/<hall_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_hall(hall_id):
    return success(ser_union_hall(_get_hall(hall_id)))


@bp.route("/union-halls/<hall_id>/registrations", methods=["POST"])
@require_roles("UnionDispatcher", "FleetAdmin")
def create_registration(hall_id):
    scope_dispatcher_hall(hall_id)
    hall = _get_hall(hall_id)
    body = get_body()
    mariner_id = body.get("mariner_id")
    if not isinstance(mariner_id, str) or mariner_id == "":
        raise err("ERR_INVALID_REQUEST", "Field 'mariner_id' is required")
    m = store.mariners.get(mariner_id)
    if m is None:
        raise err("ERR_MARINER_NOT_FOUND", "Mariner %s not found" % mariner_id)
    seniority = req_dt(body, "seniority_date")
    card = req_str(body, "shipping_card_number")
    # Channel rule (pipeline step 12): only UNION_HALL mariners register.
    if m["hire_channel"] != "UNION_HALL":
        raise err(
            "ERR_CHANNEL_NOT_PERMITTED",
            "Only UNION_HALL mariners can register with a hall",
        )
    if any(
        r["hall_id"] == hall["id"]
        and r["mariner_id"] == m["id"]
        and r["status"] != "SUSPENDED"
        for r in store.union_registrations.values()
    ):
        raise err(
            "ERR_DUPLICATE_REGISTRATION",
            "A non-SUSPENDED registration already exists for this hall and mariner",
        )
    r = {
        "hall_id": hall["id"],
        "mariner_id": m["id"],
        "seniority_date": seniority,
        "shipping_card_number": card,
        "dues_current_until": seniority,
        "status": "REGISTERED",
    }
    store.stamp(r)
    store.union_registrations[r["id"]] = r
    return success(ser_union_registration(r), code=201)


@bp.route("/union-halls/<hall_id>/registrations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_hall_registrations(hall_id):
    hall = _get_hall(hall_id)
    items = [
        r for r in store.union_registrations.values() if r["hall_id"] == hall["id"]
    ]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_union_registration(r) for r in page],
        response_type="array",
        pagination=meta,
    )


@bp.route("/mariners/<mariner_id>/union-registrations", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_mariner_registrations(mariner_id):
    scope_mariner_id(mariner_id)
    if mariner_id not in store.mariners:
        raise err("ERR_MARINER_NOT_FOUND", "Mariner %s not found" % mariner_id)
    items = [
        r for r in store.union_registrations.values() if r["mariner_id"] == mariner_id
    ]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate(sorted_items(items))
    return success(
        [ser_union_registration(r) for r in page],
        response_type="array",
        pagination=meta,
    )


@bp.route(
    "/union-halls/<hall_id>/registrations/<registration_id>/extend-dues",
    methods=["POST"],
)
@require_roles("UnionDispatcher")
def extend_dues(hall_id, registration_id):
    scope_dispatcher_hall(hall_id)
    _get_hall(hall_id)
    r = _get_registration_under_hall(hall_id, registration_id)
    body = get_body()
    new_until = req_dt(body, "new_dues_current_until")
    if r["dues_current_until"] is not None and not new_until > r["dues_current_until"]:
        raise err(
            "ERR_INVALID_REQUEST",
            "new_dues_current_until must be strictly later than the current value",
        )
    if r["status"] != "REGISTERED":
        raise err(
            "ERR_INVALID_STATE",
            "Dues can only be extended while the registration is REGISTERED",
        )
    r["dues_current_until"] = new_until
    store.bump(r)
    return success(ser_union_registration(r))


@bp.route(
    "/union-halls/<hall_id>/registrations/<registration_id>/suspend", methods=["POST"]
)
@require_roles("UnionDispatcher", "FleetAdmin")
def suspend_registration(hall_id, registration_id):
    scope_dispatcher_hall(hall_id)
    _get_hall(hall_id)
    r = _get_registration_under_hall(hall_id, registration_id)
    if r["status"] != "REGISTERED":
        raise err(
            "ERR_INVALID_STATE", "Only a REGISTERED registration can be suspended"
        )
    r["status"] = "SUSPENDED"
    store.bump(r)
    return success(ser_union_registration(r))


@bp.route(
    "/union-halls/<hall_id>/registrations/<registration_id>/reinstate",
    methods=["POST"],
)
@require_roles("UnionDispatcher", "FleetAdmin")
def reinstate_registration(hall_id, registration_id):
    scope_dispatcher_hall(hall_id)
    _get_hall(hall_id)
    r = _get_registration_under_hall(hall_id, registration_id)
    if r["status"] != "SUSPENDED":
        raise err(
            "ERR_INVALID_STATE", "Only a SUSPENDED registration can be reinstated"
        )
    r["status"] = "REGISTERED"
    store.bump(r)
    return success(ser_union_registration(r))
