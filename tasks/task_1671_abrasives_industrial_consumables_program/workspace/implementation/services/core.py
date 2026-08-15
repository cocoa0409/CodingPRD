"""Shared record lifecycle: creation, mutation (touch), serialization, cascades."""
from decimal import Decimal

from db import db
from util import new_id, now_ts


def new_record(collection: str, fields: dict, common_fields: bool = True) -> dict:
    """Create a record with system fields. common_fields=True adds
    created_at/updated_at/version (PRD 2.5); append-only events get id+created_at only."""
    rec = {"id": new_id()}
    rec.update(fields)
    ts = now_ts()
    rec["created_at"] = ts
    if common_fields:
        rec["updated_at"] = ts
        rec["version"] = 1
    db[collection][rec["id"]] = rec
    return rec


def touch(rec: dict):
    """PRD 2.5/2.9: every mutation refreshes updated_at and increments version."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 0) + 1


def serialize(rec):
    """Public view: Decimals become int/float; internal keys (prefix _) hidden."""
    if rec is None:
        return None
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, Decimal):
            out[k] = int(v) if v == v.to_integral_value() else float(v)
        elif isinstance(v, list):
            out[k] = [
                {ik: iv for ik, iv in item.items() if not ik.startswith("_")}
                if isinstance(item, dict) else item
                for item in v
            ]
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Blanket-order helpers
# ---------------------------------------------------------------------------

def recompute_order_value(order: dict):
    """provisional_remaining_value_cents := remaining_qty * provisional_unit_price_cents
    (only once provisional pricing exists)."""
    if order.get("provisional_unit_price_cents") is not None and order.get("remaining_qty") is not None:
        order["provisional_remaining_value_cents"] = (
            order["remaining_qty"] * order["provisional_unit_price_cents"]
        )


def auto_close_check(order: dict):
    """OPEN -> CLOSED when remaining_qty == 0 and no releases in
    SCHEDULED|ON_HOLD|PICKED (checked after ship/cancel)."""
    if order["status"] != "OPEN":
        return
    if order.get("remaining_qty") != 0:
        return
    open_release = any(
        r["blanket_order_id"] == order["id"] and r["status"] in ("SCHEDULED", "ON_HOLD", "PICKED")
        for r in db["releases"].values()
    )
    if not open_release:
        order["status"] = "CLOSED"
        touch(order)


def cancel_release_effects(rel: dict) -> int:
    """Move a release to CANCELLED with per-departure-state side effects
    (PRD 3.7). Returns the give-back qty. Does not mutate the parent order."""
    if rel["status"] == "PICKED":
        # Restore each allocation line's qty to the SAME lot.
        for line in rel["allocations"]:
            lot = db["lots"].get(line["lot_id"])
            if lot is None:
                continue
            lot["qty_on_hand"] += line["qty"]
            # DEPLETED lot lifted above zero returns to AVAILABLE;
            # BLOCKED/EXPIRED lots keep their status.
            if lot["status"] == "DEPLETED" and lot["qty_on_hand"] > 0:
                lot["status"] = "AVAILABLE"
            touch(lot)
        rel["allocations"] = []
    rel["status"] = "CANCELLED"
    touch(rel)
    return rel["qty"]


def cancel_single_release(rel: dict):
    """Individual release cancel: effects + give-back + auto-close (3.7)."""
    order = db["blanket_orders"][rel["blanket_order_id"]]
    give_back = cancel_release_effects(rel)
    if order.get("remaining_qty") is not None:
        order["remaining_qty"] += give_back
        recompute_order_value(order)
    touch(order)
    auto_close_check(order)
