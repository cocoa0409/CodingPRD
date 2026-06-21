"""Agency endpoints: register, fetch, list, patch, reverse-reachability."""
from flask import Blueprint, request

from db import db
from errors import err, ERR_INVALID_REQUEST
from middleware import get_identity, require_role
from response import object_response, array_response
from services import models
from services.validate import (
    get_json_body,
    parse_pagination,
    paginate,
    require_string,
    optional_string,
    optional_int,
    optional_enum,
)
from routes.lookups import get_agency

bp = Blueprint("agencies", __name__)

READ_ROLES_ALL = {"FoodBankOperator", "AllocationManager", "ComplianceAuditor", "AgencyCoordinator"}
READ_ROLES_NO_COORD = {"FoodBankOperator", "AllocationManager", "ComplianceAuditor"}
AGENCY_STATUS = {"ACTIVE", "SUSPENDED"}


@bp.post("/agencies")
def create_agency():
    user_id, role = get_identity()
    require_role(role, {"AllocationManager"})
    body = get_json_body()
    name = require_string(body, "name")
    service_area = require_string(body, "service_area")
    fair_share_weight = optional_int(body, "fair_share_weight", minimum=1, default=1)
    status = optional_enum(body, "status", AGENCY_STATUS, default="ACTIVE")

    agency = models._common_create()
    agency.update(
        {
            "name": name,
            "service_area": service_area,
            "fair_share_weight": fair_share_weight,
            "status": status,
            "lifetime_distributed_lbs": 0,
        }
    )
    db.agencies[agency["id"]] = agency
    return object_response(models.serialize_agency(agency), status=201)


@bp.get("/agencies/<agency_id>")
def fetch_agency(agency_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES_ALL)
    agency = get_agency(agency_id)
    return object_response(models.serialize_agency(agency))


@bp.get("/agencies")
def list_agencies():
    user_id, role = get_identity()
    require_role(role, READ_ROLES_NO_COORD)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    agencies = list(db.agencies.values())
    if status is not None:
        agencies = [a for a in agencies if a["status"] == status]
    agencies.sort(key=lambda a: a["_seq"])
    page, total = paginate(agencies, limit, offset)
    return array_response([models.serialize_agency(a) for a in page], limit, offset, total)


@bp.patch("/agencies/<agency_id>")
def patch_agency(agency_id):
    user_id, role = get_identity()
    require_role(role, {"AllocationManager"})
    agency = get_agency(agency_id)
    body = get_json_body()
    status = optional_enum(body, "status", AGENCY_STATUS, default=None)
    fair_share_weight = optional_int(body, "fair_share_weight", minimum=1, default=None)
    service_area = optional_string(body, "service_area", default=None)

    if status is not None:
        agency["status"] = status
    if fair_share_weight is not None:
        agency["fair_share_weight"] = fair_share_weight
    if service_area is not None:
        agency["service_area"] = service_area
    models.touch(agency)
    return object_response(models.serialize_agency(agency))


@bp.get("/agencies/<agency_id>/client-households")
def agency_households(agency_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES_ALL)
    agency = get_agency(agency_id)
    limit, offset = parse_pagination()
    cert = request.args.get("certification_status")
    households = [h for h in db.client_households.values() if h["agency_id"] == agency["id"]]
    if cert is not None:
        households = [h for h in households if h["certification_status"] == cert]
    households.sort(key=lambda h: h["_seq"])
    page, total = paginate(households, limit, offset)
    return array_response(
        [models.serialize_household(h) for h in page], limit, offset, total
    )


@bp.get("/agencies/<agency_id>/agency-orders")
def agency_orders(agency_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES_ALL)
    agency = get_agency(agency_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    orders = [o for o in db.agency_orders.values() if o["agency_id"] == agency["id"]]
    if status is not None:
        orders = [o for o in orders if o["status"] == status]
    orders.sort(key=lambda o: o["_seq"])
    page, total = paginate(orders, limit, offset)
    return array_response([models.serialize_order(o) for o in page], limit, offset, total)
