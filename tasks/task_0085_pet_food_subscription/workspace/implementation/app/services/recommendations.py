"""Recommendation lifecycle helpers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.recipe_selector import select_recipe
from app.store import store
from app.utils import logical_now_iso, new_id


def create_pending_recommendation(
    subscription: Dict[str, Any],
    pet: Dict[str, Any],
    cycle_index: int,
) -> Dict[str, Any]:
    recipe, score, explanation, _ = select_recipe(pet, subscription, cycle_index)
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
        "match_score": score,
        "explanation": explanation,
        "status": "PENDING",
    }
    store.recommendations[rec["id"]] = rec
    return rec


def find_pending_recommendation(
    subscription_id: str, pet_id: str, cycle_index: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    candidates = [
        r
        for r in store.recommendations.values()
        if r.get("subscription_id") == subscription_id
        and r.get("pet_id") == pet_id
        and r.get("status") == "PENDING"
    ]
    if cycle_index is not None:
        candidates = [r for r in candidates if r.get("cycle_index") == cycle_index]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r.get("cycle_index", 0), r.get("created_at", "")))
    return candidates[0]


def supersede(rec: Dict[str, Any]) -> None:
    rec["status"] = "SUPERSEDED"
    rec["updated_at"] = logical_now_iso()
    rec["version"] = rec.get("version", 1) + 1


def freeze(rec: Dict[str, Any]) -> None:
    rec["status"] = "FROZEN"
    rec["updated_at"] = logical_now_iso()
    rec["version"] = rec.get("version", 1) + 1
