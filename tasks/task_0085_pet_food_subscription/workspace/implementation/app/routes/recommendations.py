"""RecipeRecommendation listing endpoint."""
from __future__ import annotations

from flask import Blueprint

from app.auth import assert_customer_owns, require_role
from app.errors import api_error
from app.pagination import paginate, parse_pagination, sort_by_created_at
from app.response import success_array
from app.store import store


bp = Blueprint("recommendations", __name__)


@bp.route("/pets/<pet_id>/recipe-recommendations", methods=["GET"])
@require_role("Customer", "AdminOps")
def list_recommendations(pet_id, user_id: str, role: str):
    pet = store.pets.get(pet_id)
    if not pet:
        raise api_error("ERR_PET_NOT_FOUND", "Pet not found")
    if role == "Customer":
        assert_customer_owns(pet["customer_id"], user_id, role)
    limit, offset = parse_pagination()
    items = [r for r in store.recommendations.values() if r["pet_id"] == pet_id]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total)
