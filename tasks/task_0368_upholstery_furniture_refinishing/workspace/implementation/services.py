"""Cross-entity reconciliation and derived-field helpers (PRD §2.7).

Centralizes the recompute logic for WorkOrder derived fields so every
money-touching event stays consistent.
"""
from db import db
import calculations as calc
from helpers import touch


def order_line_items(wo_id):
    items = [li for li in db.line_items.values() if li["work_order_id"] == wo_id]
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def order_material_orders(wo_id):
    items = [mo for mo in db.material_orders.values() if mo["work_order_id"] == wo_id]
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def fabric_price_lookup(fabric_sku_id):
    if fabric_sku_id is None:
        return 0
    sku = db.fabric_skus.get(fabric_sku_id)
    return sku["price_cents_per_yard"] if sku else 0


def foam_price_lookup(foam_spec_id):
    if foam_spec_id is None:
        return 0
    spec = db.foam_specs.get(foam_spec_id)
    return spec["price_cents_per_board_foot"] if spec else 0


def recompute_line_item_subtotal(li, service_type):
    li["piece_subtotal_cents"] = calc.piece_subtotal(
        service_type=service_type,
        labor_hours=li["labor_hours"],
        yardage_required=li["yardage_required"],
        board_feet_required=li["board_feet_required"],
        fabric_price_per_yard=fabric_price_lookup(li.get("fabric_sku_id")),
        foam_spec_id=li.get("foam_spec_id"),
        foam_price_per_board_foot=foam_price_lookup(li.get("foam_spec_id")),
    )


def reconcile_materials_committed(wo):
    """materials_committed_cents = sum of provisional_cost over ORDERED|RECEIVED
    material orders for this work order (PRD §2.7)."""
    total = 0
    for mo in db.material_orders.values():
        if mo["work_order_id"] == wo["id"] and mo["status"] in ("ORDERED", "RECEIVED"):
            total += mo["provisional_cost_cents"]
    wo["materials_committed_cents"] = total


def reconcile_balance_due(wo):
    """balance_due_cents per the single basis rule (PRD §3.7)."""
    wo["balance_due_cents"] = calc.balance_due(
        wo["final_invoice_cents"], wo["estimate_total_cents"], wo["amount_paid_cents"]
    )


def recompute_shop_day_status(day):
    """Auto-flip OPEN<->FULL based on booked vs capacity (PRD §3.6).
    Never overrides CLOSED."""
    if day["status"] == "CLOSED":
        return
    if day["booked_hours"] >= day["labor_capacity_hours"]:
        if day["status"] != "FULL":
            day["status"] = "FULL"
            touch(day)
    else:
        if day["status"] != "OPEN":
            day["status"] = "OPEN"
            touch(day)
