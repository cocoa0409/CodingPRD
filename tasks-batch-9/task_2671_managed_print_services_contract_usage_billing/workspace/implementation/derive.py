"""Derived (`source: computed`) fields, evaluated on read so they are never stale."""
from store import db

FLEET_STATES = ("PLACED", "NETWORKED", "ACTIVE", "SERVICE_HOLD")
IN_FLIGHT_TICKET_STATES = ("DISPATCHED", "PARTS_HOLD", "ONSITE")
OPEN_READ_STATES = ("PENDING_VALIDATION", "EXCEPTION")


# ---------------------------------------------------------------- lookups ----
def contract_of(row):
    return db.contracts.get(row.get("contract_id"))


def device_contract(device):
    return db.contracts.get(device.get("contract_id"))


def device_site(device):
    return db.sites.get(device.get("site_id"))


def contract_devices(contract_id):
    return [d for d in db.sorted_rows("devices") if d["contract_id"] == contract_id]


def device_reads(device_id):
    return [r for r in db.sorted_rows("meter_reads") if r["device_id"] == device_id]


def device_orders(device_id):
    return [o for o in db.sorted_rows("orders") if o["device_id"] == device_id]


def open_order_for_device(device_id):
    for order in device_orders(device_id):
        if order["status"] == "ORDERED":
            return order
    return None


def tier_rows(contract_id, page_class):
    rows = [t for t in db.sorted_rows("cost_tiers")
            if t["contract_id"] == contract_id and t["page_class"] == page_class]
    rows.sort(key=lambda t: (t["tier_index"], t["_seq"]))
    return rows


def tier1_rate(contract_id, page_class):
    """rate_micro_dollars_per_page of the tier_index 1 row, or 0 when absent."""
    for row in tier_rows(contract_id, page_class):
        if row["tier_index"] == 1:
            return row["rate_micro_dollars_per_page"]
    return 0


def statement_lines(statement_id):
    rows = [l for l in db.lines.values() if l["statement_id"] == statement_id]
    rows.sort(key=lambda l: l["_seq"])
    return rows


def period_statement(period_id, variant):
    for st in db.sorted_rows("statements"):
        if st["billing_period_id"] == period_id and st["variant"] == variant:
            return st
    return None


# --------------------------------------------------------------- contract ----
def active_device_count(contract_id):
    return len([d for d in db.devices.values()
                if d["contract_id"] == contract_id and d["lifecycle_state"] in FLEET_STATES])


def consumables_committed_cents(contract_id):
    total = 0
    for order in db.orders.values():
        if order["status"] != "ORDERED":
            continue
        device = db.devices.get(order["device_id"])
        if device is not None and device["contract_id"] == contract_id:
            total += order["committed_cents"]
    return total


# ------------------------------------------------------------------- site ----
def open_toner_units(site_id):
    total = 0
    for order in db.orders.values():
        if order["status"] != "ORDERED":
            continue
        device = db.devices.get(order["device_id"])
        if device is not None and device["site_id"] == site_id:
            total += order["quantity"]
    return total


def reserved_qty(site_id, part_sku):
    count = 0
    for ticket in db.tickets.values():
        if ticket["part_sku"] != part_sku:
            continue
        if ticket["status"] not in IN_FLIGHT_TICKET_STATES:
            continue
        device = db.devices.get(ticket["device_id"])
        if device is not None and device["site_id"] == site_id:
            count += 1
    return count


def stock_row(site_id, part_sku):
    for row in db.sorted_rows("stocks"):
        if row["site_id"] == site_id and row["part_sku"] == part_sku:
            return row
    return None


# ------------------------------------------------------------- technician ----
def open_dispatch_count(technician_id):
    return len([t for t in db.tickets.values()
                if t["assigned_technician_id"] == technician_id
                and t["status"] in IN_FLIGHT_TICKET_STATES])


# ----------------------------------------------------------------- device ----
def accepted_reads(device_id):
    return [r for r in device_reads(device_id) if r["status"] == "ACCEPTED"]


def lifetime_mono_pages(device_id):
    return sum(r["mono_delta"] for r in accepted_reads(device_id))


def lifetime_color_pages(device_id):
    return sum(r["color_delta"] for r in accepted_reads(device_id))


def latest_delivered_order(device_id):
    best = None
    for order in device_orders(device_id):
        if order["status"] != "DELIVERED" or order.get("delivered_at") is None:
            continue
        if best is None or (order["delivered_at"], order["_seq"]) >= (best["delivered_at"], best["_seq"]):
            best = order
    return best


def pages_since_last_cartridge(device_id):
    delivered = latest_delivered_order(device_id)
    reads = accepted_reads(device_id)
    if delivered is None:
        return sum(r["mono_delta"] + r["color_delta"] for r in reads)
    watermark = delivered["delivered_at"]
    return sum(r["mono_delta"] + r["color_delta"] for r in reads
               if r["coverage_end"] > watermark)


def offline_exception_count(device_id):
    return len([r for r in device_reads(device_id)
                if r["status"] == "EXCEPTION" and r["exception_reason"] == "DEVICE_OFFLINE"])


def waste_event_count(device_id):
    return len([o for o in device_orders(device_id)
                if o["waste_flagged"] and o["status"] != "CANCELLED"])


def newest_accepted_read(device_id, exclude_id=None):
    """Greatest coverage_end, created_at (then insertion order) breaking the tie."""
    best = None
    for read in accepted_reads(device_id):
        if exclude_id is not None and read["id"] == exclude_id:
            continue
        key = (read["coverage_end"], read["created_at"], read["_seq"])
        if best is None or key > (best["coverage_end"], best["created_at"], best["_seq"]):
            best = read
    return best


def device_in_flight_tickets(device_id):
    return [t for t in db.tickets.values()
            if t["device_id"] == device_id and t["status"] in IN_FLIGHT_TICKET_STATES]


# ----------------------------------------------------------------- period ----
def exception_open_count(period_id):
    return len([r for r in db.meter_reads.values()
                if r["billing_period_id"] == period_id and r["status"] in OPEN_READ_STATES])


def period_reads(period_id):
    return [r for r in db.sorted_rows("meter_reads") if r["billing_period_id"] == period_id]


def contract_periods(contract_id):
    return [p for p in db.sorted_rows("periods") if p["contract_id"] == contract_id]


def latest_closed_period(contract_id):
    """Greatest period_end among CLOSED periods; earliest created_at breaks a tie."""
    best = None
    for period in contract_periods(contract_id):
        if period["status"] != "CLOSED":
            continue
        if best is None:
            best = period
            continue
        if period["period_end"] > best["period_end"]:
            best = period
        elif period["period_end"] == best["period_end"]:
            if (period["created_at"], period["_seq"]) < (best["created_at"], best["_seq"]):
                best = period
    return best


def closed_periods_desc(contract_id):
    """CLOSED periods ordered by period_end DESC with created_at ASC as tiebreak."""
    rows = [p for p in contract_periods(contract_id) if p["status"] == "CLOSED"]
    rows.sort(key=lambda p: (p["created_at"], p["_seq"]))
    rows.sort(key=lambda p: p["period_end"], reverse=True)
    return rows


# ---------------------------------------------------------------- removal ----
def removal_device_count(removal_id):
    return len([d for d in db.devices.values() if d.get("removal_order_id") == removal_id])


def covered_devices(removal_id):
    return [d for d in db.sorted_rows("devices") if d.get("removal_order_id") == removal_id]
