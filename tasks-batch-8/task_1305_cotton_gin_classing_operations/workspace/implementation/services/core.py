"""Core helpers: entity creation, touch/version, ledger posting, pagination."""

from db import db, new_id, now_iso
from response import success_list


def stamp_new(entity):
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version by exactly 1."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def post_ledger(grower_id, season, entry_type, amount_cents, memo, settlement_id=None):
    entry = {
        "id": new_id(),
        "created_at": now_iso(),
        "grower_id": grower_id,
        "settlement_id": settlement_id,
        "season": season,
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "memo": memo,
    }
    db.ledger_entries[entry["id"]] = entry
    recompute_grower_balance(grower_id)
    return entry


def recompute_grower_balance(grower_id):
    grower = db.growers.get(grower_id)
    if grower is None:
        return
    total = sum(
        e["amount_cents"]
        for e in db.ledger_entries.values()
        if e["grower_id"] == grower_id
    )
    grower["credit_balance_cents"] = total


def recompute_warehouse_count(warehouse_id):
    wh = db.warehouses.get(warehouse_id)
    if wh is None:
        return
    count = sum(
        1
        for r in db.warehouse_receipts.values()
        if r["warehouse_id"] == warehouse_id and r["status"] in ("ACTIVE", "PLEDGED", "RELEASED")
    )
    wh["stored_bale_count"] = count


def sorted_entities(entities, order_ids=None):
    """Sort by created_at ascending. If order_ids given, use that explicit order."""
    if order_ids is not None:
        return entities  # caller has already ordered
    return sorted(entities, key=lambda e: (e["created_at"], e["id"]))


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(page, limit, offset, total)
