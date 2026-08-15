"""Pool availability reconciliation and the reorder threshold engine
(PRD §2.6, §3.2)."""
from datetime import timedelta

from db import db, clock, stamp, touch
from services.orders import units_committed_map


def available(pool):
    return (
        pool["stock_on_hand"]
        - pool["reserved_quantity"]
        - pool["in_laundry_quantity"]
    )


def reconcile_pool(pool, direction, prev_available):
    """Recompute availability, refresh updated_at, bump version by 1, then run
    the reorder threshold check. direction is "decrease" or "increase"."""
    pool["available_quantity"] = available(pool)
    touch(pool)
    threshold_check(pool, direction, prev_available)


def threshold_check(pool, direction, prev_available):
    """Edge-triggered on the DECREASE direction only (PRD §3.2): fires when the
    available quantity was strictly above reorder_point before and lands at or
    below it after. Increase-direction reconciliations can only clear a
    previously set reorder_blocked flag."""
    reorder_point = pool["reorder_point"]
    new_available = pool["available_quantity"]
    if direction == "decrease":
        if prev_available > reorder_point and new_available <= reorder_point:
            fire_reorder(pool)
    else:
        if pool["reorder_blocked"] and new_available > reorder_point:
            pool["reorder_blocked"] = False


def fire_reorder(pool):
    """Forward-looking reorder variant (authoritative): subtracts inbound open
    order units from the shortfall, adds the batch size, clamps to the selected
    contract's remaining allocation."""
    inbound_open = 0
    for order in db.orders.values():
        if order["status"] not in OPEN_FOR_INBOUND:
            continue
        contract = db.contracts.get(order["supplier_contract_id"])
        if contract is None or contract["season_label"] != pool["season_label"]:
            continue
        for line in order["lines"]:
            if (
                line["garment_type"] == pool["garment_type"]
                and line["size_code"] == pool["size_code"]
            ):
                inbound_open += line["quantity"]

    candidates = [
        c
        for c in db.contracts.values()
        if c["status"] == "ACTIVE"
        and c["season_label"] == pool["season_label"]
        and any(cap["garment_type"] == pool["garment_type"] for cap in c["allocation_caps"])
    ]
    # created_at ASC, tie-break vendor_name ASC (insertion seq final for
    # determinism when the logical clock ties both)
    candidates.sort(key=lambda c: (c["created_at"], c["vendor_name"], c["_seq"]))
    if not candidates:
        pool["reorder_blocked"] = True
        return

    contract = candidates[0]
    committed = units_committed_map(contract)
    cap = next(
        cap["max_units"]
        for cap in contract["allocation_caps"]
        if cap["garment_type"] == pool["garment_type"]
    )
    remaining = cap - committed.get(pool["garment_type"], 0)
    qty_raw = (
        pool["reorder_point"] - pool["available_quantity"] - inbound_open
    ) + pool["reorder_batch_size"]
    qty = min(qty_raw, remaining)
    if qty <= 0:
        pool["reorder_blocked"] = True
        return

    order = stamp(
        {
            "supplier_contract_id": contract["id"],
            "source": "AUTO_REORDER",
            "status": "SUBMITTED",
            "lines": [
                {
                    "garment_type": pool["garment_type"],
                    "size_code": pool["size_code"],
                    "quantity": qty,
                    "unit_price_cents": 0,
                    "line_discount_pct": 0,
                }
            ],
            "received_lines": [],
            "expected_delivery_on": (
                clock().date() + timedelta(days=contract["default_lead_time_days"])
            ).isoformat(),
            "subtotal_cents": 0,
            "total_cents": 0,
        }
    )
    db.orders[order["id"]] = order


OPEN_FOR_INBOUND = ("SUBMITTED", "PARTIALLY_RECEIVED")


def kit_pool_pairs(kit):
    """(pool, units) pairs for a kit's jersey/pants pools, aggregating when both
    reference the same pool."""
    jersey = db.pools.get(kit["jersey_pool_id"])
    pants = db.pools.get(kit["pants_pool_id"])
    if jersey is not None and pants is not None and jersey["id"] == pants["id"]:
        return [(jersey, 2)]
    return [(p, 1) for p in (jersey, pants) if p is not None]
