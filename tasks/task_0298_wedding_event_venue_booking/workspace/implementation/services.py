"""Business logic: charge calculations, milestone waterfall, payment-status
derivation, refunds, and cross-entity cascades.

All money is integer cents. Rounding is round-half-up at each named step.
"""
from datetime import timedelta

from db import store, new_id
from common import (
    pct_of, round_half_up, now_iso, stamp_create, touch, clock_now, clock_date,
)

# --- System constants -------------------------------------------------------
HOLD_DURATION_HOURS = 6          # PRD §3.3 soft-hold window
GUARANTEE_WINDOW_DAYS = 14       # PRD §3.7 guarantee_deadline = event_date - window
DEPOSIT_PCT = 0.25               # milestone split
INTERIM_PCT = 0.35

# Cancellation retention table: tier -> booking_status_at_cancel -> fraction
RETENTION_TABLE = {
    "STANDARD": {"HELD": 0.00, "CONFIRMED": 0.25, "GUARANTEED": 0.50},
    "STRICT":   {"HELD": 0.00, "CONFIRMED": 0.50, "GUARANTEED": 1.00},
    "FLEXIBLE": {"HELD": 0.00, "CONFIRMED": 0.00, "GUARANTEED": 0.25},
}

BOOKING_TERMINAL = {"COMPLETED", "CANCELLED"}


# ===========================================================================
# Event charge (dual variant)
# ===========================================================================
def _distinct_space_rental(booking_id, hold_statuses):
    """Sum base_rental_cents over DISTINCT spaces among this booking's holds
    whose hold_status is in hold_statuses."""
    seen = set()
    total = 0
    for h in store.space_holds.values():
        if h["booking_id"] != booking_id:
            continue
        if h["hold_status"] not in hold_statuses:
            continue
        space_id = h["space_id"]
        if space_id in seen:
            continue
        seen.add(space_id)
        space = store.spaces.get(space_id)
        if space:
            total += space["base_rental_cents"]
    return total


def _fb_and_charge(billable_heads, package, rental):
    fb_subtotal = max(billable_heads * package["per_head_cents"], package["fb_minimum_cents"])
    service = pct_of(fb_subtotal, package["service_charge_pct"])
    tax = pct_of(fb_subtotal + service, package["tax_pct"])
    return fb_subtotal + service + tax + rental


def provisional_event_charge(booking):
    """Provisional charge: expected_guest_count, holds HELD|COMMITTED (PRD §3.4)."""
    package = store.packages[booking["package_id"]]
    rental = _distinct_space_rental(booking["id"], {"HELD", "COMMITTED"})
    return _fb_and_charge(booking["expected_guest_count"], package, rental)


def final_event_charge(booking, guaranteed_count):
    """Final charge: guaranteed_count, COMMITTED holds only (PRD §3.7)."""
    package = store.packages[booking["package_id"]]
    rental = _distinct_space_rental(booking["id"], {"COMMITTED"})
    return _fb_and_charge(guaranteed_count, package, rental)


# ===========================================================================
# Milestone schedule + waterfall allocation
# ===========================================================================
def build_milestones(booking):
    """Create the three milestones from the current event_charge_cents (PRD §3.5).
    Called at confirmation."""
    total = booking["event_charge_cents"]
    deposit = pct_of(total, DEPOSIT_PCT)
    interim = pct_of(total, INTERIM_PCT)
    final = total - deposit - interim

    due_date = clock_date().isoformat()  # deposit due_date defaults to confirmation date
    specs = [
        ("DEPOSIT", 1, deposit),
        ("INTERIM", 2, interim),
        ("FINAL", 3, final),
    ]
    for kind, seq, amount in specs:
        m = {
            "id": new_id(),
            "booking_id": booking["id"],
            "kind": kind,
            "sequence": seq,
            "amount_due_cents": amount,
            "amount_allocated_cents": 0,
            "due_date": due_date,
            "milestone_status": "OPEN",
        }
        stamp_create(m)
        store.milestones[m["id"]] = m


