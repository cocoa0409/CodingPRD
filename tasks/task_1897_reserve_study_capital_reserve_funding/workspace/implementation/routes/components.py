"""Component endpoints."""

from flask import request, Blueprint
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from errors import (
    make_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_STUDY_NOT_DRAFT,
)
from services.calculations import recompute_study_totals

bp = Blueprint("components", __name__)

VALID_CATEGORIES = {"ROOFING", "PAVING", "MECHANICAL", "EXTERIOR", "INTERIOR", "RECREATION", "OTHER"}


def serialize_component(comp):
    return {
        "id": comp["id"],
        "created_at": comp["created_at"],
        "updated_at": comp["updated_at"],
        "version": comp["version"],
        "study_id": comp["study_id"],
        "name": comp["name"],
        "category": comp["category"],
        "useful_life_years": comp["useful_life_years"],
        "remaining_useful_life_years": comp["remaining_useful_life_years"],
        "current_replacement_cost_cents": comp["current_replacement_cost_cents"],
        "is_included_in_funding": comp.get("is_included_in_funding", True),
        "status": comp["status"],
        "actual_expenditure_cents": comp.get("actual_expenditure_cents", 0),
        "last_replaced_fiscal_year": comp.get("last_replaced_fiscal_year"),
    }


def _parse_pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (ValueError, TypeError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        offset = 0
    offset = max(0, offset)
    return limit, offset


def _require_study_draft(comp):
    """Check that the component's study is DRAFT."""
    study = store.reserve_studies.get(comp["study_id"])
    if not study:
        raise make_error(ERR_NOT_FOUND, f"Study {comp['study_id']} not found")
    if study["status"] != "DRAFT":
        raise make_error(ERR_STUDY_NOT_DRAFT, f"Study is {study['status']}, not DRAFT")
    return study


@bp.route("/components", methods=["POST"])
def create_component():
    require_roles("ReserveSpecialist")
    body = request.get_json(force=True, silent=True) or {}

    required = ["study_id", "name", "category", "useful_life_years",
                "remaining_useful_life_years", "current_replacement_cost_cents"]
    allowed = set(required) | {"is_included_in_funding"}
    for field in required:
        if field not in body:
            raise make_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    for key in body:
        if key not in allowed:
            raise make_error(ERR_INVALID_REQUEST, f"Unknown field: {key}")

    study_id = body["study_id"]
    study = store.reserve_studies.get(study_id)
    if not study:
        raise make_error(ERR_NOT_FOUND, f"ReserveStudy {study_id} not found")

    # Shape validation
    if not isinstance(body["name"], str):
        raise make_error(ERR_INVALID_REQUEST, "name must be a string")
    if body["category"] not in VALID_CATEGORIES:
        raise make_error(ERR_INVALID_REQUEST, f"Invalid category: {body['category']}")
    if not isinstance(body["useful_life_years"], int) or body["useful_life_years"] < 1:
        raise make_error(ERR_INVALID_REQUEST, "useful_life_years must be >= 1")
    if not isinstance(body["remaining_useful_life_years"], int) or body["remaining_useful_life_years"] < 0:
        raise make_error(ERR_INVALID_REQUEST, "remaining_useful_life_years must be >= 0")
    if body["remaining_useful_life_years"] > body["useful_life_years"]:
        raise make_error(ERR_INVALID_REQUEST, "remaining_useful_life_years must be <= useful_life_years")
    if not isinstance(body["current_replacement_cost_cents"], int) or body["current_replacement_cost_cents"] <= 0:
        raise make_error(ERR_INVALID_REQUEST, "current_replacement_cost_cents must be > 0")
    if "is_included_in_funding" in body and not isinstance(body["is_included_in_funding"], bool):
        raise make_error(ERR_INVALID_REQUEST, "is_included_in_funding must be a boolean")

    # Study must be DRAFT
    if study["status"] != "DRAFT":
        raise make_error(ERR_STUDY_NOT_DRAFT, f"Study is {study['status']}, not DRAFT")

    comp = store.make_common_fields()
    comp.update({
        "study_id": study_id,
        "name": body["name"],
        "category": body["category"],
        "useful_life_years": body["useful_life_years"],
        "remaining_useful_life_years": body["remaining_useful_life_years"],
        "current_replacement_cost_cents": body["current_replacement_cost_cents"],
        "is_included_in_funding": body.get("is_included_in_funding", True),
        "status": "ACTIVE",
        "actual_expenditure_cents": 0,
        "last_replaced_fiscal_year": None,
    })
    store.components[comp["id"]] = comp

    # Recompute study totals
    recompute_study_totals(study)

    return success_object(serialize_component(comp), 201)


@bp.route("/reserve-studies/<id>/components", methods=["GET"])
def list_components(id):
    require_roles(*ANY_ROLE)
    study = store.reserve_studies.get(id)
    if not study:
        raise make_error(ERR_NOT_FOUND, f"ReserveStudy {id} not found")

    status_filter = request.args.get("status")
    comps = [c for c in store.components.values() if c["study_id"] == id]
    if status_filter:
        comps = [c for c in comps if c["status"] == status_filter]
    comps.sort(key=lambda c: c["created_at"])

    limit, offset = _parse_pagination()
    total = len(comps)
    page = comps[offset:offset + limit]
    return success_list([serialize_component(c) for c in page], total, limit, offset)


@bp.route("/components/<id>", methods=["PATCH"])
def patch_component(id):
    require_roles("ReserveSpecialist")
    comp = store.components.get(id)
    if not comp:
        raise make_error(ERR_NOT_FOUND, f"Component {id} not found")

    body = request.get_json(force=True, silent=True) or {}
    allowed_fields = {"name", "category", "useful_life_years", "remaining_useful_life_years",
                      "current_replacement_cost_cents", "is_included_in_funding"}
    for key in body:
        if key not in allowed_fields:
            raise make_error(ERR_INVALID_REQUEST, f"Unknown field: {key}")

    # Validate fields if present
    if "name" in body and not isinstance(body["name"], str):
        raise make_error(ERR_INVALID_REQUEST, "name must be a string")
    if "category" in body and body["category"] not in VALID_CATEGORIES:
        raise make_error(ERR_INVALID_REQUEST, f"Invalid category: {body['category']}")
    if "useful_life_years" in body:
        if not isinstance(body["useful_life_years"], int) or body["useful_life_years"] < 1:
            raise make_error(ERR_INVALID_REQUEST, "useful_life_years must be >= 1")
    if "remaining_useful_life_years" in body:
        if not isinstance(body["remaining_useful_life_years"], int) or body["remaining_useful_life_years"] < 0:
            raise make_error(ERR_INVALID_REQUEST, "remaining_useful_life_years must be >= 0")
    if "current_replacement_cost_cents" in body:
        if not isinstance(body["current_replacement_cost_cents"], int) or body["current_replacement_cost_cents"] <= 0:
            raise make_error(ERR_INVALID_REQUEST, "current_replacement_cost_cents must be > 0")
    if "is_included_in_funding" in body and not isinstance(body["is_included_in_funding"], bool):
        raise make_error(ERR_INVALID_REQUEST, "is_included_in_funding must be a boolean")

    # Cross-field: RUL <= UL
    new_ul = body.get("useful_life_years", comp["useful_life_years"])
    new_rul = body.get("remaining_useful_life_years", comp["remaining_useful_life_years"])
    if new_rul > new_ul:
        raise make_error(ERR_INVALID_REQUEST, "remaining_useful_life_years must be <= useful_life_years")

    # Study must be DRAFT
    study = _require_study_draft(comp)

    # Apply updates
    for key in allowed_fields:
        if key in body:
            comp[key] = body[key]
    store.touch(comp)

    # Recompute study totals
    recompute_study_totals(study)

    return success_object(serialize_component(comp))


@bp.route("/components/<id>/retire", methods=["POST"])
def retire_component(id):
    require_roles("ReserveSpecialist")
    comp = store.components.get(id)
    if not comp:
        raise make_error(ERR_NOT_FOUND, f"Component {id} not found")

    study = _require_study_draft(comp)

    comp["status"] = "RETIRED"
    store.touch(comp)

    # Recompute study totals
    recompute_study_totals(study)

    return success_object(serialize_component(comp))


@bp.route("/components/<id>/restore", methods=["POST"])
def restore_component(id):
    require_roles("ReserveSpecialist")
    comp = store.components.get(id)
    if not comp:
        raise make_error(ERR_NOT_FOUND, f"Component {id} not found")

    study = _require_study_draft(comp)

    comp["status"] = "ACTIVE"
    store.touch(comp)

    # Recompute study totals
    recompute_study_totals(study)

    return success_object(serialize_component(comp))
