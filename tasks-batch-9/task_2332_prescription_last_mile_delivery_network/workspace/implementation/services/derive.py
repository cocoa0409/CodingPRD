"""Derived quantities — recomputed from defining membership, never incremented.

PRD section 2.9: "Derived quantities are recomputed from their defining membership
rather than blindly incremented."
"""

from decimal import Decimal, ROUND_HALF_UP

from constants import (
    COURIER_MIN_LIFETIME_SCORE,
    COURIER_SCORE_MIN_ATTEMPTS,
    RESERVED_CUSTODY_STATES,
    ROLLING_DECAY_FACTOR,
    ROLLING_WINDOW_SIZE,
)
from db import db, sort_rows

HUNDRED = Decimal(100)
SCORE_FULL = Decimal("100.00")
CREDIT_BY_OUTCOME = {
    "DELIVERED": Decimal("1.0"),
    "NO_ANSWER": Decimal("0.5"),
    "REFUSED": Decimal("0.5"),
    "ADDRESS_INVALID": Decimal("0.5"),
    "ID_MISMATCH": Decimal("0.5"),
    "COLD_BREACH": Decimal("0.0"),
}


def round2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---- window occupancy ----------------------------------------------------
def window_deliveries(window):
    return [d for d in db.deliveries.values() if d["window_id"] == window["id"]]


def reserved_slots(window):
    return len([d for d in window_deliveries(window)
                if d["custody_status"] in RESERVED_CUSTODY_STATES])


def available_slots(window):
    return max(window["capacity_slots"] - reserved_slots(window), 0)


# ---- delivery mirrors ----------------------------------------------------
def delivery_allocations(delivery):
    return sort_rows([a for a in db.fee_allocations.values()
                      if a["delivery_id"] == delivery["id"]])


def active_allocation(delivery):
    for allocation in delivery_allocations(delivery):
        if allocation["status"] == "ACTIVE":
            return allocation
    return None


def fee_subtotal_cents(delivery):
    allocation = active_allocation(delivery)
    return allocation["fee_subtotal_cents"] if allocation else 0


def delivery_attempts(delivery):
    return sort_rows([a for a in db.delivery_attempts.values()
                      if a["delivery_id"] == delivery["id"]])


def attempt_count(delivery):
    return len(delivery_attempts(delivery))


def last_attempt_at(delivery):
    attempts = delivery_attempts(delivery)
    return attempts[-1]["attempted_at"] if attempts else None


def delivered_at(delivery):
    for attempt in delivery_attempts(delivery):
        if attempt["outcome"] == "DELIVERED":
            return attempt["attempted_at"]
    return None


# ---- grant ledger --------------------------------------------------------
def grant_allocations(grant):
    return [a for a in db.fee_allocations.values() if a["plan_grant_id"] == grant["id"]]


def grant_committed_cents(grant):
    return sum(a["plan_grant_cents"] for a in grant_allocations(grant)
               if a["status"] == "ACTIVE" and a["variant"] == "PROVISIONAL")


def grant_consumed_cents(grant):
    return sum(a["plan_grant_cents"] for a in grant_allocations(grant)
               if a["status"] == "ACTIVE" and a["variant"] == "FINAL")


def grant_remaining_cents(grant):
    return (grant["grant_budget_cents"] - grant_committed_cents(grant)
            - grant_consumed_cents(grant))


def grant_status(grant):
    return "ACTIVE" if grant_remaining_cents(grant) > 0 else "EXHAUSTED"


# ---- courier statistics --------------------------------------------------
def courier_assignments(courier):
    return [a for a in db.courier_assignments.values() if a["courier_id"] == courier["id"]]


def active_delivery_count(courier):
    return len([a for a in courier_assignments(courier) if a["status"] == "ACCEPTED"])


def courier_attempts(courier):
    return sort_rows([a for a in db.delivery_attempts.values()
                      if a["courier_id"] == courier["id"]])


def attempt_total_count(courier):
    return len(courier_attempts(courier))


def delivered_count(courier):
    return len([a for a in courier_attempts(courier) if a["outcome"] == "DELIVERED"])


def rolling_reliability_score(courier):
    attempts = courier_attempts(courier)
    if not attempts:
        return SCORE_FULL
    recent = list(reversed(attempts))[:ROLLING_WINDOW_SIZE]
    decay = Decimal(ROLLING_DECAY_FACTOR)
    numerator = Decimal(0)
    denominator = Decimal(0)
    for index, attempt in enumerate(recent):
        weight = decay ** index
        numerator += CREDIT_BY_OUTCOME.get(attempt["outcome"], Decimal("0.0")) * weight
        denominator += weight
    return round2(HUNDRED * numerator / denominator)


def lifetime_reliability_score(courier):
    total = attempt_total_count(courier)
    if total == 0:
        return SCORE_FULL
    return round2(HUNDRED * Decimal(delivered_count(courier)) / Decimal(total))


def suspension_due(courier):
    """PRD section 3.7: only the lifetime score can suspend anyone."""
    return (attempt_total_count(courier) >= COURIER_SCORE_MIN_ATTEMPTS
            and lifetime_reliability_score(courier) < Decimal(COURIER_MIN_LIFETIME_SCORE)
            and courier["status"] in {"OFFLINE", "AVAILABLE", "ON_ROUTE"})
