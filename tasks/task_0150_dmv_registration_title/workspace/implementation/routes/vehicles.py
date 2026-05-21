"""Vehicle endpoints — intake, read, list, salvage-event."""

from flask import Blueprint, request

from config import (
    FUEL_TYPES,
    LIEN_STATUSES,
    ROLE_APPLICANT,
    ROLE_EMISSIONS_INSPECTOR,
    ROLE_LIEN_CLERK,
    ROLE_PLATE_ISSUER,
    ROLE_PLATFORM_ADMIN,
    ROLE_REAL_ID_REVIEWER,
    ROLE_SALVAGE_OFFICER,
    ROLE_TAX_ASSESSOR,
    ROLE_VIN_VERIFIER,
    SALVAGE_PARTIAL,
    SALVAGE_SEVERITIES,
    SALVAGE_TOTAL,
    TITLE_STATUS_CLEAN,
    TITLE_STATUS_NON_REPAIRABLE,
    TITLE_STATUS_REBUILT,
    TITLE_STATUS_SALVAGE_PENDING_REBUILD,
    TITLE_STATUSES,
)
from db import store
from errors import make_error
from middleware import parse_json_body, require_auth
from response import success
from routes._helpers import (
    build_pagination_meta,
    paginate_and_sort,
    parse_pagination,
    require_enum,
    require_field,
    require_int,
    require_str,
)
from services.engine import (
    cascade_partial_salvage,
    cascade_total_salvage,
    create_vehicle,
)
from services.serializers import serialize_vehicle
from utils import VIN_REGEX

vehicles_bp = Blueprint("vehicles", __name__)


@vehicles_bp.route("/vehicles", methods=["POST"])
@require_auth(allowed_roles=[ROLE_VIN_VERIFIER, ROLE_PLATFORM_ADMIN])
def create_vehicle_endpoint():
    body = parse_json_body()
    vin = require_str(require_field(body, "vin"), "vin")
    if not VIN_REGEX.match(vin):
        raise make_error("ERR_VALIDATION", "vin must be 17 chars [A-HJ-NPR-Z0-9].")
    make_ = require_str(require_field(body, "make"), "make", min_len=1, max_len=50)
    model = require_str(require_field(body, "model"), "model", min_len=1, max_len=50)
    model_year = require_int(require_field(body, "model_year"), "model_year",
                             min_value=1900, max_value=2100)
    curb_weight_lbs = require_int(require_field(body, "curb_weight_lbs"), "curb_weight_lbs",
                                  min_value=200, max_value=40000)
    fuel_type = require_enum(require_field(body, "fuel_type"), "fuel_type", FUEL_TYPES)

    with store.lock:
        # Enforce VIN global uniqueness
        for v in store.vehicles.values():
            if v["vin"] == vin:
                raise make_error("ERR_VALIDATION", "vin must be globally unique.")
        vehicle = create_vehicle(
            vin=vin, make=make_, model=model, model_year=model_year,
            curb_weight_lbs=curb_weight_lbs, fuel_type=fuel_type, now=store.now(),
        )
    return success(serialize_vehicle(vehicle), status=201)


@vehicles_bp.route("/vehicles/<vehicle_id>", methods=["GET"])
@require_auth(allowed_roles=[
    ROLE_VIN_VERIFIER, ROLE_TAX_ASSESSOR, ROLE_PLATE_ISSUER, ROLE_SALVAGE_OFFICER,
    ROLE_EMISSIONS_INSPECTOR, ROLE_LIEN_CLERK, ROLE_REAL_ID_REVIEWER,
    ROLE_APPLICANT, ROLE_PLATFORM_ADMIN,
])
def read_vehicle(vehicle_id: str):
    vehicle = store.vehicles.get(vehicle_id)
    if vehicle is None:
        raise make_error("ERR_RESOURCE_NOT_FOUND")
    return success(serialize_vehicle(vehicle))


@vehicles_bp.route("/vehicles", methods=["GET"])
@require_auth(allowed_roles=[
    ROLE_VIN_VERIFIER, ROLE_TAX_ASSESSOR, ROLE_PLATE_ISSUER, ROLE_SALVAGE_OFFICER,
    ROLE_EMISSIONS_INSPECTOR, ROLE_PLATFORM_ADMIN,
])
def list_vehicles():
    limit, offset = parse_pagination()
    title_status = request.args.get("title_status")
    lien_status = request.args.get("lien_status")
    fuel_type = request.args.get("fuel_type")
    if title_status is not None and title_status not in TITLE_STATUSES:
        raise make_error("ERR_VALIDATION", "Invalid title_status filter.")
    if lien_status is not None and lien_status not in LIEN_STATUSES:
        raise make_error("ERR_VALIDATION", "Invalid lien_status filter.")
    if fuel_type is not None and fuel_type not in FUEL_TYPES:
        raise make_error("ERR_VALIDATION", "Invalid fuel_type filter.")

    rows = []
    for v in store.vehicles.values():
        if title_status is not None and v["title_status"] != title_status:
            continue
        if lien_status is not None and v["lien_status"] != lien_status:
            continue
        if fuel_type is not None and v["fuel_type"] != fuel_type:
            continue
        rows.append(v)
    page, total = paginate_and_sort(rows, limit, offset, sort_key="created_at")
    return success([serialize_vehicle(v) for v in page],
                   pagination=build_pagination_meta(limit, offset, total))


@vehicles_bp.route("/vehicles/<vehicle_id>/salvage-event", methods=["POST"])
@require_auth(allowed_roles=[ROLE_SALVAGE_OFFICER])
def salvage_event(vehicle_id: str):
    body = parse_json_body()
    severity = require_enum(require_field(body, "severity"), "severity", SALVAGE_SEVERITIES)

    with store.lock:
        vehicle = store.vehicles.get(vehicle_id)
        if vehicle is None:
            raise make_error("ERR_RESOURCE_NOT_FOUND")

        if severity == SALVAGE_PARTIAL:
            # PARTIAL: CLEAN -> SALVAGE_PENDING_REBUILD
            if vehicle["title_status"] != TITLE_STATUS_CLEAN:
                raise make_error("ERR_INVALID_STATE",
                                 "PARTIAL salvage requires title_status == CLEAN.")
            cascade_partial_salvage(vehicle, now=store.now())
        else:
            # TOTAL: any -> NON_REPAIRABLE
            if vehicle["title_status"] == TITLE_STATUS_NON_REPAIRABLE:
                raise make_error("ERR_INVALID_STATE",
                                 "Vehicle is already NON_REPAIRABLE.")
            cascade_total_salvage(vehicle, now=store.now())

    return success(serialize_vehicle(vehicle))
