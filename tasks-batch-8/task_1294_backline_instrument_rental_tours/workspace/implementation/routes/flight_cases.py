"""FlightCase endpoints (PRD §3.5)."""

from flask import Blueprint, request
import errors
from db import store
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import domain
from util import (body, req_str, req_enum, new_resource, touch,
                  pagination_params, paginate, sort_by_created)

bp = Blueprint("flight_cases", __name__)

READ_ROLES = {"OpsManager", "TourManager", "LogisticsCoordinator", "WarehouseTech"}
SIZE_CLASSES = {"SMALL", "MEDIUM", "LARGE", "TRUNK"}


@bp.route("/backline/flight-cases", methods=["POST"])
def create_flight_case():
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    data = body()
    case_code = req_str(data, "case_code")
    for fc in store.flight_cases.values():
        if fc.get("case_code") == case_code:
            raise errors.duplicate("case_code already exists")
    case = new_resource()
    case.update({
        "case_code": case_code,
        "size_class": req_enum(data, "size_class", SIZE_CLASSES),
        "home_city_code": req_str(data, "home_city_code"),
        "status": "AVAILABLE",
    })
    store.flight_cases[case["id"]] = case
    return success_object(domain.serialize(case), status=201)


@bp.route("/backline/flight-cases/<case_id>", methods=["GET"])
def fetch_flight_case(case_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    case = domain.get_flight_case(case_id)
    return success_object(domain.serialize(case), status=200)


@bp.route("/backline/flight-cases", methods=["GET"])
def list_flight_cases():
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    limit, offset = pagination_params()
    home_city_code = request.args.get("home_city_code")
    status = request.args.get("status")
    items = list(store.flight_cases.values())
    if home_city_code is not None:
        items = [c for c in items if c.get("home_city_code") == home_city_code]
    if status is not None:
        items = [c for c in items if c.get("status") == status]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(c) for c in page], meta, status=200)


@bp.route("/backline/flight-cases/<case_id>/shipment-lines", methods=["GET"])
def list_case_shipment_lines(case_id):
    auth = get_auth()
    require_roles(auth, READ_ROLES)
    domain.get_flight_case(case_id)
    limit, offset = pagination_params()
    items = [sl for sl in store.shipment_lines.values() if sl.get("flight_case_id") == case_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success_list([domain.serialize(sl) for sl in page], meta, status=200)


@bp.route("/backline/flight-cases/<case_id>/send-to-maintenance", methods=["POST"])
def send_to_maintenance(case_id):
    auth = get_auth()
    require_roles(auth, {"WarehouseTech"})
    case = domain.get_flight_case(case_id)
    if case["status"] != "AVAILABLE":
        raise errors.invalid_state("Case must be AVAILABLE to send to maintenance")
    case["status"] = "MAINTENANCE"
    touch(case)
    return success_object(domain.serialize(case), status=200)


@bp.route("/backline/flight-cases/<case_id>/return-to-service", methods=["POST"])
def return_to_service(case_id):
    auth = get_auth()
    require_roles(auth, {"WarehouseTech"})
    case = domain.get_flight_case(case_id)
    if case["status"] != "MAINTENANCE":
        raise errors.invalid_state("Case must be MAINTENANCE to return to service")
    case["status"] = "AVAILABLE"
    touch(case)
    return success_object(domain.serialize(case), status=200)


@bp.route("/backline/flight-cases/<case_id>/retire", methods=["POST"])
def retire_case(case_id):
    auth = get_auth()
    require_roles(auth, {"OpsManager"})
    case = domain.get_flight_case(case_id)
    if case["status"] != "AVAILABLE":
        raise errors.invalid_state("Case must be AVAILABLE to retire")
    # No shipment line in BOOKED or LOADED may reference the case
    for sl in store.shipment_lines.values():
        if sl.get("flight_case_id") == case["id"] and sl.get("status") in {"BOOKED", "LOADED"}:
            raise errors.invalid_state("Case is referenced by an open shipment line")
    case["status"] = "RETIRED"
    touch(case)
    return success_object(domain.serialize(case), status=200)
