"""Business logic: calculations, cascades, serialization (PRD §3, §1.3).

All money is integer cents; percentage-derived charges use Decimal with
ROUND_HALF_UP, applied independently per component in the pinned order
(service charge, gratuity, sales tax).
"""
import math
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

import db

# Setup-style seating factors (PRD §3.4 / effective_room_capacity).
SETUP_FACTOR = {
    "ROUNDS": Decimal("0.6"),
    "THEATER": Decimal("1.0"),
    "CLASSROOM": Decimal("0.5"),
    "RECEPTION": Decimal("0.8"),
}


def round_half_up_cents(value):
    """Round a Decimal to the nearest whole cent, half rounds up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Mutation bookkeeping: bump version + updated_at on a common-fields entity.
# ---------------------------------------------------------------------------
def touch(entity):
    if "version" in entity:
        entity["version"] += 1
    if "updated_at" in entity:
        entity["updated_at"] = db.now_iso()


def touch_no_version(entity):
    """Refresh updated_at without bumping version. Used for the Event's own
    derived-field reconciliations (lifecycle transitions and line edits): the
    Event.version field is the OCC token and per PRD §2.7 is incremented ONLY by
    booking-create and payment-record, the two endpoints carrying the
    expected_event_version guard."""
    if "updated_at" in entity:
        entity["updated_at"] = db.now_iso()


# ---------------------------------------------------------------------------
# billable_count (§1.3 / PRD §3.5)
# ---------------------------------------------------------------------------
def billable_count(event):
    status = event["status"]
    guarantee = event["guarantee_count"]
    actual = event["actual_attendance"]
    if status == "COMPLETED":
        # actualized: max(guarantee, actual); overset dropped entirely.
        g = guarantee if guarantee is not None else 0
        a = actual if actual is not None else 0
        return max(g, a)
    elif guarantee is not None:
        # guarantee locked (CONFIRMED+): oversetted guarantee, rounded up.
        inflated = Decimal(guarantee) * (Decimal(1) + Decimal(str(event["overset_pct"])))
        return int(math.ceil(inflated))
    else:
        # pre-guarantee estimate.
        return event["expected_attendance"]


# ---------------------------------------------------------------------------
# menu_line_extended (§1.3 / PRD §3.7)
# ---------------------------------------------------------------------------
def menu_line_extended(line, event):
    if line["pricing_mode"] == "PER_PERSON":
        return line["unit_price_cents"] * billable_count(event)
    else:  # CONSUMPTION
        return line["unit_price_cents"] * line["consumption_qty"]


def recompute_menu_line(line, event):
    new_val = menu_line_extended(line, event)
    if line["extended_cents"] != new_val:
        line["extended_cents"] = new_val
        touch(line)
    else:
        line["extended_cents"] = new_val


# ---------------------------------------------------------------------------
# room_rental (§1.3 / PRD §3.3)
# ---------------------------------------------------------------------------
def room_rental(booking, room):
    if booking["hold_status"] == "RELEASED":
        return 0
    start = parse_dt(booking["start_utc"])
    end = parse_dt(booking["end_utc"])
    duration_minutes = (end - start).total_seconds() / 60.0
    billed_hours = math.ceil(duration_minutes / 60.0)
    return billed_hours * room["hourly_rental_cents"]


def parse_dt(value):
    v = value
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    return datetime.fromisoformat(v)


# ---------------------------------------------------------------------------
# effective_room_capacity (§1.3 / PRD §3.4)
# ---------------------------------------------------------------------------
def effective_room_capacity(room, event):
    factor = SETUP_FACTOR[event["setup_style"]]
    return int(math.floor(Decimal(room["max_capacity"]) * factor))


# ---------------------------------------------------------------------------
# charge_rollup (§1.3 / PRD §3.7)
# ---------------------------------------------------------------------------
def charge_rollup(event):
    """Compute the grand total in integer cents for the event's current state.

    Per-person menu lines read the event's current billable_count, so the
    caller selects ESTIMATE vs ACTUAL by setting event status/guarantee/actual
    before calling. Returns the integer grand total.
    """
    lines = [m for m in db.menu_lines.values() if m["event_id"] == event["id"]]
    svc = [s for s in db.service_lines.values() if s["event_id"] == event["id"]]
    bks = [b for b in db.bookings.values() if b["event_id"] == event["id"]]

    fnb_subtotal = sum(menu_line_extended(m, event) for m in lines)
    service_subtotal = sum(s["extended_cents"] for s in svc)
    gratuity_base = fnb_subtotal + sum(
        s["extended_cents"] for s in svc if s["gratuity_eligible"]
    )
    rental_subtotal = sum(
        b["rental_charge_cents"] for b in bks if b["hold_status"] != "RELEASED"
    )

    service_charge = round_half_up_cents(
        Decimal(gratuity_base) * Decimal(str(event["service_charge_pct"]))
    )
    gratuity = round_half_up_cents(
        Decimal(gratuity_base) * Decimal(str(event["gratuity_pct"]))
    )
    taxable_base = fnb_subtotal + service_subtotal + rental_subtotal + service_charge
    sales_tax = round_half_up_cents(
        Decimal(taxable_base) * Decimal(str(event["sales_tax_pct"]))
    )
    grand_total = (
        fnb_subtotal + service_subtotal + rental_subtotal
        + service_charge + gratuity + sales_tax
    )
    return grand_total


# ---------------------------------------------------------------------------
# payment_waterfall (§1.3 / PRD §3.8)
# ---------------------------------------------------------------------------
def paid_to_date(event):
    return sum(
        p["amount_cents"]
        for p in db.payments.values()
        if p["event_id"] == event["id"] and p["status"] == "APPLIED"
    )


def run_waterfall(event):
    """Recompute every schedule item's allocated_cents and settled flag.

    Items mutated (allocated_cents/settled changes) each refresh updated_at and
    bump version independently (PRD §2.5).
    """
    pool = paid_to_date(event)
    items = sorted(
        (i for i in db.payment_schedule_items.values() if i["event_id"] == event["id"]),
        key=lambda i: i["sequence_no"],
    )
    for item in items:
        take = min(pool, item["amount_due_cents"])
        new_settled = take >= item["amount_due_cents"]
        if item["allocated_cents"] != take or item["settled"] != new_settled:
            item["allocated_cents"] = take
            item["settled"] = new_settled
            touch(item)
        pool -= take


def deposit_item(event):
    """The schedule item with sequence_no == 1, or None."""
    for i in db.payment_schedule_items.values():
        if i["event_id"] == event["id"] and i["sequence_no"] == 1:
            return i
    return None


# ---------------------------------------------------------------------------
# rooms_committed for a hotel room block (§1.3 / PRD §3.6)
# ---------------------------------------------------------------------------
def block_rooms_committed(block):
    total = 0
    for link in db.room_block_links.values():
        if link["hotel_room_block_id"] != block["id"]:
            continue
        if link["link_status"] == "RESERVED":
            total += link["rooms_reserved"]
        elif link["link_status"] == "PICKED_UP":
            total += link["rooms_picked_up"] if link["rooms_picked_up"] is not None else 0
        # RELEASED contributes 0
    return total


# ---------------------------------------------------------------------------
# Event derived-figure recomputation.
# ---------------------------------------------------------------------------
def recompute_estimated_total(event):
    """Estimate rollup — writes estimated_total_cents. Not run on terminal
    events whose totals are frozen (CANCELLED/COMPLETED handled by callers)."""
    event["estimated_total_cents"] = charge_rollup(event)


def active_total(event):
    if event["status"] == "COMPLETED":
        return event["actualized_total_cents"]
    return event["estimated_total_cents"]


def recompute_balance(event):
    total = active_total(event)
    if total is None:
        total = 0
    event["balance_due_cents"] = total - paid_to_date(event)


# ===========================================================================
# Serialization — produce the public JSON for each entity.
# ===========================================================================
def serialize_function_room(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "max_capacity": r["max_capacity"],
        "turnover_buffer_minutes": r["turnover_buffer_minutes"],
        "hourly_rental_cents": r["hourly_rental_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_hotel_room_block(b):
    committed = block_rooms_committed(b)
    available = b["total_rooms"] - committed
    if available < 0:
        available = 0
    return {
        "id": b["id"],
        "block_name": b["block_name"],
        "total_rooms": b["total_rooms"],
        "nightly_rate_cents": b["nightly_rate_cents"],
        "rooms_committed": committed,
        "rooms_available": available,
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_event(e):
    return {
        "id": e["id"],
        "account_name": e["account_name"],
        "event_date": e["event_date"],
        "setup_style": e["setup_style"],
        "expected_attendance": e["expected_attendance"],
        "guarantee_count": e["guarantee_count"],
        "actual_attendance": e["actual_attendance"],
        "overset_pct": e["overset_pct"],
        "service_charge_pct": e["service_charge_pct"],
        "gratuity_pct": e["gratuity_pct"],
        "sales_tax_pct": e["sales_tax_pct"],
        "status": e["status"],
        "billable_count": billable_count(e),
        "estimated_total_cents": e["estimated_total_cents"],
        "actualized_total_cents": e["actualized_total_cents"],
        "paid_to_date_cents": paid_to_date(e),
        "balance_due_cents": _balance_for_read(e),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def _balance_for_read(e):
    total = active_total(e)
    if total is None:
        total = 0
    return total - paid_to_date(e)


def serialize_booking(b):
    return {
        "id": b["id"],
        "event_id": b["event_id"],
        "function_room_id": b["function_room_id"],
        "start_utc": b["start_utc"],
        "end_utc": b["end_utc"],
        "setup_diagram_url": b["setup_diagram_url"],
        "hold_status": b["hold_status"],
        "rental_charge_cents": b["rental_charge_cents"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_menu_line(m):
    return {
        "id": m["id"],
        "event_id": m["event_id"],
        "name": m["name"],
        "pricing_mode": m["pricing_mode"],
        "unit_price_cents": m["unit_price_cents"],
        "consumption_qty": m["consumption_qty"],
        "extended_cents": m["extended_cents"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def serialize_service_line(s):
    return {
        "id": s["id"],
        "event_id": s["event_id"],
        "category": s["category"],
        "description": s["description"],
        "quantity": s["quantity"],
        "unit_price_cents": s["unit_price_cents"],
        "gratuity_eligible": s["gratuity_eligible"],
        "extended_cents": s["extended_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_room_block_link(l):
    return {
        "id": l["id"],
        "event_id": l["event_id"],
        "hotel_room_block_id": l["hotel_room_block_id"],
        "rooms_reserved": l["rooms_reserved"],
        "check_in_date": l["check_in_date"],
        "check_out_date": l["check_out_date"],
        "rooms_picked_up": l["rooms_picked_up"],
        "link_status": l["link_status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def serialize_payment_schedule_item(i):
    return {
        "id": i["id"],
        "event_id": i["event_id"],
        "label": i["label"],
        "due_date": i["due_date"],
        "amount_due_cents": i["amount_due_cents"],
        "sequence_no": i["sequence_no"],
        "allocated_cents": i["allocated_cents"],
        "settled": i["settled"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def serialize_payment(p):
    return {
        "id": p["id"],
        "event_id": p["event_id"],
        "amount_cents": p["amount_cents"],
        "method": p["method"],
        "status": p["status"],
        "created_at": p["created_at"],
    }
