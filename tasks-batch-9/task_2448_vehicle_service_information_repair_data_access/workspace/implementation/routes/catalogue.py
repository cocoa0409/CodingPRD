"""System areas, manufacturers and vehicle models -- PRD 3.1."""

from flask import Blueprint

from auth import authenticate
from calc import as_number, effective_cents_per_system_day, parity_index, stamp_list_basis_parity
from envelope import object_response
from errors import err
from serialize import project
from services import find
from store import store
from validate import body_object, check_allowed, get_bool, get_enum, get_int, get_ref, get_str, pagination, q_enum, q_int

from routes.common import (
    LICENSE_STATUSES,
    OEM_CODE_RE,
    REGIONS,
    SYSTEM_AREA_CODE_RE,
    paged,
)

bp = Blueprint("catalogue", __name__)

READ_ALL = ("PlatformAdmin", "ContentPublisher", "ComplianceOfficer", "ShopManager")
PARITY_READERS = ("PlatformAdmin", "ComplianceOfficer", "ShopManager")
PRICING_FIELDS = (
    "independent_list_monthly_cents",
    "independent_covered_system_count",
    "oem_dealer_monthly_cents",
    "oem_dealer_covered_system_count",
)


@bp.post("/system-areas")
def register_system_area():
    authenticate(("PlatformAdmin",))
    body = body_object()
    check_allowed(body, ("code", "name", "requires_calibration_doc", "requires_security_credential"))
    code = get_str(body, "code", min_len=2, max_len=24)
    if not SYSTEM_AREA_CODE_RE.match(code):
        raise err("ERR_INVALID_REQUEST", "code must be 2..24 uppercase letters or underscores.")
    name = get_str(body, "name", min_len=1, max_len=80)
    requires_calibration_doc = get_bool(body, "requires_calibration_doc")
    requires_security_credential = get_bool(body, "requires_security_credential")
    for existing in store.system_areas.values():
        if existing["code"] == code:
            raise err("ERR_INVALID_REQUEST", "code must be unique across the platform.")

    row = store.base_row(common=False)
    row["code"] = code
    row["name"] = name
    row["requires_calibration_doc"] = requires_calibration_doc
    row["requires_security_credential"] = requires_security_credential
    store.system_areas[row["id"]] = row
    return object_response(project("system_area", row), 201)


@bp.post("/manufacturers")
def register_manufacturer():
    authenticate(("PlatformAdmin",))
    body = body_object()
    check_allowed(body, ("name", "oem_code", "region") + PRICING_FIELDS)
    name = get_str(body, "name", min_len=1, max_len=120)
    oem_code = get_str(body, "oem_code", min_len=2, max_len=8)
    if not OEM_CODE_RE.match(oem_code):
        raise err("ERR_INVALID_REQUEST", "oem_code must be 2..8 uppercase letters or digits.")
    region = get_enum(body, "region", REGIONS)
    figures = {}
    for field in PRICING_FIELDS:
        figures[field] = get_int(body, field, minimum=1)
    for existing in store.manufacturers.values():
        if existing["oem_code"] == oem_code:
            raise err("ERR_INVALID_REQUEST", "oem_code must be unique across the platform.")

    row = store.base_row()
    row["name"] = name
    row["oem_code"] = oem_code
    row["region"] = region
    row.update(figures)
    stamp_list_basis_parity(row)
    store.manufacturers[row["id"]] = row
    return object_response(project("manufacturer", row), 201)


@bp.get("/manufacturers/<manufacturer_id>")
def read_manufacturer(manufacturer_id):
    authenticate(READ_ALL)
    row = find(store.manufacturers, manufacturer_id, "ERR_MANUFACTURER_NOT_FOUND")
    return object_response(project("manufacturer", row))


