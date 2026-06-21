"""Inventory on-hand recomputation (calc inventory_on_hand, PRD §3.1).

available_on_hand = sum(remaining_qty of AVAILABLE lots of the component)
Component.on_hand_qty = round_half_up(available_on_hand - reserved_qty, 3)

physical_on_hand (traceability only) = sum over AVAILABLE+QUARANTINED lots,
ignoring reservations. Not stored; the component's on_hand_qty is the available
view. QUARANTINED lots are excluded from on_hand_qty.
"""
import db
import util


def recompute_component_on_hand(component):
    """Recompute and store Component.on_hand_qty from its AVAILABLE lots,
    less reserved_qty, rounded half up to 3 decimals."""
    cid = component["id"]
    available = 0.0
    for lot in db.component_lots.values():
        if lot["component_id"] == cid and lot["status"] == "AVAILABLE":
            available += lot["remaining_qty"]
    reserved = component.get("reserved_qty", 0)
    component["on_hand_qty"] = util.round_half_up(available - reserved, 3)


def add_reserved(component, qty):
    """Increase reserved_qty and recompute on_hand."""
    component["reserved_qty"] = util.round_half_up(component.get("reserved_qty", 0) + qty, 3)
    recompute_component_on_hand(component)


def release_reserved(component, qty):
    """Decrease reserved_qty (never below 0) and recompute on_hand."""
    new_reserved = component.get("reserved_qty", 0) - qty
    if new_reserved < 0:
        new_reserved = 0
    component["reserved_qty"] = util.round_half_up(new_reserved, 3)
    recompute_component_on_hand(component)
