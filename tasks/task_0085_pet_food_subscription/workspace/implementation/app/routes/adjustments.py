"""RecipeAdjustment endpoints + vet event ingress."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from app.audit import append_audit
from app.auth import assert_customer_owns, require_role
from app.calculations import (
    compute_portion_grams_per_day,
    compute_portion_with_delta,
    recipe_passes_hard_gates,
)
from app.clock import logical_clock
from app.errors import api_error
from app.pagination import paginate, parse_pagination, sort_by_created_at
from app.response import success_array, success_object
from app.services.recipe_selector import (
    get_previous_monotony_class_for_pet,
    select_recipe,
)
from app.services.recommendations import (
    create_pending_recommendation,
    find_pending_recommendation,
    supersede,
)
from app.services.subscriptions import get_next_scheduled_order
from app.store import store
from app.utils import logical_now_iso, parse_iso


bp = Blueprint("adjustments", __name__)


def _ensure_pet_and_owned(pet_id, user_id, role):
    pet = store.pets.get(pet_id)
    if not pet:
        raise api_error("ERR_PET_NOT_FOUND", "Pet not found")
    if role == "Customer":
        assert_customer_owns(pet["customer_id"], user_id, role)
    return pet


def _ensure_adj_under_pet(pet_id, adj_id, user_id, role):
    pet = _ensure_pet_and_owned(pet_id, user_id, role)
    adj = store.adjustments.get(adj_id)
    if not adj or adj.get("pet_id") != pet_id:
        raise api_error("ERR_ADJUSTMENT_NOT_FOUND", "Adjustment not found")
    return pet, adj


@bp.route("/pets/<pet_id>/recipe-adjustments", methods=["GET"])
@require_role("Customer", "AdminOps")
def list_adjustments(pet_id, user_id: str, role: str):
    _ensure_pet_and_owned(pet_id, user_id, role)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [
        a
        for a in store.adjustments.values()
        if a["pet_id"] == pet_id and (not status_filter or a.get("status") == status_filter)
    ]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total)


@bp.route("/pets/<pet_id>/recipe-adjustments/<adj_id>", methods=["GET"])
@require_role("Customer", "AdminOps")
def get_adjustment(pet_id, adj_id, user_id: str, role: str):
    _, adj = _ensure_adj_under_pet(pet_id, adj_id, user_id, role)
    return success_object(adj)


def _apply_adjustment_side_effects(pet, adj, subscription):
    """Regenerate next PENDING recommendation, append history, log audit."""
    # Find the most recent PENDING recommendation for this pet under that subscription
    pending = find_pending_recommendation(subscription["id"], pet["id"])
    next_cycle = subscription.get("scheduled_order_count", 0) + 1
    cycle_index = pending["cycle_index"] if pending else next_cycle
    if pending:
        supersede(pending)

    # If the adjustment carries a target_recipe_id, prefer that recipe (validate eligibility).
    if adj.get("target_recipe_id"):
        recipe = store.recipes.get(adj["target_recipe_id"])
        if not recipe:
            raise api_error("ERR_RECIPE_NOT_ELIGIBLE", "target recipe not found")
        # Validate against current pet
        prev_monotony = get_previous_monotony_class_for_pet(subscription["id"], pet["id"])
        reason = recipe_passes_hard_gates(
            recipe,
            pet,
            is_trial_cycle1=(bool(subscription.get("is_trial")) and cycle_index == 1),
            rotation_block_monotony=prev_monotony,
            enforce_rotation=True,
        )
        if reason is not None:
            raise api_error("ERR_RECIPE_NOT_ELIGIBLE", "Recipe not eligible")
        now = logical_now_iso()
        from app.calculations import compute_match_score, build_explanation
        from app.utils import new_id

        rec = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "subscription_id": subscription["id"],
            "pet_id": pet["id"],
            "cycle_index": cycle_index,
            "recipe_id": recipe["id"],
            "match_score": compute_match_score(recipe, pet),
            "explanation": build_explanation(recipe, pet, prev_monotony is not None),
            "status": "PENDING",
        }
        store.recommendations[rec["id"]] = rec
    else:
        # PRD §3.5: portion-delta adjustments (INCREASE_PORTION /
        # DECREASE_PORTION) do not change the recipe; they only
        # change portion_grams_per_day via portion_delta_pct applied
        # at the next order emission (PRD §3.4 feedback-adjusted
        # variant). Re-running the selector with rotation enforcement
        # would mis-block the previously chosen recipe. We therefore
        # carry the previous PENDING recommendation's recipe forward
        # (or fall back to the most recent prior order's recipe for
        # this pet).
        from app.calculations import compute_match_score, build_explanation
        from app.utils import new_id

        carried_recipe_id = None
        if pending and pending.get("recipe_id"):
            carried_recipe_id = pending["recipe_id"]
        else:
            for o in sorted(
                store.orders.values(),
                key=lambda o: o.get("cycle_index", 0),
                reverse=True,
            ):
                if o.get("subscription_id") != subscription["id"]:
                    continue
                for it in o.get("items", []):
                    if it.get("pet_id") == pet["id"]:
                        carried_recipe_id = it.get("recipe_id")
                        break
                if carried_recipe_id:
                    break
        if carried_recipe_id and carried_recipe_id in store.recipes:
            recipe = store.recipes[carried_recipe_id]
            now = logical_now_iso()
            rec = {
                "id": new_id(),
                "created_at": now,
                "updated_at": now,
                "version": 1,
                "subscription_id": subscription["id"],
                "pet_id": pet["id"],
                "cycle_index": cycle_index,
                "recipe_id": recipe["id"],
                "match_score": compute_match_score(recipe, pet),
                "explanation": build_explanation(recipe, pet, False),
                "status": "PENDING",
                # PRD §3.4 feedback-adjusted variant: portion delta is
                # captured on the regenerated recommendation so the
                # next order emission applies it before rounding.
                "portion_delta_pct": adj.get("portion_delta_pct"),
            }
            store.recommendations[rec["id"]] = rec
        else:
            # No prior recipe to carry — fall back to a fresh selection.
            create_pending_recommendation(subscription, pet, cycle_index)

    # Append history
    pet.setdefault("adjustment_history", []).append(
        {
            "adjustment_id": adj["id"],
            "applied_at": logical_now_iso(),
            "summary": ",".join(adj.get("rationale", []) or []),
        }
    )
    pet["updated_at"] = logical_now_iso()
    pet["version"] = pet.get("version", 1) + 1


@bp.route("/pets/<pet_id>/recipe-adjustments/<adj_id>/apply", methods=["POST"])
@require_role("Customer")
def apply_adjustment(pet_id, adj_id, user_id: str, role: str):
    pet, adj = _ensure_adj_under_pet(pet_id, adj_id, user_id, role)
    if adj["status"] not in ("SUGGESTED", "VET_APPROVED"):
        raise api_error("ERR_INVALID_ADJUSTMENT_STATE", "Adjustment not appliable")
    if adj["status"] == "SUGGESTED" and adj.get("suggestion_type") == "VET_ESCALATE":
        raise api_error("ERR_INVALID_ADJUSTMENT_STATE", "Must go through vet first")
    if pet["status"] != "ACTIVE":
        raise api_error("ERR_PET_NOT_ACTIVE", "Pet not active")

    sub = store.subscriptions.get(adj["subscription_id"])
    if not sub:
        raise api_error("ERR_INVALID_ADJUSTMENT_STATE", "Subscription gone")

    # Modification window: next non-terminal SCHEDULED order's time-to-ship strictly > deadline
    order = get_next_scheduled_order(sub["id"])
    if order:
        ship_at = parse_iso(order["scheduled_ship_at"])
        cutoff = ship_at - timedelta(hours=int(sub["modification_deadline_hours"]))
        if logical_clock.now() >= cutoff:
            raise api_error("ERR_MODIFICATION_DEADLINE_PASSED", "Past modification deadline")

    # If target_recipe_id is referenced, ensure it still exists.
    if adj.get("target_recipe_id") and not store.recipes.get(adj["target_recipe_id"]):
        raise api_error("ERR_RECIPE_NOT_ELIGIBLE", "Target recipe not found")

    _apply_adjustment_side_effects(pet, adj, sub)

    adj["status"] = "APPLIED"
    adj["applied_at"] = logical_now_iso()
    adj["updated_at"] = logical_now_iso()
    adj["version"] = adj.get("version", 1) + 1

    append_audit(
        actor_role=role,
        actor_id=user_id,
        entity_type="RecipeAdjustment",
        entity_id=adj_id,
        event_type="ADJUSTMENT_APPLIED",
        before={"status": "SUGGESTED"},
        after={"status": "APPLIED"},
    )
    return success_object(adj)


@bp.route("/pets/<pet_id>/recipe-adjustments/<adj_id>/dismiss", methods=["POST"])
@require_role("Customer")
def dismiss_adjustment(pet_id, adj_id, user_id: str, role: str):
    pet, adj = _ensure_adj_under_pet(pet_id, adj_id, user_id, role)
    if adj["status"] != "SUGGESTED":
        raise api_error("ERR_INVALID_ADJUSTMENT_STATE", "Adjustment not SUGGESTED")
    before = {"status": "SUGGESTED"}
    adj["status"] = "DISMISSED"
    adj["updated_at"] = logical_now_iso()
    adj["version"] = adj.get("version", 1) + 1
    append_audit(
        actor_role=role,
        actor_id=user_id,
        entity_type="RecipeAdjustment",
        entity_id=adj_id,
        event_type="ADJUSTMENT_DISMISSED",
        before=before,
        after={"status": "DISMISSED"},
    )
    return success_object(adj)


@bp.route("/pets/<pet_id>/recipe-adjustments/<adj_id>/escalate", methods=["POST"])
@require_role("Customer")
def escalate_adjustment(pet_id, adj_id, user_id: str, role: str):
    pet, adj = _ensure_adj_under_pet(pet_id, adj_id, user_id, role)
    if adj["status"] != "SUGGESTED":
        raise api_error("ERR_INVALID_ADJUSTMENT_STATE", "Adjustment not SUGGESTED")
    before_status = pet["status"]
    adj["status"] = "VET_PENDING"
    adj["updated_at"] = logical_now_iso()
    adj["version"] = adj.get("version", 1) + 1
    pet["status"] = "VET_HOLD"
    pet["updated_at"] = logical_now_iso()
    pet["version"] = pet.get("version", 1) + 1
    append_audit(
        actor_role=role,
        actor_id=user_id,
        entity_type="Pet",
        entity_id=pet_id,
        event_type="VET_ESCALATED",
        before={"status": before_status},
        after={"status": "VET_HOLD"},
    )
    return success_object(adj)


@bp.route("/pets/<pet_id>/recipe-adjustments/<adj_id>/events/vet", methods=["POST"])
@require_role("VetAdapter")
def vet_event(pet_id, adj_id, user_id: str, role: str):
    pet = store.pets.get(pet_id)
    if not pet:
        raise api_error("ERR_PET_NOT_FOUND", "Pet not found")
    adj = store.adjustments.get(adj_id)
    if not adj or adj.get("pet_id") != pet_id:
        raise api_error("ERR_ADJUSTMENT_NOT_FOUND", "Adjustment not found")
    body = request.get_json(silent=True) or {}
    et = body.get("event_type") if isinstance(body, dict) else None
    if et not in ("VET_APPROVED", "VET_REJECTED"):
        raise api_error("ERR_INVALID_REQUEST", "Unknown vet event_type")
    if adj["status"] != "VET_PENDING":
        raise api_error("ERR_INVALID_ADJUSTMENT_STATE", "Adjustment not VET_PENDING")

    if et == "VET_APPROVED":
        adj["status"] = "VET_APPROVED"
        pet["status"] = "ACTIVE"
    else:  # VET_REJECTED
        adj["status"] = "VET_REJECTED"
        pet["status"] = "ACTIVE"
        append_audit(
            actor_role=role,
            actor_id=user_id,
            entity_type="RecipeAdjustment",
            entity_id=adj_id,
            event_type="ADJUSTMENT_DISMISSED",
            before={"status": "VET_PENDING"},
            after={"status": "VET_REJECTED", "rationale": "vet rejected"},
        )
    adj["updated_at"] = logical_now_iso()
    adj["version"] = adj.get("version", 1) + 1
    pet["updated_at"] = logical_now_iso()
    pet["version"] = pet.get("version", 1) + 1
    return success_object(adj)
