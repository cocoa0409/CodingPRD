"""InstructionalMaterial + AlignmentMapping endpoints (PRD §3.2), plus the
material-scoped inventory lot and distribution order reads (PRD §3.7)."""

from flask import Blueprint, request

import serializers
from db import bump, new_id, stamp_new, store
from errors import invalid_state
from middleware import (ALL_ROLES, auth_context, get_body, get_or_404,
                        req_enum, req_str, require_roles)
from response import paginate, sort_created, success_object
from services.calculations import recompute_coverage

bp = Blueprint("materials", __name__)


def _get_material(material_id):
    return get_or_404(store.materials, material_id, "InstructionalMaterial")


@bp.route("/materials", methods=["GET"])
def list_materials():
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    items = list(store.materials.values())
    cycle_id = request.args.get("cycle_id")
    adoption_status = request.args.get("adoption_status")
    availability_status = request.args.get("availability_status")
    if cycle_id is not None:
        items = [m for m in items if m["cycle_id"] == cycle_id]
    if adoption_status is not None:
        items = [m for m in items if m["adoption_status"] == adoption_status]
    if availability_status is not None:
        items = [m for m in items if m["availability_status"] == availability_status]
    return paginate(sort_created(items), serializers.material)


@bp.route("/materials/<materialId>", methods=["GET"])
def get_material(materialId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    return success_object(serializers.material(_get_material(materialId)))


@bp.route("/materials/<materialId>/transitions", methods=["POST"])
def material_transition(materialId):
    user_id, role = auth_context()
    require_roles(role, ("InstructionalSpecialist",))
    material = _get_material(materialId)
    body = get_body()
    to_state = req_enum(body, "to_state", ("VETTED", "REJECTED"))
    if material["adoption_status"] != "SUBMITTED":
        raise invalid_state("only a SUBMITTED material may be vetted or rejected")
    if to_state == "VETTED":
        cycle = store.cycles.get(material["cycle_id"])
        if cycle is None or cycle["status"] not in ("DRAFT", "ALIGNMENT_REVIEW"):
            raise invalid_state(
                "vetting requires the material's cycle to be DRAFT or "
                "ALIGNMENT_REVIEW")
    material["adoption_status"] = to_state
    bump(material)
    return success_object(serializers.material(material))


@bp.route("/materials/<materialId>/alignments", methods=["POST"])
def upsert_alignment(materialId):
    user_id, role = auth_context()
    require_roles(role, ("InstructionalSpecialist",))
    material = _get_material(materialId)
    body = get_body()
    standard_code = req_str(body, "standard_code")
    coverage_rating = req_enum(body, "coverage_rating",
                               ("NONE", "PARTIAL", "FULL"))
    key = (material["id"], standard_code)
    existing_id = store.alignment_index.get(key)
    if existing_id is not None:
        mapping = store.alignments[existing_id]
        mapping["coverage_rating"] = coverage_rating
        bump(mapping)
        status_code = 200
    else:
        mapping = {
            "id": new_id(),
            "material_id": material["id"],
            "standard_code": standard_code,
            "coverage_rating": coverage_rating,
        }
        stamp_new(mapping)
        store.alignments[mapping["id"]] = mapping
        store.alignment_index[key] = mapping["id"]
        status_code = 201
    # Every create or upsert recomputes the material's coverage_pct (PRD §3.2).
    from db import refresh
    recompute_coverage(material)
    refresh(material)
    return success_object(serializers.alignment(mapping), status=status_code)


@bp.route("/materials/<materialId>/alignments", methods=["GET"])
def list_alignments(materialId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    material = _get_material(materialId)
    items = [a for a in store.alignments.values()
             if a["material_id"] == material["id"]]
    return paginate(sort_created(items), serializers.alignment)


@bp.route("/materials/<materialId>/inventory-lots", methods=["GET"])
def get_inventory_lots(materialId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    material = _get_material(materialId)
    lot = store.inventory_lots.get(material["id"])
    items = [lot] if lot is not None else []
    return paginate(sort_created(items), serializers.inventory_lot)


@bp.route("/materials/<materialId>/distribution-orders", methods=["GET"])
def list_material_distribution_orders(materialId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    material = _get_material(materialId)
    items = [do for do in store.distribution_orders.values()
             if do["material_id"] == material["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [do for do in items if do["status"] == status]
    return paginate(sort_created(items), serializers.distribution_order)