@bp.patch("/manufacturers/<manufacturer_id>/pricing")
def restate_pricing(manufacturer_id):
    authenticate(("PlatformAdmin",))
    body = body_object()
    check_allowed(body, PRICING_FIELDS)
    supplied = {}
    for field in PRICING_FIELDS:
        value = get_int(body, field, minimum=1, required=False)
        if value is not None:
            supplied[field] = value
    row = find(store.manufacturers, manufacturer_id, "ERR_MANUFACTURER_NOT_FOUND")

    row.update(supplied)
    stamp_list_basis_parity(row)
    store.touch(row)
    return object_response(project("manufacturer", row))


@bp.get("/manufacturers/<manufacturer_id>/parity-report")
def parity_report(manufacturer_id):
    authenticate(PARITY_READERS)
    basis = q_enum("basis", ("LIST_BASIS", "EFFECTIVE_BASIS"), default="LIST_BASIS")
    row = find(store.manufacturers, manufacturer_id, "ERR_MANUFACTURER_NOT_FOUND")

    index, status = parity_index(row, basis)
    independent = effective_cents_per_system_day(
        row["independent_list_monthly_cents"], row["independent_covered_system_count"]
    )
    dealer = effective_cents_per_system_day(
        row["oem_dealer_monthly_cents"], row["oem_dealer_covered_system_count"]
    )
    return object_response(
        {
            "manufacturer_id": row["id"],
            "basis": basis,
            "parity_index": as_number(index, 4),
            "parity_status": status,
            "independent_effective_cents_per_system_day": as_number(independent, 4),
            "oem_effective_cents_per_system_day": as_number(dealer, 4),
            "threshold": 1.15,
        }
    )


@bp.get("/manufacturers/<manufacturer_id>/licenses")
def list_manufacturer_licenses(manufacturer_id):
    authenticate(PARITY_READERS)
    status = q_enum("status", LICENSE_STATUSES)
    limit, offset = pagination()
    find(store.manufacturers, manufacturer_id, "ERR_MANUFACTURER_NOT_FOUND")

    rows = [
        row
        for row in store.licenses.values()
        if row["manufacturer_id"] == manufacturer_id
        and (status is None or row["status"] == status)
    ]
    return paged("license", rows, limit, offset)


@bp.post("/vehicle-models")
def register_vehicle_model():
    authenticate(("PlatformAdmin",))
    body = body_object()
    check_allowed(body, ("manufacturer_id", "model_code", "model_year"))
    manufacturer_id = get_ref(body, "manufacturer_id")
    model_code = get_str(body, "model_code", min_len=1, max_len=24)
    model_year = get_int(body, "model_year", minimum=1990, maximum=2035)
    # PRD 2.6 names "the manufacturer_id axis check when a vehicle model is
    # registered" among the SECONDARY references.
    if manufacturer_id not in store.manufacturers:
        raise err("ERR_REFERENCED_RESOURCE_NOT_FOUND", "manufacturer_id does not resolve.")
    for existing in store.vehicle_models.values():
        if (
            existing["manufacturer_id"] == manufacturer_id
            and existing["model_year"] == model_year
            and existing["model_code"] == model_code
        ):
            raise err(
                "ERR_INVALID_REQUEST",
                "model_code must be unique within this manufacturer and model year.",
            )

    row = store.base_row(common=False)
    row["manufacturer_id"] = manufacturer_id
    row["model_code"] = model_code
    row["model_year"] = model_year
    store.vehicle_models[row["id"]] = row
    return object_response(project("vehicle_model", row), 201)


@bp.get("/manufacturers/<manufacturer_id>/vehicle-models")
def list_manufacturer_vehicle_models(manufacturer_id):
    authenticate(READ_ALL)
    model_year = q_int("model_year")
    limit, offset = pagination()
    find(store.manufacturers, manufacturer_id, "ERR_MANUFACTURER_NOT_FOUND")

    rows = [
        row
        for row in store.vehicle_models.values()
        if row["manufacturer_id"] == manufacturer_id
        and (model_year is None or row["model_year"] == model_year)
    ]
    return paged("vehicle_model", rows, limit, offset)
