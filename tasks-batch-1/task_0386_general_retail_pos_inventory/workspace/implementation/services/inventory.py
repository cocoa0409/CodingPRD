"""Inventory derived-field reconciliation (PRD §2.9, calc F)."""
from common import touch


def recompute(item):
    """available_qty = on_hand_qty - reserved_qty; below_reorder = available <= reorder_point.

    PRD §2.9: the comparison is inclusive at the threshold. Recomputing a derived
    field is a mutation (PRD §2.4): it refreshes updated_at and bumps version.
    """
    item["available_qty"] = item["on_hand_qty"] - item["reserved_qty"]
    item["below_reorder"] = item["available_qty"] <= item["reorder_point"]
    touch(item)


def find_item(db, store_id, product_id):
    for it in db.inventory_items.values():
        if it["store_id"] == store_id and it["product_id"] == product_id:
            return it
    return None