def recompute_milestone_amounts(booking):
    """Recompute the three milestone amount_due_cents from the current event charge
    (called at guarantee). Preserves milestone identity/due_date."""
    total = booking["event_charge_cents"]
    deposit = pct_of(total, DEPOSIT_PCT)
    interim = pct_of(total, INTERIM_PCT)
    final = total - deposit - interim
    amounts = {1: deposit, 2: interim, 3: final}
    for m in _booking_milestones(booking["id"]):
        if m["milestone_status"] == "WAIVED":
            continue
        m["amount_due_cents"] = amounts[m["sequence"]]
        touch(m)


def _booking_milestones(booking_id):
    return sorted(
        (m for m in store.milestones.values() if m["booking_id"] == booking_id),
        key=lambda m: m["sequence"],
    )


def _posted_inbound_minus_outbound(booking_id):
    """Net inbound = sum(INBOUND POSTED) - sum(OUTBOUND POSTED)."""
    net = 0
    for p in store.payments.values():
        if p["booking_id"] != booking_id or p["status"] != "POSTED":
            continue
        if p["direction"] == "INBOUND":
            net += p["amount_cents"]
        else:
            net -= p["amount_cents"]
    return net


def allocate_waterfall(booking):
    """Allocate net inbound money across non-WAIVED milestones in ascending
    sequence, deriving each milestone_status (PRD §3.5)."""
    net = max(_posted_inbound_minus_outbound(booking["id"]), 0)
    for m in _booking_milestones(booking["id"]):
        if m["milestone_status"] == "WAIVED":
            continue
        due = m["amount_due_cents"]
        new_alloc = min(net, due)
        net -= new_alloc
        # derive status from the new allocation
        if due > 0 and new_alloc >= due:
            new_status = "SETTLED"
        elif new_alloc > 0:
            new_status = "PARTIAL"
        else:
            new_status = "OPEN"
        changed = (
            m["amount_allocated_cents"] != new_alloc
            or m["milestone_status"] != new_status
        )
        m["amount_allocated_cents"] = new_alloc
        m["milestone_status"] = new_status
        if changed:
            touch(m)


# ===========================================================================
# Derived booking money fields + payment_status
# ===========================================================================
def amount_paid(booking_id):
    return _posted_inbound_minus_outbound(booking_id)


def recompute_money(booking):
    """Refresh amount_paid_cents and balance_due_cents (derived from payment stream)."""
    booking["amount_paid_cents"] = amount_paid(booking["id"])
    booking["balance_due_cents"] = booking["event_charge_cents"] - booking["amount_paid_cents"]


def deposit_milestone(booking_id):
    for m in store.milestones.values():
        if m["booking_id"] == booking_id and m["kind"] == "DEPOSIT":
            return m
    return None


def provisional_deposit_amount(booking):
    """The deposit amount (25% of the provisional charge), used to recognize a
    settled deposit BEFORE confirmation builds the milestone schedule."""
    charge = provisional_event_charge(booking)
    return pct_of(charge, DEPOSIT_PCT)


def recompute_payment_status(booking):
    """Recompute payment_status from milestone allocation + paid totals (PRD §3.5).

    Bumps booking.version when payment_status changes.
    """
    paid = booking["amount_paid_cents"]
    charge = booking["event_charge_cents"]
    milestones = _booking_milestones(booking["id"])
    dep = deposit_milestone(booking["id"])

    all_settled_or_waived = bool(milestones) and all(
        m["milestone_status"] in ("SETTLED", "WAIVED") for m in milestones
    )

    if dep is not None:
        deposit_settled = dep["milestone_status"] == "SETTLED"
        deposit_due = dep["amount_due_cents"]
    else:
        # Pre-confirmation: no milestone yet. Use the provisional deposit threshold
        # so a deposit paid while HELD lands the booking at DEPOSIT_PAID.
        deposit_due = provisional_deposit_amount(booking)
        deposit_settled = paid >= deposit_due and deposit_due > 0

    new_status = booking["payment_status"]
    cancelled = booking["booking_status"] == "CANCELLED"

    if cancelled and paid == 0 and booking["payment_status"] in (
        "DEPOSIT_PAID", "PARTIALLY_PAID", "PAID_IN_FULL"
    ):
        # refund netted inbound to zero on a cancelled booking
        new_status = "REFUNDED"
    elif charge > 0 and paid >= charge and all_settled_or_waived:
        new_status = "PAID_IN_FULL"
    elif deposit_settled and charge > 0 and paid > deposit_due and paid < charge:
        new_status = "PARTIALLY_PAID"
    elif deposit_settled:
        new_status = "DEPOSIT_PAID"
    elif paid > 0:
        # money posted but deposit threshold not yet met; keep prior axis state
        new_status = booking["payment_status"]
    else:
        new_status = "UNPAID"

    if new_status != booking["payment_status"]:
        booking["payment_status"] = new_status
        touch(booking)


