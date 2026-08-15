from flask import Blueprint, request

from db import store, new_entity, touch
from errors import (
    ApiError, ERR_DUPLICATE, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_PARENT_MISMATCH,
)
from middleware import require_roles
from response import object_response
from serializers import practice_area_view, matter_type_view
from validation import Payload, require_exists, list_page

bp = Blueprint("taxonomy", __name__, url_prefix="/legal-ops")

ALL = ("LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive")
CODE_PATTERN = r"[A-Z0-9]{2,8}"


# ---------------------------------------------------------- practice areas
@bp.post("/practice-areas")
@require_roles("LegalOpsManager")
def create_practice_area(user_id, role):
    p = Payload()
    code = p.req_str("code", pattern=CODE_PATTERN)
    display_name = p.req_str("display_name")
    if code is not None:
        for a in store.practice_areas.values():
            if a["code"] == code:
                raise ApiError(ERR_DUPLICATE, 409, "Practice area code already exists")
    p.finish()
    pa = new_entity({"code": code, "display_name": display_name, "status": "ACTIVE"})
    store.practice_areas[pa["id"]] = pa
    return object_response(practice_area_view(pa), 201)


@bp.get("/practice-areas")
@require_roles(*ALL)
def list_practice_areas(user_id, role):
    items = list(store.practice_areas.values())
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_page(items, practice_area_view)


@bp.get("/practice-areas/<pa_id>")
@require_roles(*ALL)
def get_practice_area(user_id, role, pa_id):
    return object_response(practice_area_view(require_exists(store.practice_areas, pa_id, "practice area")))


@bp.post("/practice-areas/<pa_id>/archive")
@require_roles("LegalOpsManager")
def archive_practice_area(user_id, role, pa_id):
    pa = require_exists(store.practice_areas, pa_id, "practice area")
    if pa["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Practice area is not ACTIVE")
    pa["status"] = "ARCHIVED"
    touch(pa)
    return object_response(practice_area_view(pa))


# ------------------------------------------------------------- matter types
@bp.post("/practice-areas/<pa_id>/matter-types")
@require_roles("LegalOpsManager")
def create_matter_type(user_id, role, pa_id):
    pa = require_exists(store.practice_areas, pa_id, "practice area")
    p = Payload()
    code = p.req_str("code")
    display_name = p.req_str("display_name")
    default_budget = p.opt_int("default_budget_cents")
    body_pa = p.opt_str("practice_area_id")
    # Uniqueness within the practice area (priority 10) before parent mismatch (11).
    if code is not None:
        for t in store.matter_types.values():
            if t["practice_area_id"] == pa_id and t["code"] == code:
                raise ApiError(ERR_DUPLICATE, 409, "Matter type code already exists in this practice area")
    if body_pa is not None and body_pa != pa_id:
        raise ApiError(ERR_PARENT_MISMATCH, 422, "MatterType practice_area_id does not match URL parent")
    if default_budget is not None and default_budget < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "default_budget_cents must be >= 0")
    p.finish()
    mt = new_entity({
        "practice_area_id": pa_id,
        "code": code,
        "display_name": display_name,
        "default_budget_cents": 0 if default_budget is None else default_budget,
    })
    store.matter_types[mt["id"]] = mt
    return object_response(matter_type_view(mt), 201)


@bp.get("/practice-areas/<pa_id>/matter-types")
@require_roles(*ALL)
def list_matter_types(user_id, role, pa_id):
    require_exists(store.practice_areas, pa_id, "practice area")
    items = [t for t in store.matter_types.values() if t["practice_area_id"] == pa_id]
    return list_page(items, matter_type_view)


@bp.get("/matter-types/<mt_id>")
@require_roles(*ALL)
def get_matter_type(user_id, role, mt_id):
    return object_response(matter_type_view(require_exists(store.matter_types, mt_id, "matter type")))
