"""Order generation, totals, confirmation, cancellation cascade."""
from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.calculations import (
    apply_trial_discount,
    compute_line_total_cents,
    compute_portion_grams_per_day,
    compute_portion_with_delta,
    compute_shipping_fee,
)
from app.clock import logical_clock
from app.errors import api_error
from app.services.recipe_selector import select_recipe
from app.services.recommendations import (
    create_pending_recommendation,
    find_pending_recommendation,
    freeze,
)
from app.store import store
from app.utils import logical_now_iso, new_id, parse_iso, utc_date_key


SHIP_LEAD_TIME_HOURS = 72


def _bump(entity: Dict[str, Any]) -> None:
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = logical_now_iso()


def _compute_item_for_pet(
    pet: Dict[str, Any], recipe: Dict[str, Any], cycle_days: int,
    *, portion_delta_pct: Optional[int] = None,
) -> Dict[str, Any]:
    if portion_delta_pct is not None:
        portion = compute_portion_with_delta(
            weight_kg=float(pet["weight_kg"]),
            activity_level=pet["activity_level"],
            life_stage=pet["life_stage"],
            kcal_per_gram=float(recipe["kcal_per_gram"]),
            portion_delta_pct=int(portion_delta_pct),
        )
    else:
        portion = compute_portion_grams_per_day(
            weight_kg=float(pet["weight_kg"]),
            activity_level=pet["activity_level"],
            life_stage=pet["life_stage"],
            kcal_per_gram=float(recipe["kcal_per_gram"]),
        )
    total_grams = portion * cycle_days
    unit_price_cents = int(recipe["unit_price_cents_per_100g"])
    line_total_cents = compute_line_total_cents(total_grams, unit_price_cents)
    return {
        "pet_id": pet["id"],
        "recipe_id": recipe["id"],
        "portion_grams_per_day": portion,
        "total_grams": total_grams,
        "unit_price_cents": unit_price_cents,
        "line_total_cents": line_total_cents,
    }


def _compute_totals(items: List[Dict[str, Any]], is_trial_pack: bool) -> Tuple[int, int, int]:
    subtotal = sum(it["line_total_cents"] for it in items)
    if is_trial_pack:
        subtotal = apply_trial_discount(subtotal)
    shipping = compute_shipping_fee(subtotal)
    return subtotal, shipping, subtotal + shipping


