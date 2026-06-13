"""Business-logic services: recomputation, cascades, allocation, time parsing."""
from datetime import datetime, timezone

import calc
import store
from store import soft_touch, touch


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO 8601 datetime (accepts trailing 'Z'). Returns aware UTC dt."""
    if value is None:
        raise ValueError("missing datetime")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def current_clock_dt():
    """The simulated clock as an aware datetime; falls back to real now if unset."""
    if store.clock_utc is None:
        return datetime.now(timezone.utc)
    return parse_iso(store.clock_utc)


# ---------------------------------------------------------------------------
# Children lookups (sorted by created sequence for determinism)
# ---------------------------------------------------------------------------
def guests_of(booking_id):
    items = [g for g in store.guests.values() if g["booking_id"] == booking_id]
    items.sort(key=lambda g: g["_seq"])
    return items


def cabins_of_category(cabin_category_id):
    items = [c for c in store.cabins.values() if c["cabin_category_id"] == cabin_category_id]
    items.sort(key=lambda c: c["_seq"])
    return items


def cabins_of_block(group_block_id):
    items = [c for c in store.cabins.values() if c.get("group_block_id") == group_block_id]
    items.sort(key=lambda c: c["_seq"])
    return items


def payments_of(booking_id):
    return [p for p in store.payments.values() if p["booking_id"] == booking_id]


def charges_of_folio(folio_id):
    return [c for c in store.folio_charges.values() if c["folio_id"] == folio_id]


# ---------------------------------------------------------------------------
# Guest fare assessment + booking totals + deposit schedule (PRD §3.4)
# ---------------------------------------------------------------------------
def recompute_booking_finances(booking):
    """Re-derive per-guest fares and the booking roll-ups in place.

    The group discount only materializes when the booking is CONFIRMED and
    carries a group_block_id (PRD §3.4). Each guest mutation and the booking
    mutation are version-bumped by callers as appropriate; here we bump the
    affected resources since recomputation is itself a mutation (PRD §2.4/§2.6).
    """
    category = store.cabin_categories[booking["cabin_category_id"]]
    base_fare = category["base_fare_per_guest_cents"]

    apply_group = (
        booking["status"] == "CONFIRMED" and booking.get("group_block_id") is not None
    )
    group_discount_pct = 0
    if booking.get("group_block_id") is not None:
        block = store.group_blocks.get(booking["group_block_id"])
        if block is not None:
            group_discount_pct = block["group_discount_pct"]

    roster = guests_of(booking["id"])
    fare_total = 0
    tax_total = 0
    for idx, g in enumerate(roster, start=1):
        new_occ = idx
        new_base = calc.base_fare_for_index(base_fare, new_occ)
        new_final = calc.final_fare_for(new_base, apply_group, group_discount_pct)
        new_tax = calc.tax_port_for(new_final)
        if (
            g.get("occupancy_index") != new_occ
            or g.get("base_fare_cents") != new_base
            or g.get("final_fare_cents") != new_final
            or g.get("tax_port_cents") != new_tax
        ):
            g["occupancy_index"] = new_occ
            g["base_fare_cents"] = new_base
            g["final_fare_cents"] = new_final
            g["tax_port_cents"] = new_tax
            touch(g)
        fare_total += new_final
        tax_total += new_tax

    booking_total = fare_total + tax_total
    guest_count = len(roster)
    deposit_due, final_due = calc.deposit_schedule(booking_total, guest_count)

    changed = (
        booking.get("guest_count") != guest_count
        or booking.get("fare_total_cents") != fare_total
        or booking.get("tax_port_total_cents") != tax_total
        or booking.get("booking_total_cents") != booking_total
        or booking.get("deposit_due_cents") != deposit_due
        or booking.get("final_due_cents") != final_due
    )
    booking["guest_count"] = guest_count
    booking["fare_total_cents"] = fare_total
    booking["tax_port_total_cents"] = tax_total
    booking["booking_total_cents"] = booking_total
    booking["deposit_due_cents"] = deposit_due
    booking["final_due_cents"] = final_due
    if changed:
        touch(booking)


def projected_final_total(booking):
    """Compute the booking_total under the CONFIRMED (final-fare) variant without
    mutating anything. Used by the confirm balance gate, since the group discount
    is applied on confirmation (PRD §3.4/§3.5)."""
    category = store.cabin_categories[booking["cabin_category_id"]]
    base_fare = category["base_fare_per_guest_cents"]
    apply_group = booking.get("group_block_id") is not None
    group_discount_pct = 0
    if apply_group:
        block = store.group_blocks.get(booking["group_block_id"])
        if block is not None:
            group_discount_pct = block["group_discount_pct"]
        else:
            apply_group = False
    fare_total = 0
    tax_total = 0
    for idx, _g in enumerate(guests_of(booking["id"]), start=1):
        base = calc.base_fare_for_index(base_fare, idx)
        final = calc.final_fare_for(base, apply_group, group_discount_pct)
        fare_total += final
        tax_total += calc.tax_port_for(final)
    return fare_total + tax_total


def recompute_amount_paid(booking):
    """amount_paid = sum CAPTURED deposit/final - sum REFUNDED refunds (PRD §3.4)."""
    total = 0
    for p in payments_of(booking["id"]):
        if p["status"] == "CAPTURED" and p["kind"] in ("DEPOSIT", "FINAL"):
            total += p["amount_cents"]
        elif p["status"] == "REFUNDED":
            total -= p["amount_cents"]
    if booking.get("amount_paid_cents") != total:
        booking["amount_paid_cents"] = total
        touch(booking)


# ---------------------------------------------------------------------------
# Category & sailing cabin-count roll-ups (PRD §2.6)
# ---------------------------------------------------------------------------
def recompute_category_counts(category):
    cabins = cabins_of_category(category["id"])
    total = len(cabins)
    available = sum(1 for c in cabins if c["status"] == "AVAILABLE")
    held = sum(1 for c in cabins if c["status"] == "HELD")
    assigned = sum(1 for c in cabins if c["status"] == "ASSIGNED")
    blocked = sum(1 for c in cabins if c["status"] == "BLOCKED")
    changed = (
        category.get("total_cabins") != total
        or category.get("available_cabins") != available
        or category.get("held_cabins") != held
        or category.get("assigned_cabins") != assigned
        or category.get("blocked_cabins") != blocked
    )
    category["total_cabins"] = total
    category["available_cabins"] = available
    category["held_cabins"] = held
    category["assigned_cabins"] = assigned
    category["blocked_cabins"] = blocked
    if changed:
        soft_touch(category)


def recompute_sailing_counts(sailing):
    cats = [c for c in store.cabin_categories.values() if c["sailing_id"] == sailing["id"]]
    total = sum(c["total_cabins"] for c in cats)
    available = sum(c["available_cabins"] for c in cats)
    changed = (
        sailing.get("total_cabins") != total
        or sailing.get("available_cabins") != available
    )
    sailing["total_cabins"] = total
    sailing["available_cabins"] = available
    if changed:
        soft_touch(sailing)


def recompute_sailing_rollup(sailing):
    """Refresh every category of a sailing, then the sailing totals."""
    for cat in [c for c in store.cabin_categories.values() if c["sailing_id"] == sailing["id"]]:
        recompute_category_counts(cat)
    recompute_sailing_counts(sailing)


# ---------------------------------------------------------------------------
# Group block counts (PRD §2.6 / §3.2)
# ---------------------------------------------------------------------------
def recompute_block_counts(block):
    blocked = sum(
        1
        for c in store.cabins.values()
        if c["status"] == "BLOCKED" and c.get("group_block_id") == block["id"]
    )
    materialized = sum(
        1
        for b in store.bookings.values()
        if b.get("group_block_id") == block["id"]
        and b["status"] not in ("CANCELLED", "EXPIRED")
    )
    changed = (
        block.get("blocked_count") != blocked
        or block.get("materialized_count") != materialized
    )
    block["blocked_count"] = blocked
    block["materialized_count"] = materialized
    if changed:
        soft_touch(block)


# ---------------------------------------------------------------------------
# Folio roll-ups (PRD §3.7)
# ---------------------------------------------------------------------------
def recompute_folio(folio):
    booking = store.bookings[folio["booking_id"]]
    sailing = store.sailings[booking["sailing_id"]]
    guest_count = booking["guest_count"]
    gratuity = calc.gratuity_total(guest_count, sailing["nights"])
    charges_total = sum(
        c["amount_cents"] for c in charges_of_folio(folio["id"]) if c["status"] == "POSTED"
    )
    # No folio-level payments are modelled separately; folio_payments_applied = 0.
    balance = charges_total + gratuity
    changed = (
        folio.get("charges_total_cents") != charges_total
        or folio.get("gratuity_total_cents") != gratuity
        or folio.get("balance_due_cents") != balance
    )
    folio["charges_total_cents"] = charges_total
    folio["gratuity_total_cents"] = gratuity
    folio["balance_due_cents"] = balance
    if changed:
        touch(folio)


# ---------------------------------------------------------------------------
# Cabin allocation / release
# ---------------------------------------------------------------------------
def hold_cabin_for_booking(booking):
    """Pick and HOLD a cabin for a booking reaching DEPOSIT_HELD (PRD §3.5)."""
    category = store.cabin_categories[booking["cabin_category_id"]]
    chosen = None
    if booking.get("group_block_id") is not None:
        for c in cabins_of_block(booking["group_block_id"]):
            if c["status"] == "BLOCKED":
                chosen = c
                break
    else:
        for c in cabins_of_category(category["id"]):
            if c["status"] == "AVAILABLE":
                chosen = c
                break
    if chosen is None:
        return None
    chosen["status"] = "HELD"
    chosen["booking_id"] = booking["id"]
    touch(chosen)
    booking["cabin_id"] = chosen["id"]
    recompute_category_counts(category)
    recompute_sailing_counts(store.sailings[category["sailing_id"]])
    return chosen


def release_held_cabin(booking):
    """Release a HELD cabin back to its prior pool on revise (PRD §3.5)."""
    if booking.get("cabin_id") is None:
        return
    cabin = store.cabins[booking["cabin_id"]]
    category = store.cabin_categories[cabin["cabin_category_id"]]
    if cabin.get("group_block_id") is not None:
        cabin["status"] = "BLOCKED"
    else:
        cabin["status"] = "AVAILABLE"
    cabin["booking_id"] = None
    touch(cabin)
    booking["cabin_id"] = None
    recompute_category_counts(category)
    recompute_sailing_counts(store.sailings[category["sailing_id"]])


def release_cabin_on_cancel(booking):
    """Release a HELD or ASSIGNED cabin on cancellation (PRD §3.8 cascade)."""
    if booking.get("cabin_id") is None:
        return
    cabin = store.cabins[booking["cabin_id"]]
    category = store.cabin_categories[cabin["cabin_category_id"]]
    if cabin.get("group_block_id") is not None:
        cabin["status"] = "BLOCKED"
    else:
        cabin["status"] = "AVAILABLE"
    cabin["booking_id"] = None
    touch(cabin)
    booking["cabin_id"] = None
    recompute_category_counts(category)
    recompute_sailing_counts(store.sailings[category["sailing_id"]])


# ---------------------------------------------------------------------------
# Folio voiding (PRD §3.7)
# ---------------------------------------------------------------------------
def folio_for_booking(booking_id):
    for f in store.folios.values():
        if f["booking_id"] == booking_id:
            return f
    return None


def void_folio(booking):
    folio = folio_for_booking(booking["id"])
    if folio is None or folio["status"] != "OPEN":
        return
    for charge in charges_of_folio(folio["id"]):
        if charge["status"] == "POSTED":
            charge["status"] = "REVERSED"
            touch(charge)
    # Recompute against the now-reversed charges (charges_total_cents -> 0),
    # then flip status to VOID.
    recompute_folio(folio)
    folio["status"] = "VOID"
    touch(folio)
