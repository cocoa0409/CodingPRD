"""ProductModel, Technician, and Contractor endpoints (PRD 2.8 registers)."""

from flask import Blueprint

import db
from errors import (
    ApiError, ERR_CONTRACTOR_NOT_ACTIVE, ERR_CONTRACTOR_NOT_FOUND,
    ERR_MODEL_DISCONTINUED, ERR_PRODUCT_MODEL_NOT_FOUND,
    ERR_TECHNICIAN_HAS_OPEN_CALLS, ERR_TECHNICIAN_HAS_OPEN_INSPECTIONS,
    ERR_TECHNICIAN_NOT_ACTIVE, ERR_TECHNICIAN_NOT_FOUND, invalid_request,
)
from middleware import DEALER_ADMIN, ALL_ROLES, require_roles
from response import ok
from routes.common import get_or_404, list_endpoint
from util import get_json_body, serialize, validate_body

bp = Blueprint("catalog", __name__)

DRIVE_TYPES = ["HYDRAULIC", "TRACTION", "PNEUMATIC", "PLATFORM_LIFT"]
CERTIFICATIONS = ["CET", "QEI", "CET_AND_QEI"]

MODEL_SPEC = {
    "model_code": ("string", True, None),
    "drive_type": ("enum", True, DRIVE_TYPES),
    "min_pit_depth_inches": ("number", True, None),
    "min_overhead_clearance_inches": ("number", True, None),
    "capacity_lbs": ("int", True, None),
    "base_price": ("money", True, None),
    "install_labor_price": ("money", True, None),
}

TECHNICIAN_SPEC = {
    "full_name": ("string", True, None),
    "certification": ("enum", True, CERTIFICATIONS),
    "home_region": ("string", True, None),
}

CONTRACTOR_SPEC = {
    "company_name": ("string", True, None),
    "license_number": ("string", True, None),
    "license_state_code": ("string", True, None),
}


# --- ProductModel -----------------------------------------------------------

@bp.post("/api/product-models")
@require_roles(DEALER_ADMIN)
def create_product_model():
    vals = validate_body(get_json_body(), MODEL_SPEC)
    if any(m["model_code"] == vals["model_code"] for m in db.product_models.values()):
        raise invalid_request("model_code must be unique")
    rec = db.new_record({
        "model_code": vals["model_code"],
        "drive_type": vals["drive_type"],
        "min_pit_depth_inches": vals["min_pit_depth_inches"],
        "min_overhead_clearance_inches": vals["min_overhead_clearance_inches"],
        "capacity_lbs": vals["capacity_lbs"],
        "base_price": vals["base_price"],
        "install_labor_price": vals["install_labor_price"],
        "status": "ACTIVE",
    })
    db.product_models[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/product-models")
@require_roles(*ALL_ROLES)
def list_product_models():
    return list_endpoint(db.product_models, {"drive_type": "drive_type", "status": "status"})


@bp.get("/api/product-models/<productModelId>")
@require_roles(*ALL_ROLES)
def get_product_model(productModelId):
    rec = get_or_404(db.product_models, productModelId, ERR_PRODUCT_MODEL_NOT_FOUND, "ProductModel")
    return ok(serialize(rec))


@bp.post("/api/product-models/<productModelId>/discontinue")
@require_roles(DEALER_ADMIN)
def discontinue_product_model(productModelId):
    rec = get_or_404(db.product_models, productModelId, ERR_PRODUCT_MODEL_NOT_FOUND, "ProductModel")
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_MODEL_DISCONTINUED, 409, "Product model is already DISCONTINUED")
    rec["status"] = "DISCONTINUED"
    db.touch(rec)
    return ok(serialize(rec))


# --- Technician -------------------------------------------------------------

@bp.post("/api/technicians")
@require_roles(DEALER_ADMIN)
def create_technician():
    vals = validate_body(get_json_body(), TECHNICIAN_SPEC)
    rec = db.new_record({
        "full_name": vals["full_name"],
        "certification": vals["certification"],
        "home_region": vals["home_region"],
        "status": "ACTIVE",
    })
    db.technicians[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/technicians")
@require_roles(*ALL_ROLES)
def list_technicians():
    return list_endpoint(db.technicians, {"certification": "certification", "status": "status"})


@bp.get("/api/technicians/<technicianId>")
@require_roles(*ALL_ROLES)
def get_technician(technicianId):
    rec = get_or_404(db.technicians, technicianId, ERR_TECHNICIAN_NOT_FOUND, "Technician")
    return ok(serialize(rec))


@bp.post("/api/technicians/<technicianId>/deactivate")
@require_roles(DEALER_ADMIN)
def deactivate_technician(technicianId):
    rec = get_or_404(db.technicians, technicianId, ERR_TECHNICIAN_NOT_FOUND, "Technician")
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_TECHNICIAN_NOT_ACTIVE, 409, "Technician is already INACTIVE")
    tid = rec["id"]
    if any(c["technician_id"] == tid and c["status"] in ("OPEN", "DISPATCHED", "ON_SITE") for c in db.service_calls.values()):
        raise ApiError(ERR_TECHNICIAN_HAS_OPEN_CALLS, 409, "Technician has OPEN/DISPATCHED/ON_SITE service calls")
    if any(i["inspector_technician_id"] == tid and i["status"] == "SCHEDULED" for i in db.inspections.values()):
        raise ApiError(ERR_TECHNICIAN_HAS_OPEN_INSPECTIONS, 409, "Technician has SCHEDULED inspections")
    rec["status"] = "INACTIVE"
    db.touch(rec)
    return ok(serialize(rec))


# --- Contractor -------------------------------------------------------------

@bp.post("/api/contractors")
@require_roles(DEALER_ADMIN)
def create_contractor():
    vals = validate_body(get_json_body(), CONTRACTOR_SPEC)
    if any(c["license_number"] == vals["license_number"] for c in db.contractors.values()):
        raise invalid_request("license_number must be unique")
    rec = db.new_record({
        "company_name": vals["company_name"],
        "license_number": vals["license_number"],
        "license_state_code": vals["license_state_code"],
        "status": "ACTIVE",
    })
    db.contractors[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.get("/api/contractors")
@require_roles(*ALL_ROLES)
def list_contractors():
    return list_endpoint(db.contractors, {"status": "status"})


@bp.get("/api/contractors/<contractorId>")
@require_roles(*ALL_ROLES)
def get_contractor(contractorId):
    rec = get_or_404(db.contractors, contractorId, ERR_CONTRACTOR_NOT_FOUND, "Contractor")
    return ok(serialize(rec))


@bp.post("/api/contractors/<contractorId>/suspend")
@require_roles(DEALER_ADMIN)
def suspend_contractor(contractorId):
    rec = get_or_404(db.contractors, contractorId, ERR_CONTRACTOR_NOT_FOUND, "Contractor")
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACTOR_NOT_ACTIVE, 409, "Contractor is already SUSPENDED")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return ok(serialize(rec))