def emit_order_for_subscription(subscription: Dict[str, Any]) -> Dict[str, Any]:
    """Cycle scheduler emits one order for this ACTIVE subscription."""
    cycle_index = subscription["scheduled_order_count"] + 1

    # For each pet: ensure FROZEN recommendation, regenerate any PENDING first.
    items: List[Dict[str, Any]] = []
    for pet_id in subscription["pet_ids"]:
        pet = store.pets.get(pet_id)
        if not pet:
            raise api_error("ERR_INVALID_PET_LIST", f"Pet {pet_id} no longer exists")
        # Regenerate PENDING recommendation to refresh on current pet state.
        # If the existing PENDING carries a portion_delta_pct or was generated
        # against a specific recipe by an APPLIED RecipeAdjustment, preserve
        # those signals so the emitted order honors PRD §3.4's feedback-
        # adjusted variant rather than reverting to a fresh selector run.
        pending = find_pending_recommendation(subscription["id"], pet_id)
        carry_recipe_id = None
        carry_delta = None
        if pending is not None:
            carry_recipe_id = pending.get("recipe_id")
            carry_delta = pending.get("portion_delta_pct")
            pending["status"] = "SUPERSEDED"
            _bump(pending)
        if carry_recipe_id and carry_recipe_id in store.recipes:
            from app.calculations import compute_match_score, build_explanation

            recipe = store.recipes[carry_recipe_id]
            now_iso = logical_now_iso()
            pending = {
                "id": new_id(),
                "created_at": now_iso,
                "updated_at": now_iso,
                "version": 1,
                "subscription_id": subscription["id"],
                "pet_id": pet["id"],
                "cycle_index": cycle_index,
                "recipe_id": recipe["id"],
                "match_score": compute_match_score(recipe, pet),
                "explanation": build_explanation(recipe, pet, False),
                "status": "PENDING",
            }
            if carry_delta is not None:
                pending["portion_delta_pct"] = carry_delta
            store.recommendations[pending["id"]] = pending
        else:
            pending = create_pending_recommendation(subscription, pet, cycle_index)

        recipe = store.recipes[pending["recipe_id"]]
        delta = pending.get("portion_delta_pct")
        items.append(
            _compute_item_for_pet(
                pet, recipe, subscription["cycle_days"],
                portion_delta_pct=delta,
            )
        )
        freeze(pending)

    is_trial_pack = bool(subscription.get("is_trial", False)) and cycle_index == 1
    subtotal, shipping, total = _compute_totals(items, is_trial_pack)

    now = logical_clock.now()
    scheduled_ship_at = now + timedelta(hours=SHIP_LEAD_TIME_HOURS)
    order_id = new_id()
    now_iso = logical_now_iso()

    # Snapshot shipping address (snapshot at confirmation per PRD §3.4, but we
    # initialise with current address to preserve verified flag; the confirm
    # step refreshes it.)
    address_snapshot = copy.deepcopy(subscription.get("shipping_address") or {})

    order = {
        "id": order_id,
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
        "subscription_id": subscription["id"],
        "customer_id": subscription["customer_id"],
        "cycle_index": cycle_index,
        "scheduled_ship_at": _iso_from_dt(scheduled_ship_at),
        "items": items,
        "warehouse_id": None,
        "assigned_lots": [],
        "subtotal_cents": subtotal,
        "shipping_fee_cents": shipping,
        "total_cents": total,
        "payment_status": "PENDING",
        "fulfillment_status": "SCHEDULED",
        "tracking_number": None,
        "shipping_address_snapshot": address_snapshot,
        "is_trial_pack": is_trial_pack,
    }
    store.orders[order_id] = order

    # Bump subscription counters
    subscription["scheduled_order_count"] += 1
    subscription["total_cycles_elapsed"] += 1
    # Advance next_cycle_at by cycle_days
    if subscription.get("next_cycle_at"):
        cur = parse_iso(subscription["next_cycle_at"])
        new_next = cur + timedelta(days=subscription["cycle_days"])
        subscription["next_cycle_at"] = _iso_from_dt(new_next)
    _bump(subscription)
    return order


def _iso_from_dt(dt) -> str:
    """Format a datetime as the standard ISO string with ms."""
    from app.utils import format_iso

    return format_iso(dt)


# ----------------------------------------------------------------------------
# Confirmation: warehouse + lot selection
# ----------------------------------------------------------------------------


def _utc_date_from_iso(iso: str) -> str:
    dt = parse_iso(iso)
    return utc_date_key(dt)


def _warehouse_capacity_remaining(warehouse: Dict[str, Any], date_key: str) -> int:
    used = store.warehouse_daily_used.get(warehouse["id"], {}).get(date_key, 0)
    return int(warehouse["daily_outbound_capacity"]) - used


def _eligible_lots_for_item(
    warehouse_id: str, recipe_id: str, scheduled_ship_at_dt, required_grams: int
) -> List[Dict[str, Any]]:
    out = []
    for lot in store.inventory_lots.values():
        if lot.get("warehouse_id") != warehouse_id:
            continue
        if lot.get("recipe_id") != recipe_id:
            continue
        # expiration_date > scheduled_ship_at (strictly after)
        exp = parse_iso(lot.get("expiration_date")) if "T" in (lot.get("expiration_date") or "") else None
        if exp is None:
            from app.utils import parse_iso_date

            exp = parse_iso_date(lot.get("expiration_date"))
        if exp is None:
            continue
        if exp <= scheduled_ship_at_dt:
            continue
        if int(lot.get("quantity_grams", 0)) < required_grams:
            continue
        out.append(lot)
    return out


def _warehouse_serves_all_items(
    warehouse: Dict[str, Any], order: Dict[str, Any]
) -> bool:
    ship_at = parse_iso(order["scheduled_ship_at"])
    # Aggregate required grams per recipe across items, since a single lot may need
    # to serve multiple items of the same recipe.
    required_by_recipe: Dict[str, int] = {}
    for item in order["items"]:
        required_by_recipe[item["recipe_id"]] = required_by_recipe.get(item["recipe_id"], 0) + int(
            item["total_grams"]
        )
    for recipe_id, total_required in required_by_recipe.items():
        # Need at least one lot (or sum across lots) that satisfies expiration and
        # total grams. The lot_selector picks one lot per item, so the simplest
        # readable criterion is: for each item, at least one eligible lot exists
        # with >= item.total_grams. We approximate by per-item check below.
        pass
    # Per-item check: each item must have at least one eligible lot.
    for item in order["items"]:
        lots = _eligible_lots_for_item(
            warehouse["id"], item["recipe_id"], ship_at, int(item["total_grams"])
        )
        if not lots:
            return False
    return True


