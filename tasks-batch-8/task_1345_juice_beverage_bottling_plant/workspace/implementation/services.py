"""Shared business logic: cascades, reservations, pallet postings, sweeps."""
from datetime import timedelta

from domain import (OPEN_ORDER_STATES, PALLET_AGING_DAYS, STALE_ORDER_GRACE_DAYS,
                    UNITS_PER_PALLET, ceil_div)
from store import db, stamp_append_only, touch


# ------------------------------------------------------------ containers
def release_run_reservations(run):
    """Release every container unit this run still holds reserved."""
    for entry in run["_reservations"]:
        lot = db.container_lots.get(entry["lot_id"])
        if lot is None or entry["units"] <= 0:
            continue
        lot["quantity_reserved"] -= entry["units"]
        touch(lot)
    run["_reservations"] = []


# ------------------------------------------------------------ batch condemn cascade
def condemn_cascade(batch):
    """Full four-hop cascade for a batch entering CONDEMNED."""
    # Hop 1: live process runs of this batch are aborted.
    for pr in db.process_runs.values():
        if pr["batch_id"] == batch["id"] and pr["status"] in ("SCHEDULED", "RUNNING", "DEVIATED"):
            pr["status"] = "ABORTED"
            touch(pr)
    # Hop 2: the reserving production run in SCHEDULED is demoted.
    run_id = batch.get("linked_run_id")
    if run_id:
        run = db.runs.get(run_id)
        if run is not None and run["production_status"] == "SCHEDULED":
            run["production_status"] = "BLOCKED_SUPPLY"
            touch(run)
            # Hop 3: container reservations released (window freed by state change).
            release_run_reservations(run)
        batch["linked_run_id"] = None
    # Tank hop: if still occupied by this batch, it now awaits CIP.
    tank = db.tanks.get(batch["tank_id"])
    if tank is not None and tank["posture"] == "OCCUPIED" and tank.get("occupying_batch_id") == batch["id"]:
        tank["posture"] = "AWAITING_CIP"
        tank["occupying_batch_id"] = None
        touch(tank)


# ------------------------------------------------------------ finished-lot de-allocation cascade
def deallocate_lot_from_open_orders(lot):
    """Strip allocations referencing this lot from PLACED/ALLOCATED/BACKORDERED
    orders; demote any that fall short. Returns number of orders demoted."""
    demoted = 0
    for order in db.orders.values():
        if order["status"] not in ("PLACED", "ALLOCATED", "BACKORDERED"):
            continue  # PICKED orders keep allocations; the ship gate stops them
        before = [a for a in order["allocations"] if a["lot_id"] == lot["id"]]
        if not before:
            continue
        stripped = sum(a["units"] for a in before)
        order["allocations"] = [a for a in order["allocations"] if a["lot_id"] != lot["id"]]
        lot["units_allocated"] -= stripped
        allocated = sum(a["units"] for a in order["allocations"])
        if order["status"] == "ALLOCATED" and allocated < order["units_requested"]:
            order["status"] = "BACKORDERED"
            demoted += 1
        touch(order)
    return demoted


# ------------------------------------------------------------ pallet ledger
def post_pallet_entry(account, entry_type, pallet_count, shipment_order_id=None):
    entry = {
        "pallet_account_id": account["id"],
        "entry_type": entry_type,
        "pallet_count": pallet_count,
        "shipment_order_id": shipment_order_id,
        "entry_date": db.clock.date().isoformat(),
        "_entry_date": db.clock.date(),
    }
    if entry_type == "SHIP":
        account["pallets_out_total"] += pallet_count
    elif entry_type == "RETURN":
        account["pallets_returned_total"] += pallet_count
    elif entry_type == "CONVERSION":
        account["pallets_converted_total"] += pallet_count
    outstanding = (account["pallets_out_total"] - account["pallets_returned_total"]
                   - account["pallets_converted_total"])
    entry["running_balance"] = outstanding
    stamp_append_only(entry)
    db.pallet_entries[entry["id"]] = entry
    touch(account)
    return entry


# ------------------------------------------------------------ housekeeping epoch
def run_ops_epoch():
    ran_at = db.clock
    current_date = ran_at.date()
    lots_expired = 0
    orders_backordered = 0
    orders_cancelled = 0
    customers_suspended = 0
    pallets_converted = 0

    # Sweep 1: credit — suspend ACTIVE customers strictly over their limit.
    for customer in db.customers.values():
        if customer["status"] == "ACTIVE" and \
                customer["outstanding_balance_cents"] > customer["credit_limit_cents"]:
            customer["status"] = "SUSPENDED"
            touch(customer)
            customers_suspended += 1

    # Sweep 2: stale orders — PLACED/BACKORDERED more than 7 days past delivery date.
    for order in db.orders.values():
        if order["status"] not in ("PLACED", "BACKORDERED"):
            continue
        delivery = order["_requested_delivery_date"]
        if delivery + timedelta(days=STALE_ORDER_GRACE_DAYS) < current_date:
            for alloc in order["allocations"]:
                lot = db.fg_lots.get(alloc["lot_id"])
                if lot is not None:
                    lot["units_allocated"] -= alloc["units"]
                    touch(lot)
            order["allocations"] = []
            order["status"] = "CANCELLED"
            touch(order)
            orders_cancelled += 1

    # Sweep 3: lot expiry — label date, equality expires.
    for lot in db.fg_lots.values():
        if lot["status"] != "AVAILABLE":
            continue
        if current_date >= lot["_expiry_label_date"]:
            lot["status"] = "EXPIRED"
            lots_expired += 1
            orders_backordered += deallocate_lot_from_open_orders(lot)
            touch(lot)

    # Sweep 4: pallet aging — convert SHIP entries aged >= 30 days (net of returns).
    for account in db.pallet_accounts.values():
        entries = [e for e in db.pallet_entries.values()
                   if e["pallet_account_id"] == account["id"]]
        entries.sort(key=lambda e: (e["entry_date"], e["_seq"]))
        ships = [e for e in entries if e["entry_type"] == "SHIP"]
        returns_remaining = account["pallets_returned_total"]
        conversions_remaining = account["pallets_converted_total"]
        cutoff = current_date - timedelta(days=PALLET_AGING_DAYS)
        for ship in ships:
            netted_returns = min(ship["pallet_count"], returns_remaining)
            returns_remaining -= netted_returns
            after_returns = ship["pallet_count"] - netted_returns
            netted_conversions = min(after_returns, conversions_remaining)
            conversions_remaining -= netted_conversions
            net_outstanding = after_returns - netted_conversions
            if net_outstanding > 0 and ship["_entry_date"] <= cutoff:
                post_pallet_entry(account, "CONVERSION", net_outstanding)
                pallets_converted += net_outstanding

    record = {
        "ran_at": _iso(ran_at),
        "lots_expired_count": lots_expired,
        "orders_backordered_count": orders_backordered,
        "orders_cancelled_count": orders_cancelled,
        "customers_suspended_count": customers_suspended,
        "pallets_converted_count": pallets_converted,
    }
    stamp_append_only(record)
    db.ops_runs[record["id"]] = record
    return record


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
