"""Customer deposit ledger + rental inventory helpers (PRD §3.2, §3.4).

The deposit balance identity (PRD §3.2): at all times a customer's
deposit_balance_cents equals the sum of held_deposit_cents across that
customer's reservations in {HELD, CONFIRMED, CHECKED_IN}. Every capture,
release, or refund keeps this true and bumps the customer's version.
"""
from db import db, touch


def deposit_credit(customer, amount):
    """Add to held deposit balance (a capture). Bumps customer version."""
    if amount == 0:
        # Still a real ledger event? Capturing/releasing 0 keeps balance and
        # would needlessly bump version; skip the no-op mutation.
        return
    customer["deposit_balance_cents"] += amount
    touch(customer)


def deposit_debit(customer, amount):
    """Remove from held deposit balance (a release/apply). Bumps version."""
    if amount == 0:
        return
    customer["deposit_balance_cents"] -= amount
    touch(customer)


def deposit_release_with_wallet(customer, held, refund):
    """Release a held deposit and credit refund to wallet (cancel/expire path).

    Single customer mutation: debit deposit_balance by `held`, credit
    wallet_credit by `refund`. Bumps version once.
    """
    changed = False
    if held != 0:
        customer["deposit_balance_cents"] -= held
        changed = True
    if refund != 0:
        customer["wallet_credit_cents"] += refund
        changed = True
    if changed:
        touch(customer)


def deposit_reconcile_delta(customer, delta):
    """Reconcile deposit balance by a delta (revise re-pricing). Bumps version."""
    if delta != 0:
        customer["deposit_balance_cents"] += delta
        touch(customer)


def recompute_rental_item_counts(item):
    """available_count = total_count - out_on_rent_count; never negative.

    out_on_rent_count = sum of quantity over OPEN rental lines for this item.
    """
    out = 0
    for line in db.rental_lines.values():
        if line["rental_item_id"] == item["id"] and line["status"] == "OPEN":
            out += line["quantity"]
    item["out_on_rent_count"] = out
    item["available_count"] = max(0, item["total_count"] - out)


def return_open_rentals(reservation_id):
    """Return every OPEN rental line on a reservation, restoring availability.

    Used by cancel/expire cascades (PRD §3.6). Each rental line gets its own
    version bump per PRD §2.5. Returns list of affected item ids.
    """
    affected_items = set()
    for line in db.rental_lines.values():
        if line["reservation_id"] == reservation_id and line["status"] == "OPEN":
            line["status"] = "RETURNED"
            touch(line)
            affected_items.add(line["rental_item_id"])
    for item_id in affected_items:
        item = db.rental_items.get(item_id)
        if item:
            recompute_rental_item_counts(item)
    return affected_items