def select_warehouse_for_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """Run the warehouse_selector. Raises ERR_NO_WAREHOUSE_AVAILABLE if none."""
    region = (order.get("shipping_address_snapshot") or {}).get("region")
    date_key = _utc_date_from_iso(order["scheduled_ship_at"])
    candidates: List[Dict[str, Any]] = []
    for wh in store.warehouses.values():
        if wh.get("status") != "ONLINE":
            continue
        if region not in (wh.get("serves_regions") or []):
            continue
        if _warehouse_capacity_remaining(wh, date_key) <= 0:
            continue
        if not _warehouse_serves_all_items(wh, order):
            continue
        candidates.append(wh)
    if not candidates:
        raise api_error("ERR_NO_WAREHOUSE_AVAILABLE", "No warehouse available")
    candidates.sort(key=lambda w: (int(w.get("priority_rank", 0)), w.get("code", "")))
    return candidates[0]


def select_lots_for_order(order: Dict[str, Any], warehouse: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run lot_selector per item; return assigned_lots payload.

    Performs the decrement on each chosen lot atomically as it picks. If at any
    point a lot is unavailable, raise ERR_INSUFFICIENT_INVENTORY (no rollback —
    caller wraps the entire confirm in the store lock).
    """
    ship_at = parse_iso(order["scheduled_ship_at"])
    assigned: List[Dict[str, Any]] = []
    for idx, item in enumerate(order["items"]):
        lots = _eligible_lots_for_item(warehouse["id"], item["recipe_id"], ship_at, int(item["total_grams"]))
        if not lots:
            raise api_error("ERR_INSUFFICIENT_INVENTORY", "No eligible inventory lot")
        # FEFO: expiration ASC, batch_code ASC, id ASC
        def _exp_key(l):
            from app.utils import parse_iso_date

            exp = parse_iso_date(l.get("expiration_date"))
            return exp

        lots.sort(key=lambda l: (_exp_key(l), l.get("batch_code", ""), l.get("id", "")))
        chosen = lots[0]
        # Decrement
        grams = int(item["total_grams"])
        chosen["quantity_grams"] = int(chosen["quantity_grams"]) - grams
        _bump(chosen)
        assigned.append(
            {
                "item_index": idx,
                "lot_id": chosen["id"],
                "batch_code": chosen["batch_code"],
                "expiration_date": chosen["expiration_date"],
                "grams_drawn": grams,
            }
        )
    return assigned


def debit_warehouse_capacity(warehouse_id: str, date_key: str) -> None:
    bucket = store.warehouse_daily_used.setdefault(warehouse_id, {})
    bucket[date_key] = bucket.get(date_key, 0) + 1


def refund_warehouse_capacity(warehouse_id: str, date_key: str) -> None:
    bucket = store.warehouse_daily_used.get(warehouse_id)
    if not bucket:
        return
    if bucket.get(date_key, 0) > 0:
        bucket[date_key] -= 1


def restore_lots_for_order(order: Dict[str, Any]) -> None:
    for assigned in order.get("assigned_lots", []) or []:
        lot = store.inventory_lots.get(assigned.get("lot_id"))
        if not lot:
            continue
        lot["quantity_grams"] = int(lot["quantity_grams"]) + int(assigned.get("grams_drawn", 0))
        _bump(lot)


def cancel_order_fulfillment(order: Dict[str, Any]) -> None:
    """Move fulfillment to CANCELLED (idempotent for non-terminal sources)."""
    current = order.get("fulfillment_status")
    if current in ("CANCELLED", "DELIVERED"):
        return
    # Restore inventory + capacity if we already debited
    if order.get("assigned_lots"):
        restore_lots_for_order(order)
        order["assigned_lots"] = []
    if order.get("warehouse_id"):
        date_key = _utc_date_from_iso(order["scheduled_ship_at"])
        refund_warehouse_capacity(order["warehouse_id"], date_key)
        order["warehouse_id"] = None
    order["fulfillment_status"] = "CANCELLED"
    _bump(order)
