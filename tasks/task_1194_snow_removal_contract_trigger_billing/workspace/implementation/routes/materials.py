"""MaterialApplication endpoints."""
from flask import Blueprint
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import recompute_visit_material_cost, recompute_draft_invoices, _touch, round_half_up

bp = Blueprint("materials", __name__)

ALLOWED_FIELDS = {"visit_id", "material_type", "quantity_lbs"}
MATERIAL_TYPES = {"ROCK_SALT", "ICE_MELT_BLEND", "LIQUID_BRINE"}
RATE_FIELD_MAP = {
    "ROCK_SALT": "salt_rate_per_lb_cents",
    "ICE_MELT_BLEND": "blend_rate_per_lb_cents",
    "LIQUID_BRINE": "brine_rate_per_lb_cents",
}


@bp.route("/materials", methods=["POST"])
def create_material():
    user_id, role = require_roles("CrewLead", "Subcontractor")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    visit_id = body.get("visit_id")
    material_type = body.get("material_type")
    quantity_lbs = body.get("quantity_lbs")

    if not visit_id:
        raise ApiError(ERR_INVALID_REQUEST, "visit_id is required", 400)
    visit = db.visits.get(visit_id)
    if not visit:
        raise ApiError(ERR_NOT_FOUND, f"Visit {visit_id} not found", 404)

    if not material_type or material_type not in MATERIAL_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, "material_type must be ROCK_SALT, ICE_MELT_BLEND, or LIQUID_BRINE", 400)
    if quantity_lbs is None:
        raise ApiError(ERR_INVALID_REQUEST, "quantity_lbs is required", 400)
    if quantity_lbs <= 0:
        raise ApiError(ERR_INVALID_QUANTITY, "quantity_lbs must be > 0", 422)

    # Ownership: CrewLead for in-house, Subcontractor for assigned
    if role == "CrewLead":
        if visit.get("assigned_subcontractor_id") is not None:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "CrewLead can only log on in-house visits", 403)
    elif role == "Subcontractor":
        if visit.get("assigned_subcontractor_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your assigned visit", 403)

    # Contract must be ACTIVE
    contract = db.contracts.get(visit.get("contract_id"))
    if contract and contract.get("status") != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, f"Contract is {contract.get('status')}", 409)

    # Rate snapshot
    rate_field = RATE_FIELD_MAP.get(material_type)
    rate_snapshot = contract.get(rate_field, 25) if contract else 25

    line_cost = round_half_up(quantity_lbs * rate_snapshot)

    material = {
        "id": db._new_id(),
        "visit_id": visit_id,
        "material_type": material_type,
        "quantity_lbs": quantity_lbs,
        "rate_per_lb_cents_snapshot": rate_snapshot,
        "line_cost_cents": line_cost,
        "status": "RECORDED",
        "logged_by_user_id": user_id,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.materials.create(material)

    # Recompute visit material cost
    recompute_visit_material_cost(visit_id)
    # Recompute DRAFT invoices
    recompute_draft_invoices(contract_id=visit.get("contract_id"))

    return success_created(material)


@bp.route("/visits/<id>/materials", methods=["GET"])
def list_visit_materials(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "ClientContact", "ClaimsAdjuster", "CrewLead", "Subcontractor")
    visit = db.visits.get(id)
    if not visit:
        raise ApiError(ERR_NOT_FOUND, f"Visit {id} not found", 404)
    # Ownership
    if role == "ClientContact":
        contract = db.contracts.get(visit.get("contract_id"))
        if contract and contract.get("client_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your visit", 403)
    elif role == "Subcontractor":
        if visit.get("assigned_subcontractor_id") != user_id:
            raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your assigned visit", 403)

    limit, offset = get_pagination()
    all_mats = sorted(
        [m for m in db.materials.list_all() if m.get("visit_id") == id],
        key=lambda m: m.get("created_at", ""),
    )
    total = len(all_mats)
    page = all_mats[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/materials/<id>/void", methods=["POST"])
def void_material(id):
    user_id, role = require_roles("CrewLead", "OpsDispatcher")
    material = db.materials.get(id)
    if not material:
        raise ApiError(ERR_NOT_FOUND, f"Material {id} not found", 404)
    if material["status"] == "VOIDED":
        raise ApiError(ERR_ALREADY_TERMINAL, "Material already VOIDED", 409)
    if material["status"] != "RECORDED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot void from {material['status']}", 409)

    # Parent visit billing must not be locked
    visit = db.visits.get(material.get("visit_id"))
    if visit and visit.get("billing_status") in ("INVOICED", "DISPUTED", "SETTLED", "WRITTEN_OFF"):
        raise ApiError(ERR_INVALID_STATE, "Visit billing is locked", 409)

    material["status"] = "VOIDED"
    _touch(material)
    db.materials.update(id, material)

    # Recompute visit material cost
    if visit:
        recompute_visit_material_cost(visit["id"])
        recompute_draft_invoices(contract_id=visit.get("contract_id"))

    return success_object(material)
