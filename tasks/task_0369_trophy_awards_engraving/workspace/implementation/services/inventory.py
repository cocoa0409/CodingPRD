"""Component availability recompute (calc component_available, PRD §2.9)."""
from db import db


def recompute_component(component):
    """Recompute allocated_qty, available_qty, low_stock for a component from
    scratch. allocated_qty = sum of qty over RESERVED allocations for it."""
    allocated = 0
    for alloc in db.component_allocations.values():
        if alloc["component_id"] == component["id"] and alloc["alloc_status"] == "RESERVED":
            allocated += alloc["qty"]
    component["allocated_qty"] = allocated
    component["available_qty"] = component["on_hand_qty"] - allocated
    component["low_stock"] = component["available_qty"] <= component["reorder_point"]


def recompute_components(component_ids):
    seen = set()
    for cid in component_ids:
        if cid in seen:
            continue
        seen.add(cid)
        comp = db.components.get(cid)
        if comp is not None:
            recompute_component(comp)
