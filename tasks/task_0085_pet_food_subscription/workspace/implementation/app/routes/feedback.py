"""Feedback endpoint (POST /orders/{id}/feedback)."""
from __future__ import annotations

from flask import Blueprint, request

from app.auth import assert_customer_owns, require_role
from app.errors import api_error
from app.response import success_object
from app.services.suggestion_engine import run_suggestion_engine
from app.store import store
from app.utils import is_int, is_nonempty_str, logical_now_iso, new_id


bp = Blueprint("feedback", __name__)


def _validate_rating(value):
    return is_int(value) and 1 <= value <= 5


@bp.route("/orders/<order_id>/feedback", methods=["POST"])
@require_role("Customer")
def submit_feedback(order_id, user_id: str, role: str):
    order = store.orders.get(order_id)
    if not order:
        raise api_error("ERR_ORDER_NOT_FOUND", "Order not found")
    assert_customer_owns(order["customer_id"], user_id, role)
    if order["fulfillment_status"] != "DELIVERED":
        raise api_error("ERR_INVALID_ORDER_STATE", "Order not DELIVERED")

    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")

    pet_id = body.get("pet_id")
    if not is_nonempty_str(pet_id):
        raise api_error("ERR_INVALID_REQUEST", "pet_id required")
    sub = store.subscriptions.get(order["subscription_id"])
    if not sub or pet_id not in (sub.get("pet_ids") or []):
        raise api_error("ERR_INVALID_REQUEST", "pet_id not in subscription")
    pet = store.pets.get(pet_id)
    if not pet:
        raise api_error("ERR_PET_NOT_FOUND", "Pet not found")

    palatability = body.get("palatability")
    stool = body.get("stool_quality")
    coat = body.get("coat_condition")
    weight_change = body.get("weight_change_grams")
    notes = body.get("notes")

    if not _validate_rating(palatability):
        raise api_error("ERR_INVALID_FEEDBACK_PAYLOAD", "palatability must be int [1,5]")
    if not _validate_rating(stool):
        raise api_error("ERR_INVALID_FEEDBACK_PAYLOAD", "stool_quality must be int [1,5]")
    if not _validate_rating(coat):
        raise api_error("ERR_INVALID_FEEDBACK_PAYLOAD", "coat_condition must be int [1,5]")
    if not is_int(weight_change):
        raise api_error("ERR_INVALID_FEEDBACK_PAYLOAD", "weight_change_grams must be integer")
    if notes is not None and not isinstance(notes, str):
        raise api_error("ERR_INVALID_REQUEST", "notes must be string")

    fid = new_id()
    now = logical_now_iso()
    feedback = {
        "id": fid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "order_id": order_id,
        "pet_id": pet_id,
        "palatability": int(palatability),
        "stool_quality": int(stool),
        "coat_condition": int(coat),
        "weight_change_grams": int(weight_change),
        "notes": notes,
        "adverse_flag": int(palatability) <= 2 or int(stool) <= 2,
    }
    store.feedbacks[fid] = feedback

    # Apply weight change to pet
    pet["weight_kg"] = float(pet["weight_kg"]) + (int(weight_change) / 1000.0)
    pet["updated_at"] = logical_now_iso()
    pet["version"] = pet.get("version", 1) + 1

    # Run suggestion engine
    run_suggestion_engine(pet_id, role, user_id)

    return success_object(feedback, status=201)
