"""Theatre + Screen endpoints."""
from flask import Blueprint, request

from db import db
from middleware import require_roles
from response import success_object
from errors import err_invalid_request, err_invalid_state
from services.core import (
    serialize_theatre, serialize_screen,
    get_theatre, get_screen, get_distributor,
    new_entity_common, touch,
)
from ._helpers import get_json_body, require_fields, paginate_list

bp = Blueprint("theatres", __name__)


FORMATS = {"DCP_2K", "DCP_4K", "FILM_35MM"}


@bp.route("/distributors/<did>/theatres", methods=["POST"])
@require_roles("PlatformAdmin")
def create_theatre(did, _user_id, _role):
    get_distributor(did)
    body = get_json_body()
    require_fields(body, ["name", "circuit", "market_code", "house_allowance_cents"])
    if not isinstance(body["house_allowance_cents"], int):
        raise err_invalid_request("house_allowance_cents must be integer")
    common = new_entity_common()
    t = {
        **common,
        "distributor_id": did,
        "name": body["name"],
        "circuit": body["circuit"],
        "market_code": body["market_code"],
        "house_allowance_cents": body["house_allowance_cents"],
        "status": "ACTIVE",
    }
    db.theatres[t["id"]] = t
    return success_object(serialize_theatre(t), 201)


@bp.route("/distributors/<did>/theatres/<tid>", methods=["GET"])
@require_roles("Any")
def read_theatre(did, tid, _user_id, _role):
    return success_object(serialize_theatre(get_theatre(did, tid)))


@bp.route("/distributors/<did>/theatres", methods=["GET"])
@require_roles("Any")
def list_theatres(did, _user_id, _role):
    get_distributor(did)
    items = [t for t in db.theatres.values() if t["distributor_id"] == did]
    filters = {}
    for k in ("market_code", "circuit", "status", "distributor_id"):
        if k in request.args:
            filters[k] = request.args.get(k)
    return paginate_list(items, serialize_theatre, filters)


@bp.route("/distributors/<did>/theatres/<tid>/suspend", methods=["POST"])
@require_roles("PlatformAdmin")
def suspend_theatre(did, tid, _user_id, _role):
    t = get_theatre(did, tid)
    if t["status"] == "DARK":
        raise err_invalid_state("Theatre is DARK")
    t["status"] = "SUSPENDED"
    touch(t)
    return success_object(serialize_theatre(t))


@bp.route("/distributors/<did>/theatres/<tid>/screens", methods=["POST"])
@require_roles("PlatformAdmin")
def create_screen(did, tid, _user_id, _role):
    get_theatre(did, tid)
    body = get_json_body()
    require_fields(body, ["auditorium_label", "seat_count", "projection_format"])
    if body["projection_format"] not in FORMATS:
        raise err_invalid_request("projection_format must be DCP_2K|DCP_4K|FILM_35MM")
    if not isinstance(body["seat_count"], int):
        raise err_invalid_request("seat_count must be integer")
    common = new_entity_common()
    s = {
        **common,
        "theatre_id": tid,
        "auditorium_label": body["auditorium_label"],
        "seat_count": body["seat_count"],
        "projection_format": body["projection_format"],
        "status": "AVAILABLE",
    }
    db.screens[s["id"]] = s
    return success_object(serialize_screen(s), 201)


@bp.route("/distributors/<did>/theatres/<tid>/screens/<sid>", methods=["GET"])
@require_roles("Any")
def read_screen(did, tid, sid, _user_id, _role):
    return success_object(serialize_screen(get_screen(did, tid, sid)))


@bp.route("/distributors/<did>/theatres/<tid>/screens", methods=["GET"])
@require_roles("Any")
def list_screens(did, tid, _user_id, _role):
    get_theatre(did, tid)
    items = [s for s in db.screens.values() if s["theatre_id"] == tid]
    filters = {}
    if "status" in request.args:
        filters["status"] = request.args.get("status")
    return paginate_list(items, serialize_screen, filters)
