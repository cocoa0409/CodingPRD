"""Onboarding + property portal + complaints routes."""
from flask import Blueprint
from store import store, new_entity
from auth import require_role, body, require_fields, as_int, check_enum
from errors import err
from lookups import get_landlord, get_property, sorted_by_creation
from pagination import paginate
from envelope import success, list_response
from serializers import (
    landlord_dict, inspector_dict, property_dict, complaint_dict,
    license_dict, notice_dict,
)
from domain import licenses_of_property

bp = Blueprint("onboarding", __name__)

CERT_LEVELS = {"STANDARD", "SENIOR", "LEAD_CERTIFIED"}
COMPLAINT_CATEGORIES = {"LIFE_SAFETY", "HABITABILITY", "LEAD_PAINT", "STRUCTURAL"}
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
REG_STATUSES = {"REGISTERED", "SUSPENDED", "CONDEMNED"}


@bp.post("/landlords")
def create_landlord():
    require_role({"Registrar"})
    data = body()
    require_fields(data, ["full_name", "email", "phone", "mailing_address"])
    e = new_entity(store.landlords, {
        "full_name": data["full_name"],
        "email": data["email"],
        "phone": data["phone"],
        "mailing_address": data["mailing_address"],
    })
    return success(landlord_dict(e), status=201)


@bp.post("/inspectors")
def create_inspector():
    require_role({"Registrar"})
    data = body()
    require_fields(data, ["full_name", "badge_number", "email"])
    cert = data.get("certification_level", "STANDARD")
    if cert is None:
        cert = "STANDARD"
    check_enum(cert, "certification_level", CERT_LEVELS)
    active = data.get("active", True)
    if active is None:
        active = True
    if not isinstance(active, bool):
        raise err("ERR_VALIDATION", "active must be a boolean")
    e = new_entity(store.inspectors, {
        "full_name": data["full_name"],
        "badge_number": data["badge_number"],
        "email": data["email"],
        "certification_level": cert,
        "active": active,
    })
    return success(inspector_dict(e), status=201)


@bp.post("/properties")
def create_property():
    uid, role = require_role({"Landlord", "Registrar"})
    data = body()
    # Ownership (priority 3): a Landlord may only register properties they own.
    if role == "Landlord" and data.get("landlord_id") != uid:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "Landlord may only register own properties")
    # Existence of the referenced landlord (priority 5), if provided.
    if data.get("landlord_id") is not None:
        get_landlord(data["landlord_id"])
    # Structural validation (priority 6).
    require_fields(data, ["landlord_id", "street_address", "unit_count", "year_built"])
    unit_count = as_int(data, "unit_count")
    year_built = as_int(data, "year_built")
    if unit_count < 1:
        raise err("ERR_VALIDATION", "unit_count must be >= 1")
    e = new_entity(store.properties, {
        "landlord_id": data["landlord_id"],
        "street_address": data["street_address"],
        "unit_count": unit_count,
        "year_built": year_built,
        "registration_status": "REGISTERED",
        "current_license_id": None,
        "total_fees_paid_cents": 0,
    })
    return success(property_dict(e), status=201)


@bp.get("/properties/<pid>")
def get_property_route(pid):
    require_role({"Landlord", "Registrar", "Inspector"})
    e = get_property(pid)
    return success(property_dict(e), status=200)


@bp.get("/properties")
def list_properties():
    require_role({"Landlord", "Registrar"})
    from flask import request
    items = list(store.properties.values())
    landlord_id = request.args.get("landlord_id")
    if landlord_id is not None:
        items = [p for p in items if p["landlord_id"] == landlord_id]
    reg = request.args.get("registration_status")
    if reg is not None:
        items = [p for p in items if p["registration_status"] == reg]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(items)
    return list_response([property_dict(p) for p in page], limit, offset, total)


@bp.get("/properties/<pid>/rental-licenses")
def list_property_licenses(pid):
    require_role({"Landlord", "Registrar"})
    get_property(pid)
    items = sorted_by_creation(licenses_of_property(pid))
    page, limit, offset, total = paginate(items)
    return list_response([license_dict(x) for x in page], limit, offset, total)


@bp.get("/properties/<pid>/complaints")
def list_property_complaints(pid):
    require_role({"Registrar", "Landlord"})
    get_property(pid)
    items = sorted_by_creation([c for c in store.complaints.values() if c["property_id"] == pid])
    page, limit, offset, total = paginate(items)
    return list_response([complaint_dict(x) for x in page], limit, offset, total)


@bp.get("/properties/<pid>/tenant-notices")
def list_property_notices(pid):
    require_role({"Registrar", "Landlord"})
    get_property(pid)
    items = sorted_by_creation([n for n in store.notices.values() if n["property_id"] == pid])
    page, limit, offset, total = paginate(items)
    return list_response([notice_dict(x) for x in page], limit, offset, total)


@bp.post("/complaints")
def create_complaint():
    require_role({"Tenant"})
    data = body()
    # Existence of referenced property (priority 5), if provided.
    if data.get("property_id") is not None:
        get_property(data["property_id"])
    require_fields(data, [
        "property_id", "tenant_email", "tenant_unit",
        "category", "description", "severity_alleged",
    ])
    check_enum(data["category"], "category", COMPLAINT_CATEGORIES)
    check_enum(data["severity_alleged"], "severity_alleged", SEVERITIES)
    e = new_entity(store.complaints, {
        "property_id": data["property_id"],
        "tenant_email": data["tenant_email"],
        "tenant_unit": data["tenant_unit"],
        "category": data["category"],
        "description": data["description"],
        "severity_alleged": data["severity_alleged"],
        "status": "FILED",
        "filed_at": store.now(),
    })
    return success(complaint_dict(e), status=201)
