"""Clock advance side effects: cycle scheduling, auto-resume, auto-confirm (PRD §2.8, §3.4)."""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from app.audit import append_audit
from app.calculations import compute_life_stage
from app.clock import logical_clock
from app.errors import APIError
from app.services.orders import (
    cancel_order_fulfillment,
    debit_warehouse_capacity,
    emit_order_for_subscription,
    select_lots_for_order,
    select_warehouse_for_order,
)
from app.services.subscriptions import compute_next_cycle_iso
from app.store import store
from app.utils import format_iso, logical_now_iso, parse_iso, utc_date_key


def _recompute_life_stages() -> None:
    for pet in store.pets.values():
        new_stage = compute_life_stage(pet["species"], pet["birthdate"])
        if new_stage != pet.get("life_stage"):
            pet["life_stage"] = new_stage
            pet["updated_at"] = logical_now_iso()
            pet["version"] = pet.get("version", 1) + 1


def _emit_cycles() -> None:
    now = logical_clock.now()
    # For every ACTIVE sub whose next_cycle_at <= now, emit ONE order.
    for sub in list(store.subscriptions.values()):
        if sub.get("status") != "ACTIVE":
            continue
        nxt_iso = sub.get("next_cycle_at")
        if not nxt_iso:
            continue
        nxt = parse_iso(nxt_iso)
        if nxt is None or nxt > now:
            continue
        try:
            emit_order_for_subscription(sub)
        except APIError:
            # If we can't emit (e.g. ERR_NO_RECIPE_AVAILABLE) we silently skip
            # for this advance; scheduler is not user-facing.
            continue


def _auto_resume_paused() -> None:
    now = logical_clock.now()
    for sub in list(store.subscriptions.values()):
        if sub.get("status") != "PAUSED":
            continue
        pu_iso = sub.get("paused_until")
        if not pu_iso:
            continue
        pu = parse_iso(pu_iso)
        if pu is None or pu > now:
            continue
        before = {"status": "PAUSED", "paused_until": pu_iso}
        sub["status"] = "ACTIVE"
        sub["paused_until"] = None
        sub["next_cycle_at"] = compute_next_cycle_iso(now, sub["cycle_days"])
        sub["updated_at"] = logical_now_iso()
        sub["version"] = sub.get("version", 1) + 1
        append_audit(
            actor_role="AdminOps",
            actor_id="system",
            entity_type="Subscription",
            entity_id=sub["id"],
            event_type="RESUMED",
            before=before,
            after={"status": "ACTIVE", "paused_until": None, "next_cycle_at": sub["next_cycle_at"]},
        )


def _auto_confirm_orders() -> None:
    now = logical_clock.now()
    candidates: List[Dict[str, Any]] = [
        o
        for o in store.orders.values()
        if o.get("fulfillment_status") == "SCHEDULED"
    ]
    for order in candidates:
        sub = store.subscriptions.get(order["subscription_id"])
        if not sub or sub.get("status") != "ACTIVE":
            continue
        ship_at = parse_iso(order["scheduled_ship_at"])
        deadline = ship_at - timedelta(hours=int(sub.get("modification_deadline_hours", 48)))
        if now <= deadline:
            continue
        # Refresh address snapshot from current subscription address
        snap = dict(sub.get("shipping_address") or {})
        order["shipping_address_snapshot"] = snap
        if not bool(snap.get("verified", False)):
            # Cannot auto-confirm without verified address; leave SCHEDULED
            continue
        try:
            warehouse = select_warehouse_for_order(order)
            assigned = select_lots_for_order(order, warehouse)
        except APIError:
            continue
        order["warehouse_id"] = warehouse["id"]
        order["assigned_lots"] = assigned
        order["fulfillment_status"] = "CONFIRMED"
        order["updated_at"] = logical_now_iso()
        order["version"] = order.get("version", 1) + 1
        debit_warehouse_capacity(warehouse["id"], utc_date_key(ship_at))


def run_clock_advance_side_effects() -> None:
    _recompute_life_stages()
    _emit_cycles()
    _auto_resume_paused()
    _auto_confirm_orders()
