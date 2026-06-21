"""Shared business-logic helpers: lookups, ledger recompute, cascades."""
import db
from errors import not_found, referenced_not_found


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(store, _id):
    rec = store.get(_id)
    if rec is None:
        raise not_found()
    return rec


def get_or_ref_404(store, _id):
    rec = store.get(_id)
    if rec is None:
        raise referenced_not_found()
    return rec


# ---------------------------------------------------------------------------
# Booking ledger recompute
# ---------------------------------------------------------------------------
def recompute_amount_paid(booking):
    """amount_paid = sum(CAPTURED amounts) - sum(REFUNDED amounts) for this
    booking."""
    captured = 0
    refunded = 0
    for p in db.payments.values():
        if p["booking_id"] != booking["id"]:
            continue
        if p["capture_status"] == "CAPTURED":
            captured += p["amount_cents"]
        if p["settlement_status"] == "REFUNDED":
            refunded += p["amount_cents"]
    booking["amount_paid_cents"] = captured - refunded


def recompute_balance(booking):
    """balance_due = (final_total if PERFORMED-or-later else quote_total)
    - amount_paid.

    Pre-PERFORMED bookings have final_total_cents == 0, so the basis is the
    quote total; once a set is performed, final_total_cents is set and becomes
    the basis.
    """
    if booking["status"] in ("PERFORMED", "SETTLED"):
        basis = booking["final_total_cents"]
    else:
        basis = booking["quote_total_cents"]
    booking["balance_due_cents"] = basis - booking["amount_paid_cents"]


def refresh_ledger(booking):
    recompute_amount_paid(booking)
    recompute_balance(booking)


# ---------------------------------------------------------------------------
# Equipment / package helpers
# ---------------------------------------------------------------------------
def equipment_unit_fees_for_package(package_id):
    """Unit fees for every equipment line whose package_id matches, ordered by
    insertion sequence (sum is order-independent, but kept stable)."""
    rows = [e for e in db.equipment_items.values()
            if e["package_id"] == package_id]
    rows.sort(key=lambda e: e.get("_seq", 0))
    return [e["unit_fee_cents"] for e in rows]