def settle_and_status(booking):
    """Full settlement recompute pipeline after any payment / milestone change."""
    recompute_money(booking)
    allocate_waterfall(booking)
    recompute_money(booking)
    recompute_payment_status(booking)


# ===========================================================================
# Refund (cancellation) calculation
# ===========================================================================
def cancellation_refund_amount(booking, status_at_cancel):
    venue = store.venues[booking["venue_id"]]
    tier = venue["cancellation_tier"]
    paid = booking["amount_paid_cents"]  # net inbound pre-refund
    retention_pct = RETENTION_TABLE[tier].get(status_at_cancel, 0.0)
    retained = pct_of(paid, retention_pct)
    refund = paid - retained
    return refund


def post_outbound_payment(booking, amount_cents):
    """Post an OUTBOUND refund Payment for amount_cents (>0)."""
    p = {
        "id": new_id(),
        "booking_id": booking["id"],
        "direction": "OUTBOUND",
        "amount_cents": amount_cents,
        "method": "ACH",
        "status": "POSTED",
        "posted_at": now_iso(),
    }
    # Payment has common_fields false: only id + created_at, no version/updated_at.
    p["created_at"] = now_iso()
    p["_seq"] = store.next_seq()
    store.payments[p["id"]] = p
    return p


# ===========================================================================
# Coordinator load
# ===========================================================================
def coordinator_active_count(coordinator_id):
    return sum(
        1 for b in store.bookings.values()
        if b["coordinator_id"] == coordinator_id
        and b["booking_status"] not in BOOKING_TERMINAL
    )


def refresh_coordinator_count(coordinator_id):
    if coordinator_id is None:
        return
    coord = store.coordinators.get(coordinator_id)
    if coord is None:
        return
    coord["assigned_active_count"] = coordinator_active_count(coordinator_id)


# ===========================================================================
# Guarantee deadline
# ===========================================================================
def guarantee_deadline_for(event_date_str):
    from common import parse_date
    ed = parse_date(event_date_str, "event_date")
    return (ed - timedelta(days=GUARANTEE_WINDOW_DAYS)).isoformat()


# ===========================================================================
# Space-date overlap (with turnover buffer)
# ===========================================================================
def _interval_overlaps_with_buffer(start_a, end_a, start_b, end_b, buffer_minutes):
    """True if [start_a, end_a] and [start_b, end_b] collide once each interval's
    end is extended by buffer_minutes. Adjacency with a gap >= buffer is allowed."""
    buf = timedelta(minutes=buffer_minutes)
    # A occupies [start_a, end_a + buf); B occupies [start_b, end_b + buf).
    # They conflict unless one ends (with buffer) at or before the other starts.
    return not (end_a + buf <= start_b or end_b + buf <= start_a)


def space_conflict(space_id, occupy_start, occupy_end, exclude_booking_id=None):
    """Return True if occupying [occupy_start, occupy_end] on space_id collides with
    any OTHER booking's blocking hold (HELD or COMMITTED) on the same space."""
    space = store.spaces.get(space_id)
    buffer_minutes = space["turnover_buffer_minutes"] if space else 0
    for h in store.space_holds.values():
        if h["space_id"] != space_id:
            continue
        if h["hold_status"] not in ("HELD", "COMMITTED"):
            continue
        if exclude_booking_id is not None and h["booking_id"] == exclude_booking_id:
            continue
        from common import parse_datetime
        h_start = parse_datetime(h["occupy_start"], "occupy_start")
        h_end = parse_datetime(h["occupy_end"], "occupy_end")
        if _interval_overlaps_with_buffer(occupy_start, occupy_end, h_start, h_end, buffer_minutes):
            return True
    return False
