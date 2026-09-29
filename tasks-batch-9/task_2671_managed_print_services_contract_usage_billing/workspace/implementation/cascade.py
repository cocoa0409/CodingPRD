"""Multi-row cascades: read acceptance, auto-replenishment, void reversal,
order cancellation and the removal-order sanitization chain (PRD 2.6)."""
import calc
import derive
from store import db, new_row, touch


# ------------------------------------------------------------ order creation ---
def create_order(device, part_type, quantity, unit_price_cents, trigger_source):
    """Create a ConsumableOrder and snapshot the waste-control inputs."""
    snapshot = derive.pages_since_last_cartridge(device["id"])
    had_prior_delivery = any(o["status"] == "DELIVERED"
                             for o in derive.device_orders(device["id"]))
    row = new_row()
    row.update({
        "device_id": device["id"],
        "part_type": part_type,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "committed_cents": quantity * unit_price_cents,
        "status": "ORDERED",
        "trigger_source": trigger_source,
        "pages_since_last_cartridge_at_order": snapshot,
        "waste_flagged": bool(had_prior_delivery and snapshot < calc.MIN_CARTRIDGE_PAGES),
        "delivered_at": None,
        "cancel_reason": "NONE",
    })
    db.orders[row["id"]] = row
    return row


# --------------------------------------------------------- read acceptance ----
def _attempt_auto_replenishment(device, color_delta):
    """SUPPLY_LOW -> SUPPLY_ORDERED (order raised) or -> SUPPLY_BLOCKED."""
    site = derive.device_site(device)
    existing = derive.open_order_for_device(device["id"])
    cap_ok = True
    if site is not None:
        cap_ok = derive.open_toner_units(site["id"]) + 1 <= site["toner_unit_cap"]
    if existing is not None or not cap_ok:
        device["supply_state"] = "SUPPLY_BLOCKED"
        return None
    device["supply_state"] = "SUPPLY_ORDERED"
    if device["color_capable"] and color_delta > 0:
        part_type = "TONER_COLOR"
    else:
        part_type = "TONER_BLACK"
    return create_order(device, part_type, 1, calc.AUTO_TONER_UNIT_PRICE_CENTS,
                        "AUTO_THRESHOLD")


def accept_read(read, device, mono_delta, color_delta):
    """Hops 1-4 of the acceptance cascade."""
    read["status"] = "ACCEPTED"
    read["mono_delta"] = mono_delta
    read["color_delta"] = color_delta
    read["exception_reason"] = "NONE"

    device["last_accepted_mono_meter"] = read["mono_meter"]
    device["last_accepted_color_meter"] = read["color_meter"]
    device["last_read_at"] = read["coverage_end"]
    device["toner_level_pct"] = read["toner_level_pct"]

    if (device["toner_level_pct"] <= calc.TONER_REORDER_PCT
            and device["supply_state"] == "SUPPLY_OK"):
        device["supply_state"] = "SUPPLY_LOW"
        _attempt_auto_replenishment(device, color_delta)
    touch(device)


def reject_read(read, exception_reason):
    read["status"] = "EXCEPTION"
    read["exception_reason"] = exception_reason
    read["mono_delta"] = 0
    read["color_delta"] = 0


# --------------------------------------------------------------- void path ----
def void_read(read, device, voided_reason):
    """Walk the acceptance cascade backwards (PRD 3.4)."""
    read["status"] = "VOID"
    read["voided_reason"] = voided_reason
    read["mono_delta"] = 0
    read["color_delta"] = 0
    touch(read)

    remaining = derive.newest_accepted_read(device["id"])
    if remaining is None:
        device["last_accepted_mono_meter"] = 0
        device["last_accepted_color_meter"] = 0
        device["last_read_at"] = None
        device["toner_level_pct"] = 100
    else:
        device["last_accepted_mono_meter"] = remaining["mono_meter"]
        device["last_accepted_color_meter"] = remaining["color_meter"]
        device["last_read_at"] = remaining["coverage_end"]
        device["toner_level_pct"] = remaining["toner_level_pct"]

    if device["supply_state"] == "SUPPLY_ORDERED":
        order = derive.open_order_for_device(device["id"])
        if (order is not None and order["trigger_source"] == "AUTO_THRESHOLD"
                and device["toner_level_pct"] > calc.TONER_REORDER_PCT):
            order["status"] = "CANCELLED"
            order["cancel_reason"] = "READ_VOIDED"
            touch(order)
            device["supply_state"] = "SUPPLY_OK"
    touch(device)


# ------------------------------------------------------- order compensation ---
def cancel_order(order, device, cancel_reason):
    order["status"] = "CANCELLED"
    order["cancel_reason"] = cancel_reason
    touch(order)
    if device is None:
        return
    if derive.open_order_for_device(device["id"]) is not None:
        return
    if device["supply_state"] != "SUPPLY_ORDERED":
        return
    if device["toner_level_pct"] <= calc.TONER_REORDER_PCT:
        device["supply_state"] = "SUPPLY_LOW"
    else:
        device["supply_state"] = "SUPPLY_OK"
    touch(device)


def deliver_order(order, device):
    order["status"] = "DELIVERED"
    order["delivered_at"] = db.clock
    touch(order)
    if device is not None:
        if device["supply_state"] == "SUPPLY_ORDERED":
            device["supply_state"] = "SUPPLY_OK"
        touch(device)


# ---------------------------------------------------------- sanitize chain ----
def sanitize_devices(removal):
    """Hops 2-4: devices to REMOVED, then their open cartridge orders cancelled."""
    for device in derive.covered_devices(removal["id"]):
        if device["lifecycle_state"] != "RETRIEVED":
            continue
        device["lifecycle_state"] = "REMOVED"
        device["secure_release_enrolled"] = False
        touch(device)
        for order in derive.device_orders(device["id"]):
            if order["status"] != "ORDERED":
                continue
            order["status"] = "CANCELLED"
            order["cancel_reason"] = "DEVICE_REMOVED"
            touch(order)
