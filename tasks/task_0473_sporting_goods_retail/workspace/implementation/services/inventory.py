"""Inventory pool accounting (PRD §2.5).

available_qty = on_hand_qty - reserved_qty, recomputed on every reserve / commit
/ release. Counters never go negative.
  reserve(n): reserved_qty += n            (on_hand unchanged)
  commit(n):  on_hand_qty -= n; reserved_qty -= n
  release(n): reserved_qty -= n            (on_hand unchanged)
Each mutation bumps the row's own updated_at + version (cascade independence,
PRD §2.4).
"""

from db import db, now_ts


def recompute_available(row):
    row["available_qty"] = row["on_hand_qty"] - row["reserved_qty"]


def _touch(row):
    row["updated_at"] = now_ts()
    row["version"] += 1


def find_row(store_id, sku_id):
    for row in db.store_inventory.values():
        if row["store_id"] == store_id and row["sku_id"] == sku_id:
            return row
    return None


def reserve(row, qty):
    row["reserved_qty"] += qty
    recompute_available(row)
    _touch(row)


def commit(row, qty):
    row["on_hand_qty"] -= qty
    row["reserved_qty"] -= qty
    recompute_available(row)
    _touch(row)


def release(row, qty):
    row["reserved_qty"] -= qty
    recompute_available(row)
    _touch(row)
