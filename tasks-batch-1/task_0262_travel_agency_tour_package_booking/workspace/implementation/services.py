"""Business logic: calculations, derived fields, and cascading state machines."""
from db import db, touch
from money import days_between_floor, round_half_up_div, subtract_days

# --- group_discount_price_per_person constants (calculations §1.3) ---
TIER_SMALL_PCT = 5
TIER_MID_PCT = 10
TIER_LARGE_PCT = 15
TIER_MID_MIN = 8
TIER_LARGE_MIN = 15

# --- insurance_premium constants ---
BASIC_RATE_CENTS = 1500
PREMIUM_RATE_CENTS = 4000

# --- cancellation_penalty constants ---
TIER_FREE_MIN_DAYS = 60
TIER_LOW_MIN_DAYS = 30
TIER_HIGH_MIN_DAYS = 7
TIER_LOW_PCT = 25
TIER_HIGH_PCT = 50
TIER_FULL_PCT = 100

# --- component overlap ---
BUFFER_SECONDS = 7200


# =========================================================================
# Per-person group discount pricing
# =========================================================================
def group_discount_subtotal(traveler_count, package):
    n = traveler_count
    base = package["base_price_per_person_cents"]
    min_group = package["min_group_size_for_discount"]
    if n < min_group:
        discount_pct = 0
    elif n < TIER_MID_MIN:
        discount_pct = TIER_SMALL_PCT
    elif n < TIER_LARGE_MIN:
        discount_pct = TIER_MID_PCT
    else:
        discount_pct = TIER_LARGE_PCT
    # PINNED ORDER: round per-person FIRST, THEN multiply by n.
    per_person = round_half_up_div(base * (100 - discount_pct), 100)
    return per_person * n


# =========================================================================
# Derived totals on a booking (used in DRAFT live quote + reserve freeze)
# =========================================================================
def active_insurance_premium(booking_id):
    total = 0
    for pol in db.insurance_policies.values():
        if pol["booking_id"] == booking_id and pol["status"] == "ACTIVE":
            total += pol["premium_cents"]
    return total


def booking_travelers(booking_id):
    return [t for t in db.travelers.values() if t["booking_id"] == booking_id]


def recompute_draft_quote(booking):
    """Recompute subtotal/insurance/grand_total against live roster (DRAFT)."""
    package = db.tour_packages[booking["tour_package_id"]]
    n = booking["traveler_count"]
    booking["subtotal_cents"] = group_discount_subtotal(n, package)
    booking["insurance_premium_cents"] = active_insurance_premium(booking["id"])
    booking["grand_total_cents"] = (
        booking["subtotal_cents"] + booking["insurance_premium_cents"]
    )


# =========================================================================
# Insurance premium
# =========================================================================
def compute_insurance_premium(traveler_count, coverage_tier):
    rate = BASIC_RATE_CENTS if coverage_tier == "BASIC" else PREMIUM_RATE_CENTS
    return traveler_count * rate


# =========================================================================
# Payment ledger derivations
# =========================================================================
def recompute_paid_cents(booking):
    total = 0
    for p in db.payments.values():
        if p["booking_id"] == booking["id"] and p["status"] == "APPLIED":
            total += p["amount_cents"]
    booking["paid_cents"] = total


def booking_milestones(booking_id):
    return [m for m in db.milestones.values() if m["booking_id"] == booking_id]


def milestone_by_kind(booking_id, kind):
    for m in db.milestones.values():
        if m["booking_id"] == booking_id and m["kind"] == kind:
            return m
    return None


def refresh_milestone_status(milestone):
    """SETTLED iff settled_amount_cents >= amount_due_cents; never un-waives."""
    if milestone["status"] == "WAIVED":
        return
    if milestone["settled_amount_cents"] >= milestone["amount_due_cents"]:
        milestone["status"] = "SETTLED"
    else:
        milestone["status"] = "OPEN"


def recompute_payment_status(booking):
    """payment_status_derivation (calculations §1.3)."""
    ms = booking_milestones(booking["id"])
    live = [m for m in ms if m["status"] in ("OPEN", "SETTLED")]
    if not live:
        booking["payment_status"] = "UNPAID"
        return
    deposit = milestone_by_kind(booking["id"], "DEPOSIT")
    balance = milestone_by_kind(booking["id"], "BALANCE")
    if balance is not None and balance["status"] == "SETTLED":
        booking["payment_status"] = "PAID_IN_FULL"
    elif deposit is not None and deposit["status"] == "SETTLED":
        booking["payment_status"] = "DEPOSIT_PAID"
    else:
        booking["payment_status"] = "UNPAID"


