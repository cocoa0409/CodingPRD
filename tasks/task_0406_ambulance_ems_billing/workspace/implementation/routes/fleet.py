"""Vehicle + CrewMember endpoints (PRD §3.1, §2.9)."""

from flask import Blueprint

from db import store
from errors import ERR_INVALID_ENUM, err
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_json_body,
    get_or_404,
    init_common,
    paginate,
    parse_pagination,
    require_fields,
    resolve_fk,
    touch,
)
from services.serialize import serialize, serialize_list

bp = Blueprint("fleet", __name__)

CERTIFICATIONS = {"EMT", "AEMT", "PARAMEDIC"}


# ---- Vehicle ----
@bp.route("/vehicles", methods=["POST"])
def create_vehicle():
    principal = authenticate()
    require_role(principal, ["BillingAdmin"])
    body = get_json_body()
    if body.get("agency_id") is not None:
        resolve_fk(store.agencies, body["agency_id"])
    require_fields(body, ["agency_id", "unit_call_sign"])
    rec = {
        "agency_id": body["agency_id"],
        "unit_call_sign": body["unit_call_sign"],
        "turnaround_minutes": (
            body["turnaround_minutes"] if body.get("turnaround_minutes") is not None else 30
        ),
        "status": "IN_SERVICE",
    }
    init_common(rec)
    store.vehicles[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle(vehicle_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Dispatcher"])
    rec = get_or_404(store.vehicles, vehicle_id)
    return success(serialize(rec), 200)


@bp.route("/vehicles/<vehicle_id>/out-of-service", methods=["POST"])
def vehicle_out_of_service(vehicle_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin"])
    rec = get_or_404(store.vehicles, vehicle_id)
    rec["status"] = "OUT_OF_SERVICE"
    touch(rec)
    return success(serialize(rec), 200)


@bp.route("/agencies/<agency_id>/vehicles", methods=["GET"])
def list_agency_vehicles(agency_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Dispatcher"])
    get_or_404(store.agencies, agency_id)
    limit, offset = parse_pagination()
    items = [v for v in store.vehicles.values() if v["agency_id"] == agency_id]
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)


# ---- CrewMember ----
@bp.route("/crew-members", methods=["POST"])
def create_crew_member():
    principal = authenticate()
    require_role(principal, ["BillingAdmin"])
    body = get_json_body()
    if body.get("agency_id") is not None:
        resolve_fk(store.agencies, body["agency_id"])
    require_fields(body, ["agency_id", "full_name", "certification"])
    if body["certification"] not in CERTIFICATIONS:
        raise err(ERR_INVALID_ENUM, "Invalid certification")
    rec = {
        "agency_id": body["agency_id"],
        "full_name": body["full_name"],
        "certification": body["certification"],
        "status": "ACTIVE",
    }
    init_common(rec)
    store.crew_members[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/crew-members/<crew_id>", methods=["GET"])
def get_crew_member(crew_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Dispatcher"])
    rec = get_or_404(store.crew_members, crew_id)
    return success(serialize(rec), 200)


@bp.route("/agencies/<agency_id>/crew-members", methods=["GET"])
def list_agency_crew(agency_id):
    principal = authenticate()
    require_role(principal, ["BillingAdmin", "Dispatcher"])
    get_or_404(store.agencies, agency_id)
    limit, offset = parse_pagination()
    items = [c for c in store.crew_members.values() if c["agency_id"] == agency_id]
    page, meta = paginate(items, limit, offset)
    return success(serialize_list(page), 200, list_meta=meta)
