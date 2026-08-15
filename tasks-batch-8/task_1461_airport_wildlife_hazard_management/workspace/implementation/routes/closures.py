"""Runway closures: request, authorize, deny, release, cancel."""
from datetime import timedelta
from flask import Blueprint, request

import errors as E
from auth import authenticate, require_roles, acting_controller
from constants import RUNWAY_RE, CLOSURE_REASONS, CLOSURE_STATUSES, CLOSURE_MAX_DURATION_HOURS
from db import store
from services import closure_conflict, hazard_is_critical, recompute_airport
from util import (body, validate_payload, check_fk, get_or_404, list_response,
                  ok_object, new_entity, serialize, touch, now)

bp = Blueprint("closures", __name__, url_prefix="/wildlife")

READ_ROLES = ("WildlifeBiologist", "AirportAdmin", "ATCController", "RegulatorAgent")


def _get_closure(rid):
    return get_or_404(store.runway_closures, rid, "runway closure")


def _check_window_and_duration(c):
    if not c["closure_start"] < c["closure_end"]:
        raise E.ApiError(E.ERR_INVALID_WINDOW,
                         "closure_end must be strictly after closure_start", 422)


def _check_conflict(c):
    if closure_conflict(c["airport_id"], c["runway_designator"], c["closure_start"], c["closure_end"]):
        raise E.ApiError(E.ERR_CLOSURE_CONFLICT,
                         "requested closure overlaps an AUTHORIZED or ACTIVE closure on the same runway", 409)


def _check_duration(c):
    if c["closure_end"] - c["closure_start"] > timedelta(hours=CLOSURE_MAX_DURATION_HOURS):
        raise E.ApiError(E.ERR_CLOSURE_DURATION_EXCEEDED,
                         "closure duration exceeds 4 hours", 422)


def _check_cross_facility(c, uid):
    controller = acting_controller(uid)
    if controller is None or controller["airport_id"] != c["airport_id"]:
        raise E.ApiError(E.ERR_CROSS_FACILITY_FORBIDDEN,
                         "controller's airport does not match the closure's airport", 403)


@bp.post("/runway-closures")
def create_closure():
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    data = validate_payload(body(), [
        ("airport_id", "str", True),
        ("runway_designator", "pattern", True, {"regex": RUNWAY_RE}),
        ("requested_by_biologist_id", "str", True),
        ("closure_start", "datetime", True),
        ("closure_end", "datetime", True),
        ("reason", "enum", True, {"values": CLOSURE_REASONS}),
    ])
    check_fk("airport_id", data["airport_id"], store.airports, "airport")
    check_fk("requested_by_biologist_id", data["requested_by_biologist_id"], store.biologists, "biologist")
    _check_window_and_duration(data)      # priority 9
    _check_conflict(data)                 # priority 10
    _check_duration(data)                 # priority 15
    rec = new_entity(store.runway_closures, {
        "airport_id": data["airport_id"],
        "runway_designator": data["runway_designator"],
        "requested_by_biologist_id": data["requested_by_biologist_id"],
        "authorized_by_controller_id": None,
        "closure_start": data["closure_start"],
        "closure_end": data["closure_end"],
        "actual_released_at": None,
        "status": "REQUESTED",
        "reason": data["reason"],
    })
    return ok_object(serialize(rec), 201)


@bp.get("/runway-closures")
def list_closures():
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    args = request.args
    status = args.get("status")
    if status is not None and status not in CLOSURE_STATUSES:
        raise E.invalid_enum("status", status)
    rows = [c for c in store.runway_closures.values()
            if (args.get("airport_id") is None or c["airport_id"] == args.get("airport_id"))
            and (args.get("runway_designator") is None or c["runway_designator"] == args.get("runway_designator"))
            and (status is None or c["status"] == status)
            and (args.get("requested_by_biologist_id") is None or c["requested_by_biologist_id"] == args.get("requested_by_biologist_id"))
            and (args.get("authorized_by_controller_id") is None or c.get("authorized_by_controller_id") == args.get("authorized_by_controller_id"))]
    return list_response(rows)


@bp.get("/runway-closures/<rid>")
def get_closure(rid):
    uid, role = authenticate()
    require_roles(role, READ_ROLES)
    return ok_object(serialize(_get_closure(rid)))


@bp.post("/runway-closures/<rid>/authorize")
def authorize_closure(rid):
    uid, role = authenticate()
    require_roles(role, ("ATCController",))
    c = _get_closure(rid)
    if c["status"] != "REQUESTED":
        raise E.invalid_state("runway closure must be in REQUESTED to authorize")
    _check_conflict(c)                    # priority 10
    _check_cross_facility(c, uid)         # priority 19
    c["status"] = "AUTHORIZED"
    c["authorized_by_controller_id"] = uid
    touch(c)
    return ok_object(serialize(c))


@bp.post("/runway-closures/<rid>/deny")
def deny_closure(rid):
    uid, role = authenticate()
    require_roles(role, ("ATCController",))
    c = _get_closure(rid)
    if c["status"] != "REQUESTED":
        raise E.invalid_state("runway closure must be in REQUESTED to deny")
    _check_cross_facility(c, uid)         # priority 19
    c["status"] = "DENIED"
    touch(c)
    return ok_object(serialize(c))


@bp.post("/runway-closures/<rid>/release")
def release_closure(rid):
    uid, role = authenticate()
    require_roles(role, ("ATCController",))
    c = _get_closure(rid)
    if c["status"] != "ACTIVE":
        raise E.invalid_state("runway closure must be in ACTIVE to release")
    if hazard_is_critical(c["airport_id"]):
        raise E.ApiError(E.ERR_HAZARD_CRITICAL_BLOCK,
                         "airport is at CRITICAL hazard level; releasing the runway is blocked", 409)
    _check_cross_facility(c, uid)         # priority 19
    c["status"] = "RELEASED"
    c["actual_released_at"] = now()
    touch(c)
    ap = store.airports.get(c["airport_id"])
    if ap:
        recompute_airport(ap)
    return ok_object(serialize(c))


@bp.post("/runway-closures/<rid>/cancel")
def cancel_closure(rid):
    uid, role = authenticate()
    require_roles(role, ("WildlifeBiologist",))
    c = _get_closure(rid)
    if c["status"] != "REQUESTED":
        raise E.invalid_state("runway closure must be in REQUESTED to cancel")
    if uid != c["requested_by_biologist_id"]:
        raise E.ApiError(E.ERR_UNAUTHORIZED,
                         "only the requesting biologist may cancel this closure", 403)
    c["status"] = "CANCELLED"
    touch(c)
    return ok_object(serialize(c))
