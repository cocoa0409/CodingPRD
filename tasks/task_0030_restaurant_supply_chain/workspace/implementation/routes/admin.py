"""Test-driving / admin endpoints: clock advance, sweeps, synthetic events."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
import errors
import helpers
import response
from middleware import auth_required
from services import audit
from routes.replenishment_rules import _generate_replenishment_order, _on_hand_for


bp = Blueprint("admin", __name__, url_prefix="/supply-chain")


# --- Clock advance ---
@bp.route("/_clock/advance", methods=["POST"])
@auth_required("PlatformAdmin")
def clock_advance():
    body = helpers.get_json_body()
    if "to_iso8601" not in body:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "Missing to_iso8601.")
    target = clock.parse_iso(body["to_iso8601"])
    clock.advance_to(target)
    return response.ok({"current_instant": clock.iso_format(clock.now())})


# --- Expiry-alert sweep ---
@bp.route("/_sweep/expiry-alerts", methods=["POST"])
@auth_required("PlatformAdmin")
def expiry_sweep():
    now = clock.now()
    updated = []
    for batch in db.inventory_batches.values():
        if batch["status"] != "ON_HAND":
            continue
        if batch["expires_at"] is None:
            continue
        delta_seconds = (batch["expires_at"] - now).total_seconds()
        h = int(delta_seconds // 3600)  # floor of hours
        if h <= 0:
            tier = "TIER3"
        elif h <= 8:
            tier = "TIER2"
        elif h <= 24:
            tier = "TIER1"
        else:
            tier = "NONE"
        if batch["alert_tier"] != tier:
            old = batch["alert_tier"]
            batch["alert_tier"] = tier
            helpers.bump(batch)
            audit.append(target_type="InventoryBatch", target_id=batch["id"],
                         action="ALERT_TIER_UPDATED",
                         payload={"old_tier": old, "new_tier": tier, "hours_to_expiry": h})
            updated.append({"inventory_batch_id": batch["id"], "alert_tier": tier})
    return response.ok({"updated_batches": updated, "swept_at": clock.iso_format(now)})


# --- Replenishment sweep ---
@bp.route("/_sweep/replenish", methods=["POST"])
@auth_required("PlatformAdmin")
def replenish_sweep():
    now = clock.now()
    generated = []
    for rule in list(db.replenishment_rules.values()):
        if rule["status"] != "ACTIVE":
            continue
        last = rule["last_evaluated_at"]
        if last is not None:
            elapsed_hours = (now - last).total_seconds() / 3600.0
            if elapsed_hours < rule["cycle_hours"]:
                continue
        # Cycle elapsed (or first evaluation): evaluate.
        on_hand = _on_hand_for(rule["store_id"], rule["recipe_id"])
        if on_hand <= rule["safety_stock_units"]:
            order = _generate_replenishment_order(rule)
            generated.append({"rule_id": rule["id"], "store_order_id": order["id"]})
        else:
            # Still stamp last_evaluated_at to mark this cycle handled.
            rule["last_evaluated_at"] = now
            helpers.bump(rule)
            audit.append(target_type="ReplenishmentRule", target_id=rule["id"],
                         action="REPLENISHMENT_SKIP",
                         payload={"on_hand": on_hand,
                                  "safety_stock_units": rule["safety_stock_units"]})
    return response.ok({"generated_orders": generated, "swept_at": clock.iso_format(now)})


# --- Synthetic event emission ---
@bp.route("/_events/emit", methods=["POST"])
@auth_required("PlatformAdmin")
def emit_event():
    body = helpers.get_json_body()
    if "system" not in body or "payload" not in body:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "Missing system or payload.")
    system = body["system"]
    payload = body["payload"]
    if system not in {"POS", "ERP", "FINANCE", "LOGISTICS"}:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "Invalid system.")
    entry = audit.append(target_type="ExternalEvent", target_id=db.new_id(),
                         action=f"EMIT_{system}_EVENT", payload=payload,
                         external_systems=[system])
    return response.ok({"audit_log_entry_id": entry["id"], "system": system})
