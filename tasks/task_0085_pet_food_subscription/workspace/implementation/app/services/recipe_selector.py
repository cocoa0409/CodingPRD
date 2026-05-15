"""Recipe selector — eligibility filter + ranking (PRD §3.3)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.calculations import (
    build_explanation,
    compute_match_score,
    recipe_passes_hard_gates,
)
from app.errors import api_error
from app.store import store


def get_previous_monotony_class_for_pet(
    subscription_id: str, pet_id: str
) -> Optional[str]:
    """Return monotony_class of the recipe used for this pet in the most recent prior
    Order whose fulfillment_status is one of CONFIRMED, SHIPPED, DELIVERED.

    Ordering: cycle_index DESC, id ASCII DESC tie-break.
    """
    counted_statuses = {"CONFIRMED", "SHIPPED", "DELIVERED"}
    candidates = [
        o
        for o in store.orders.values()
        if o.get("subscription_id") == subscription_id
        and o.get("fulfillment_status") in counted_statuses
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda o: (o.get("cycle_index", 0), o.get("id", "")), reverse=True)
    for order in candidates:
        for item in order.get("items", []):
            if item.get("pet_id") == pet_id:
                recipe = store.recipes.get(item.get("recipe_id"))
                if recipe:
                    return recipe.get("monotony_class")
    return None


def select_recipe(
    pet: Dict[str, Any],
    subscription: Dict[str, Any],
    cycle_index: int,
    *,
    enforce_rotation: bool = True,
    block_monotony_class: Optional[str] = None,
    require_different_protein_source_set: Optional[set] = None,
) -> Tuple[Dict[str, Any], int, List[str], bool]:
    """Run the recipe selector and return (recipe, score, explanation, rotation_ok).

    Raises ERR_NO_RECIPE_AVAILABLE when the candidate pool is empty.

    block_monotony_class is the monotony_class to forbid (used both for normal rotation
    and for forced SWAP_RECIPE_FAMILY).
    """
    is_trial_cycle1 = bool(subscription.get("is_trial", False)) and cycle_index == 1

    # If caller did not specify block class explicitly but rotation is enforced,
    # derive from history.
    if enforce_rotation and block_monotony_class is None:
        block_monotony_class = get_previous_monotony_class_for_pet(
            subscription["id"], pet["id"]
        )

    eligible: List[Dict[str, Any]] = []
    elimination_reasons: List[str] = []
    for recipe in store.recipes.values():
        reason = recipe_passes_hard_gates(
            recipe,
            pet,
            is_trial_cycle1=is_trial_cycle1,
            rotation_block_monotony=block_monotony_class if enforce_rotation else None,
            enforce_rotation=enforce_rotation,
        )
        if reason is not None:
            elimination_reasons.append(reason)
            continue
        # ROTATE_PROTEIN forced protein-source rotation
        if require_different_protein_source_set is not None:
            cand_proteins = set(recipe.get("protein_sources", []) or [])
            if cand_proteins and cand_proteins == require_different_protein_source_set:
                continue
        eligible.append(recipe)

    if not eligible:
        raise api_error("ERR_NO_RECIPE_AVAILABLE", "No eligible recipe for pet")

    scored = [
        (compute_match_score(r, pet), r) for r in eligible
    ]
    scored.sort(
        key=lambda pair: (
            -pair[0],  # descending score
            pair[1].get("code", ""),  # ascending code
            pair[1].get("id", ""),  # ascending id
        )
    )

    score, chosen = scored[0]
    rotation_ok = enforce_rotation and (block_monotony_class is not None)
    explanation = build_explanation(chosen, pet, rotation_ok)
    return chosen, score, explanation, rotation_ok
