"""Largest-remainder split (PRD §2.5).

Each recipient first receives the floor of its exact pro-rata share. The
leftover cents (amount minus sum of floors) are handed out one cent at a time
to the recipients with the largest fractional remainders. Ties broken by the
recipient commitment's created_at ASC, never by id.
"""
from decimal import Decimal


def largest_remainder_split(amount, recipients, weights):
    """Split `amount` (int cents) across recipients by `weights`.

    recipients: list of objects (dicts), each having a created_at for tie-break.
    weights: dict id -> weight (int). Recipients with total weight 0 should be
             excluded by the caller.

    Returns dict id -> allocated int cents. Sums exactly to `amount`.
    """
    total_weight = sum(weights[r["id"]] for r in recipients)
    if total_weight <= 0 or amount <= 0:
        return {r["id"]: 0 for r in recipients}

    raw = {}
    floors = {}
    fracs = {}
    for r in recipients:
        rid = r["id"]
        exact = Decimal(amount) * Decimal(weights[rid]) / Decimal(total_weight)
        floor_val = int(exact // 1)
        raw[rid] = exact
        floors[rid] = floor_val
        fracs[rid] = exact - Decimal(floor_val)

    allocated = dict(floors)
    leftover = amount - sum(floors.values())

    # Largest fractional remainder DESC; ties by created_at ASC (never id).
    order = sorted(
        recipients,
        key=lambda r: (-fracs[r["id"]], r["created_at"]),
    )
    for i in range(leftover):
        allocated[order[i]["id"]] += 1

    return allocated
