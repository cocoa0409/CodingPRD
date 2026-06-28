"""Cross-entity domain operations and cascades.

These helpers are reused across routes: recomputing derived driver/host fields,
the violation-creation cascade, the suspension cascade, and ledger posting.

Every mutation of a versioned resource calls db.touch(rec) so updated_at and version
advance (PRD §2.4 / §2.5).
"""
from db import db, make_versioned, make_lightweight, touch
from services import calculations as calc


# --------------------------------------------------------------------------- #
# Driver derived fields
# --------------------------------------------------------------------------- #
def recompute_provisional_points(driver):
    """Driver.provisional_violation_points = sum over OPEN records of
    base_points * KIND_WEIGHT (escalation fixed at neutral)."""
    total = 0
    for v in db.violations.values():
        if v["driver_id"] == driver["id"] and v["status"] == "OPEN":
            total += calc.provisional_points_for(v["violation_kind"], v["base_points"])
    driver["provisional_violation_points"] = total


def recompute_lifetime_payout(host):
    """Host.lifetime_payout_cents = sum of amount_cents over EARNING + REVERSAL rows."""
    total = 0
    for e in db.ledger_entries.values():
        if e["host_id"] == host["id"] and e["entry_type"] in ("EARNING", "REVERSAL"):
            total += e["amount_cents"]
    host["lifetime_payout_cents"] = total


# --------------------------------------------------------------------------- #
# Violation creation (manual and auto-logged cascades)
# --------------------------------------------------------------------------- #
def create_violation(booking, violation_kind, base_points):
    """Create an OPEN ViolationRecord; driver_id copied from booking. Re-derive the
    driver's provisional points. Returns the new record."""
    rec = make_versioned(
        {
            "booking_id": booking["id"],
            "driver_id": booking["driver_id"],
            "violation_kind": violation_kind,
            "base_points": base_points,
            "status": "OPEN",
            "assessed_points": None,
        }
    )
    db.violations[rec["id"]] = rec
    driver = db.drivers[booking["driver_id"]]
    recompute_provisional_points(driver)
    touch(driver)  # provisional_violation_points changed -> mutation
    return rec


# --------------------------------------------------------------------------- #
# Ledger posting
# --------------------------------------------------------------------------- #
def post_earning(booking, gross_cents):
    """Post a PayoutLedgerEntry(EARNING) for the spot's host; recompute lifetime payout."""
    spot = db.spots[booking["spot_id"]]
    host = db.hosts[spot["host_id"]]
    net = calc.host_net_earning(gross_cents, host["platform_fee_bps"])
    entry = make_lightweight(
        {
            "host_id": host["id"],
            "booking_id": booking["id"],
            "entry_type": "EARNING",
            "amount_cents": net,
        }
    )
    db.ledger_entries[entry["id"]] = entry
    recompute_lifetime_payout(host)
    touch(host)  # lifetime_payout_cents changed -> mutation
    return entry


def post_reversal(booking, earning_entry):
    """Post a REVERSAL that is the exact negation of the original EARNING."""
    host = db.hosts[earning_entry["host_id"]]
    entry = make_lightweight(
        {
            "host_id": host["id"],
            "booking_id": booking["id"],
            "entry_type": "REVERSAL",
            "amount_cents": -earning_entry["amount_cents"],
        }
    )
    db.ledger_entries[entry["id"]] = entry
    recompute_lifetime_payout(host)
    touch(host)
    return entry


def earning_for_booking(booking_id):
    """Return the single EARNING entry for a booking, or None."""
    for e in db.ledger_entries.values():
        if e["booking_id"] == booking_id and e["entry_type"] == "EARNING":
            return e
    return None


def reversal_for_booking(booking_id):
    for e in db.ledger_entries.values():
        if e["booking_id"] == booking_id and e["entry_type"] == "REVERSAL":
            return e
    return None


# --------------------------------------------------------------------------- #
# Refund helper (used by cancel, suspension auto-cancel)
# --------------------------------------------------------------------------- #
def refund_to_wallet(booking, driver, clock_now):
    """Compute tiered refund of the frozen quote by lead time and credit the wallet."""
    lead_seconds = (booking["_start_at_dt"] - clock_now).total_seconds()
    refund = calc.refund_amount(booking["quoted_amount_cents"], lead_seconds)
    driver["wallet_balance_cents"] += refund
    return refund


# --------------------------------------------------------------------------- #
# Suspension cascade (from violation confirm)
# --------------------------------------------------------------------------- #
def apply_suspension_cascade(driver, clock_now):
    """When a driver becomes SUSPENDED, auto-cancel every RESERVED booking they hold:
    occupancy_status -> CANCELLED, settlement_status -> REFUNDED, tiered refund credited.
    RESERVED bookings carry no posted host EARNING, so no reversal on this path."""
    for booking in db.bookings.values():
        if booking["driver_id"] == driver["id"] and booking["occupancy_status"] == "RESERVED":
            booking["occupancy_status"] = "CANCELLED"
            booking["settlement_status"] = "REFUNDED"
            refund_to_wallet(booking, driver, clock_now)
            touch(booking)
