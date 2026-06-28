"""Inventory helpers: bin volume accounting, pallet exclusivity, lot upsert.

The three derived lot quantities maintain on_hand = reserved + available at all
times (PRD §2.8). We store on_hand_qty and reserved_qty; available_qty is derived
(on_hand - reserved) at serialization. occupied_cc is always recomputed from lots.
"""
from db import store, touch
from serializers import compute_bin_occupied_cc


def bin_occupied_cc(bin_id):
    return compute_bin_occupied_cc(bin_id)


def bin_holds_other_client(bin_id, client_id):
    """True if this bin holds >= 1 unit of a DIFFERENT client's inventory.

    "holds" means a lot with on_hand_qty > 0 (a different client's units present).
    """
    for lot in store.inventory_lots.values():
        if lot["bin_id"] == bin_id and lot["client_id"] != client_id and lot["on_hand_qty"] > 0:
            return True
    return False


def find_or_create_lot(client_id, sku_id, bin_id, receipt_id):
    """Find an existing lot for the exact (client, sku, bin, receipt) combo, else create.

    Used by putaway, which keys on the originating receipt_id (PRD §3.2).
    """
    for lot in store.inventory_lots.values():
        if (
            lot["client_id"] == client_id
            and lot["sku_id"] == sku_id
            and lot["bin_id"] == bin_id
            and lot["receipt_id"] == receipt_id
        ):
            return lot
    return None


def find_restock_lot(client_id, sku_id, bin_id):
    """Find an existing lot for (client, sku, bin) — used by sellable-return restock.

    The return restock keys on (client_id, sku_id, bin_id) per PRD §3.9.
    """
    for lot in store.inventory_lots.values():
        if (
            lot["client_id"] == client_id
            and lot["sku_id"] == sku_id
            and lot["bin_id"] == bin_id
        ):
            return lot
    return None