# =========================================================================
# Milestone generation at reserve
# =========================================================================
def generate_milestones(booking, package):
    """DEPOSIT round_half_up; BALANCE is the exact remainder."""
    grand = booking["grand_total_cents"]
    deposit_amount = round_half_up_div(grand * package["deposit_pct"], 100)
    balance_amount = grand - deposit_amount

    agency = db.agencies[booking["agency_id"]]
    deposit_due = agency["now_utc"]
    balance_due = subtract_days(
        booking["departure_date"], package["balance_due_days_before_departure"]
    )

    for kind, amount, due in (
        ("DEPOSIT", deposit_amount, deposit_due),
        ("BALANCE", balance_amount, balance_due),
    ):
        ms = {
            "booking_id": booking["id"],
            "kind": kind,
            "amount_due_cents": amount,
            "due_date": due,
            "settled_amount_cents": 0,
            "status": "OPEN",
        }
        from db import stamp_create

        stamp_create(ms)
        db.milestones[ms["id"]] = ms


# =========================================================================
# Cancellation penalty + refund
# =========================================================================
def cancellation_penalty(booking):
    agency = db.agencies[booking["agency_id"]]
    days = days_between_floor(agency["now_utc"], booking["departure_date"])
    if days >= TIER_FREE_MIN_DAYS:
        return "TIER_FREE", 0
    elif days >= TIER_LOW_MIN_DAYS:
        return "TIER_LOW", TIER_LOW_PCT
    elif days >= TIER_HIGH_MIN_DAYS:
        return "TIER_HIGH", TIER_HIGH_PCT
    else:
        return "TIER_FULL", TIER_FULL_PCT


def cancellation_refund(booking, penalty_pct, paid_cents_before):
    non_refundable = 0
    for pol in db.insurance_policies.values():
        if (
            pol["booking_id"] == booking["id"]
            and pol["status"] == "ACTIVE"
            and pol["refundable"] is False
        ):
            non_refundable += pol["premium_cents"]
    refundable_base = booking["grand_total_cents"] - non_refundable
    penalty_cents = round_half_up_div(refundable_base * penalty_pct, 100)
    refund_cents = max(0, paid_cents_before - penalty_cents)
    return refundable_base, penalty_cents, refund_cents


# =========================================================================
# Cascade: mandatory component rejected while booking RESERVED -> reopen DRAFT
# =========================================================================
def reopen_booking_on_mandatory_reject(booking):
    booking["status"] = "DRAFT"
    for m in booking_milestones(booking["id"]):
        if m["status"] == "OPEN":
            m["status"] = "WAIVED"
            touch(m)
    recompute_payment_status(booking)
    touch(booking)


# =========================================================================
# Cascade: booking cancellation sweep
# =========================================================================
def cancel_sweep(booking, refund_destination):
    """Compute the CancellationRecord and compensate the whole aggregate."""
    from db import stamp_create

    agency = db.agencies[booking["agency_id"]]
    status_before = booking["status"]
    paid_before = booking["paid_cents"]

    if status_before == "DRAFT":
        penalty_tier, penalty_pct = "TIER_FREE", 0
        refundable_base = booking["grand_total_cents"]
        penalty_cents = 0
        refund_cents = 0
    else:
        penalty_tier, penalty_pct = cancellation_penalty(booking)
        refundable_base, penalty_cents, refund_cents = cancellation_refund(
            booking, penalty_pct, paid_before
        )

    # Refund APPLIED payments; reverse milestone settlement.
    for p in db.payments.values():
        if p["booking_id"] == booking["id"] and p["status"] == "APPLIED":
            p["status"] = "REFUNDED"
            ms = db.milestones.get(p["milestone_id"])
            if ms is not None:
                ms["settled_amount_cents"] -= p["amount_cents"]
                refresh_milestone_status(ms)
                touch(ms)
            touch(p)

    # Waive all OPEN milestones.
    for m in booking_milestones(booking["id"]):
        if m["status"] == "OPEN":
            m["status"] = "WAIVED"
            touch(m)

    recompute_paid_cents(booking)  # lands at 0

    # Void ACTIVE insurance.
    for pol in db.insurance_policies.values():
        if pol["booking_id"] == booking["id"] and pol["status"] == "ACTIVE":
            pol["status"] = "VOIDED"
            touch(pol)

    # Release all non-RELEASED components.
    for c in db.components.values():
        if c["booking_id"] == booking["id"] and c["status"] != "RELEASED":
            c["status"] = "RELEASED"
            touch(c)

    # Wallet credit if directed.
    if refund_destination == "WALLET" and refund_cents > 0:
        customer = db.customers.get(booking["customer_id"])
        if customer is not None:
            customer["wallet_credit_cents"] += refund_cents
            touch(customer)

    booking["status"] = "CANCELLED"
    recompute_payment_status(booking)
    touch(booking)

    record = {
        "booking_id": booking["id"],
        "cancelled_at": agency["now_utc"],
        "penalty_tier": penalty_tier,
        "penalty_pct": penalty_pct,
        "refundable_base_cents": refundable_base,
        "penalty_cents": penalty_cents,
        "refund_cents": refund_cents,
        "refund_destination": refund_destination,
    }
    stamp_create(record)
    db.cancellation_records[record["id"]] = record
    return record
