"""Domain service: entity construction, serialization, accrual recomputation,
state transitions and cascades.

All monetary fields are integer cents. system fields are id/created_at/
updated_at/version (PRD §2.4). version starts at 1 and increments by one on
every mutation (including cascade-driven recomputations).
"""

from datetime import datetime, timezone

import db
from services import calc

# Files for serialization order are not contractual; the harness reads fields by
# name. We emit every entity field.


# ---------------------------------------------------------------------------
# system field management
# ---------------------------------------------------------------------------
def _stamp_new(record):
    ts = db.now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Register a mutation: bump version, refresh updated_at."""
    record["updated_at"] = db.now_iso()
    record["version"] = record.get("version", 0) + 1


# ---------------------------------------------------------------------------
# option_deadline = lease_start + option_term_months (calendar months)
# ---------------------------------------------------------------------------
def add_months(dt, months):
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to the last valid day of the target month
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise


# ---------------------------------------------------------------------------
# Accrual recomputation over RentPayment children
# ---------------------------------------------------------------------------
def agreement_payments(agreement_id):
    return [p for p in db.rent_payments.values()
            if p["agreement_id"] == agreement_id]


def non_superseded(payments):
    """Rows that are NOT pointed-to as a supersession source are still counted;
    a row that HAS been superseded by another row is excluded from accrual and
    uniqueness. We track this by whether any row references it via
    supersedes_payment_id."""
    superseded_ids = {p["supersedes_payment_id"] for p in payments
                      if p.get("supersedes_payment_id")}
    return [p for p in payments if p["id"] not in superseded_ids]


def recompute_accruals(agreement):
    """Recompute missed_payment_count, gross/available credit from children.

    gross = SUM(credit_portion) over {PENDING, PAID, LATE} non-superseded
    available = SUM(credit_portion) over PAID non-superseded
    missed = count of FORFEITED non-superseded rows

    On DEFAULTED the spec dictates that all earned credit evaporates, so
    available_credit_cents is forced to zero regardless of remaining PAID rows
    (PRD §3.8). The agreement carries a sticky _credit_forfeited flag set when
    default occurs.
    """
    payments = non_superseded(agreement_payments(agreement["id"]))
    gross = 0
    available = 0
    missed = 0
    for p in payments:
        st = p["status"]
        if st in ("PENDING", "PAID", "LATE"):
            gross += p["credit_portion_cents"]
        if st == "PAID":
            available += p["credit_portion_cents"]
        if st == "FORFEITED":
            missed += 1
    if agreement.get("_credit_forfeited"):
        available = 0
    agreement["gross_credit_accrued_cents"] = gross
    agreement["available_credit_cents"] = available
    agreement["missed_payment_count"] = missed


# ---------------------------------------------------------------------------
# Serialization — return a copy with computed fields fresh; private keys
# (underscore-prefixed bookkeeping) are never exposed.
# ---------------------------------------------------------------------------
def _public(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def serialize_landlord(r):
    return _public(r)


def serialize_tenant(r):
    return _public(r)


def serialize_property(r):
    return _public(r)


def serialize_agreement(r):
    recompute_accruals(r)
    return _public(r)


def serialize_rent_payment(r):
    return _public(r)


def serialize_maintenance_ticket(r):
    return _public(r)


def serialize_option_exercise(r):
    return _public(r)


def serialize_mortgage(r):
    return _public(r)
