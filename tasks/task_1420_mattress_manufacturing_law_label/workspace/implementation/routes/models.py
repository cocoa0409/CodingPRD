"""MattressModel lifecycle endpoints."""
from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_string, body, require
from services import cascade

bp = Blueprint("models", __name__)


def model_view(m):
    return {
        "id": m["id"],
        "model_code": m["model_code"],
        "quilt_pattern": m["quilt_pattern"],
        "bom_cost_cents": m["bom_cost_cents"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def get_model(model_id):
    m = db.models.get(model_id)
    if m is None:
        errors.raise_err(errors.ERR_MODEL_NOT_FOUND, "model not found")
    return m


@bp.route("/models", methods=["POST"])
def create_model():
    middleware.require_roles(["PlantManager"])
    data = body()
    code = as_string(require(data, "model_code"), "model_code")
    pattern = as_string(require(data, "quilt_pattern"), "quilt_pattern")
    model = {
        "id": db.new_id(),
        "model_code": code,
        "quilt_pattern": pattern,
        "bom_cost_cents": 0,
        "status": "DRAFT",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.models, model)
    return response.success_object(model_view(model), 201)


@bp.route("/models", methods=["GET"])
def list_models():
    middleware.require_roles(middleware.ALL_ROLES)
    cascade.touch_certificates()
    items = list(db.models.values())
    q = request.args.get("status")
    if q is not None:
        items = [m for m in items if m["status"] == q]
    items.sort(key=lambda m: m["_seq"])
    return response.success_list([model_view(m) for m in items])


@bp.route("/models/<modelId>", methods=["GET"])
def get_one_model(modelId):
    middleware.require_roles(middleware.ALL_ROLES)
    cascade.touch_certificates()
    m = get_model(modelId)
    return response.success_object(model_view(m))


@bp.route("/models/<mid>/submit-for-certification", methods=["POST"])
def submit_for_certification(mid):
    middleware.require_roles(["PlantManager"])
    model = get_model(mid)
    if model["status"] != "DRAFT":
        errors.raise_err(errors.ERR_MODEL_NOT_DRAFT, "model must be DRAFT")
    has_bom = any(l["model_id"] == model["id"] for l in db.bom_lines.values())
    if not has_bom:
        errors.raise_err(errors.ERR_MODEL_HAS_NO_BOM, "model has no BOM lines")
    model["status"] = "CERT_REVIEW"
    cascade.bump(model)
    return response.success_object(model_view(model))


@bp.route("/models/<mid>/return-to-draft", methods=["POST"])
def return_to_draft(mid):
    middleware.require_roles(["PlantManager"])
    model = get_model(mid)
    if model["status"] != "CERT_REVIEW":
        errors.raise_err(errors.ERR_MODEL_NOT_CERT_REVIEW, "model must be CERT_REVIEW")
    model["status"] = "DRAFT"
    cascade.bump(model)
    return response.success_object(model_view(model))


@bp.route("/models/<mid>/certify", methods=["POST"])
def certify(mid):
    middleware.require_roles(["ComplianceOfficer"])
    model = get_model(mid)
    if model["status"] != "CERT_REVIEW":
        errors.raise_err(errors.ERR_MODEL_NOT_CERT_REVIEW, "model must be CERT_REVIEW")
    if not cascade.approved_unexpired_flammability_certs(model["id"]):
        errors.raise_err(
            errors.ERR_CERT_REQUIRED,
            "no APPROVED unexpired FLAMMABILITY_16CFR1633 certificate",
        )
    model["status"] = "CERTIFIED"
    cascade.bump(model)
    return response.success_object(model_view(model))


@bp.route("/models/<mid>/activate", methods=["POST"])
def activate(mid):
    middleware.require_roles(["PlantManager"])
    model = get_model(mid)
    if model["status"] != "CERTIFIED":
        errors.raise_err(errors.ERR_MODEL_NOT_CERTIFIED, "model must be CERTIFIED")
    model["status"] = "ACTIVE"
    cascade.bump(model)
    return response.success_object(model_view(model))


@bp.route("/models/<mid>/discontinue", methods=["POST"])
def discontinue(mid):
    middleware.require_roles(["PlantManager"])
    model = get_model(mid)
    if model["status"] != "ACTIVE":
        errors.raise_err(errors.ERR_MODEL_NOT_ACTIVE, "model must be ACTIVE")
    open_statuses = {"PLANNED", "MATERIAL_ALLOCATED", "IN_PRODUCTION", "QC_PENDING", "QC_HOLD"}
    for order in db.orders.values():
        if order["model_id"] == model["id"] and order["production_status"] in open_statuses:
            errors.raise_err(errors.ERR_OPEN_ORDERS_EXIST, "model has open production orders")
    model["status"] = "DISCONTINUED"
    cascade.bump(model)
    return response.success_object(model_view(model))
