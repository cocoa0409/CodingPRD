"""Business logic: calculations, operability posture, cascades, clock sweeps.

Implements the five calculation rules (§3) and the cross-entity state machinery.
All money is integer cents; the single rounding point is per-line settlement
discount, ROUND_HALF_UP before summing (PRD §2.9, §3.7).
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db
from clock import parse_iso, now_iso

# ---- Constants (SCAFFOLD 1.3 / PRD §3.8, §3.4, §3.7) ----
MIN_OPERATING_PSI = 20
GENERATOR_SERVICE_HOURS = 100
CANCEL_CUTOFF_MINUTES = 120
HAPPY_HOUR_PCT = Decimal("0.15")
BULK10_PCT = Decimal("0.10")
BULK10_MIN_QTY = 10


# ==========================================================================
# Derived-field calculations
# ==========================================================================
def docked_truck_count(commissary_id):
    """Count of trucks docked here whose operability != GROUNDED (§3.1)."""
    return sum(
        1 for t in db.trucks.values()
        if t["commissary_id"] == commissary_id and t["operability"] != "GROUNDED"
    )


def reservation_fee_balance(truck_id):
    """reservation_fee_balance (§2.8, calc reservation_fee_balance).

    sum(reservation_fee_cents for bookings in {RESERVED,ARRIVED,DEPARTED,NO_SHOW})
    minus sum(fee_refunded_cents for CANCELLED bookings).
    """
    kept = 0
    refunded = 0
    for b in db.bookings.values():
        if b["truck_id"] != truck_id:
            continue
        if b["status"] in ("RESERVED", "ARRIVED", "DEPARTED", "NO_SHOW"):
            kept += b["reservation_fee_cents"]
        elif b["status"] == "CANCELLED":
            refunded += b["fee_refunded_cents"]
    bal = kept - refunded
    return bal if bal > 0 else 0


def prepared_units(menu_item_id):
    """prepared_units ledger (§3.5, calc prepared_units_ledger).

    sum(units_made over OPEN batches) - sum(quantity over lines of SETTLED orders).
    """
    made = sum(
        pb["units_made"] for pb in db.prep_batches.values()
        if pb["menu_item_id"] == menu_item_id and pb["status"] == "OPEN"
    )
    consumed = 0
    for ln in db.order_lines.values():
        if ln["menu_item_id"] != menu_item_id:
            continue
        order = db.orders.get(ln["order_id"])
        if order is not None and order["lifecycle_status"] == "SETTLED":
            consumed += ln["quantity"]
    return made - consumed


def compute_live_total(order):
    """order_live_total (§3.6): sum(quantity*unit_price) + tip; ignores discount."""
    subtotal = 0
    for ln in db.order_lines.values():
        if ln["order_id"] == order["id"]:
            subtotal += ln["quantity"] * ln["unit_price_cents"]
    return subtotal + order["tip_cents"]


def compute_settled_total(order, discount_code):
    """order_settled_total (§3.7): per-line discount, round half-up, then sum + tip."""
    discounted_subtotal = 0
    for ln in db.order_lines.values():
        if ln["order_id"] != order["id"]:
            continue
        raw_line = ln["quantity"] * ln["unit_price_cents"]
        if discount_code == "HAPPY_HOUR":
            disc_line = _round_half_up(Decimal(raw_line) * (Decimal(1) - HAPPY_HOUR_PCT))
        elif discount_code == "BULK10" and ln["quantity"] >= BULK10_MIN_QTY:
            disc_line = _round_half_up(Decimal(raw_line) * (Decimal(1) - BULK10_PCT))
        else:
            disc_line = raw_line
        discounted_subtotal += disc_line
    return discounted_subtotal + order["tip_cents"]


def _round_half_up(value):
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ==========================================================================
# Operability posture (calc operability_posture, §2.5, §3.8)
# ==========================================================================
def _shift_covers_now(shift, now):
    if shift["status"] != "SCHEDULED":
        return False
    s = parse_iso(shift["shift_start"])
    e = parse_iso(shift["shift_end"])
    return s <= now < e


def compute_operability(truck):
    """Return the derived operability value for a truck at the current clock."""
    now = db.clock

    # HARD GATES
    commissary = db.commissaries.get(truck["commissary_id"])
    h1 = commissary is not None and commissary["status"] == "ACTIVE"

    active_permits = [
        p for p in db.permits.values()
        if p["truck_id"] == truck["id"] and p["status"] == "ACTIVE"
        and now < parse_iso(p["expires_at"])
    ]
    h2 = len(active_permits) == 1

    if not (h1 and h2):
        return "GROUNDED"

    # SOFT GATES
    s1 = truck["propane_psi"] >= MIN_OPERATING_PSI

    has_driver = any(
        sh["truck_id"] == truck["id"] and sh["role"] == "DRIVER"
        and _shift_covers_now(sh, now)
        for sh in db.staff_shifts.values()
    )
    has_cook = any(
        sh["truck_id"] == truck["id"] and sh["role"] == "COOK"
        and _shift_covers_now(sh, now)
        for sh in db.staff_shifts.values()
    )
    s2 = has_driver and has_cook

    s3 = truck["generator_runtime_hours"] < GENERATOR_SERVICE_HOURS

    if s1 and s2 and s3:
        return "OPERABLE"
    return "RESTRICTED"


def recompute_operability(truck):
    """Recompute operability and write the truck row.

    Any recompute that writes the truck row is a mutation: it bumps version and
    refreshes updated_at (§2.4, §2.6) even when operability is unchanged. When a
    truck transitions from a non-GROUNDED posture to GROUNDED, the booking
    cancellation cascade fires (§2.6).
    """
    old = truck["operability"]
    new = compute_operability(truck)
    truck["operability"] = new
    db.touch(truck)
    if old != "GROUNDED" and new == "GROUNDED":
        _cascade_ground_truck(truck)


def _cascade_ground_truck(truck):
    """On a drop to GROUNDED, cancel future RESERVED bookings with full refund."""
    now = db.clock
    for b in db.bookings.values():
        if b["truck_id"] != truck["id"]:
            continue
        if b["status"] != "RESERVED":
            continue
        if parse_iso(b["window_start"]) > now:
            b["status"] = "CANCELLED"
            b["fee_refunded_cents"] = b["reservation_fee_cents"]
            db.touch(b)


# ==========================================================================
# Order VOID cascade helper (§3.7)
# ==========================================================================
def void_order(order):
    """Transition an OPEN order to VOID, refunding payment if CAPTURED."""
    order["lifecycle_status"] = "VOID"
    if order["payment_status"] == "CAPTURED":
        order["payment_status"] = "REFUNDED"
    db.touch(order)


def has_open_order_under_booking(booking_id):
    return any(
        o["booking_id"] == booking_id and o["lifecycle_status"] == "OPEN"
        for o in db.orders.values()
    )


# ==========================================================================
# Clock sweeps (§3.10): permit expiry + booking NO_SHOW
# ==========================================================================
def run_clock_sweeps():
    """Apply expiry/no-show sweeps at the current db.clock.

    Returns (swept_permit_ids, swept_booking_ids).
    Permit expiry recomputes the owning truck (which may cascade-cancel its
    future RESERVED bookings). NO_SHOW forfeits the fee.
    """
    now = db.clock
    swept_permit_ids = []
    swept_booking_ids = []

    # 1) Expire ACTIVE permits whose expires_at <= now.
    affected_trucks = set()
    for p in db.permits.values():
        if p["status"] == "ACTIVE" and now >= parse_iso(p["expires_at"]):
            p["status"] = "EXPIRED"
            db.touch(p)
            swept_permit_ids.append(p["id"])
            affected_trucks.add(p["truck_id"])

    for truck_id in affected_trucks:
        truck = db.trucks.get(truck_id)
        if truck is not None:
            recompute_operability(truck)

    # 2) NO_SHOW: RESERVED bookings whose window_end <= now (fee forfeited).
    for b in db.bookings.values():
        if b["status"] == "RESERVED" and now >= parse_iso(b["window_end"]):
            b["status"] = "NO_SHOW"
            db.touch(b)
            swept_booking_ids.append(b["id"])

    return swept_permit_ids, swept_booking_ids
