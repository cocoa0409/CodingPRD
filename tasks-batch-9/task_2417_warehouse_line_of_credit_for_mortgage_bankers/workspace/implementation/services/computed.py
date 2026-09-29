"""Ledger projections, dwell classification and the collateral valuation.

PRD 2.6: no balance in this system is a stored counter — every balance is a
projection replayed from the append-only ledger.
"""

import math
from fractions import Fraction

from clock import clock, elapsed_days
from db import by_created_at, db
from money import floor_cents, frac, round_half_up_rate
from services.constants import (
    CLEAN_COVENANT_STATUSES,
    EXCEPTION_HAIRCUT,
    FILE_OUTSTANDING_CUSTODY,
    ON_BOOK_FUNDING,
    OPEN_CALL_STATUSES,
    ORPHAN_RATE,
    ORPHANING_COMMITMENT_STATUSES,
    PRINCIPAL_TYPES,
)


# ---------------------------------------------------------------- collections

def facility_advances(facility_id):
    return by_created_at([a for a in db.advances.values()
                          if a["facility_id"] == facility_id])


def facility_rate_rows(facility_id):
    return by_created_at([r for r in db.product_rates.values()
                          if r["facility_id"] == facility_id])


def facility_custodians(facility_id):
    return by_created_at([c for c in db.custodians.values()
                          if c["facility_id"] == facility_id])


def facility_investors(facility_id):
    return by_created_at([i for i in db.investors.values()
                          if i["facility_id"] == facility_id])


def facility_commitments(facility_id):
    return by_created_at([c for c in db.commitments.values()
                          if c["facility_id"] == facility_id])


def facility_margin_calls(facility_id):
    return by_created_at([m for m in db.margin_calls.values()
                          if m["facility_id"] == facility_id])


def facility_covenant_tests(facility_id):
    return by_created_at([t for t in db.covenant_tests.values()
                          if t["facility_id"] == facility_id])


def facility_ledger(facility_id):
    return sorted(
        [e for e in db.ledger_entries.values() if e["facility_id"] == facility_id],
        key=lambda e: (e["posted_at"], e["created_at"], e["_seq"]),
    )


def advance_ledger(advance_id):
    return sorted(
        [e for e in db.ledger_entries.values() if e["advance_id"] == advance_id],
        key=lambda e: (e["posted_at"], e["created_at"], e["_seq"]),
    )


def advance_wires(advance_id):
    return by_created_at([w for w in db.wires.values()
                          if w["advance_id"] == advance_id])


def advance_receipts(advance_id):
    return by_created_at([r for r in db.receipts.values()
                          if r["advance_id"] == advance_id])


def advance_bailee_letters(advance_id):
    return by_created_at([b for b in db.bailee_letters.values()
                          if b["advance_id"] == advance_id])


def advance_margin_calls(advance_id):
    return by_created_at([m for m in db.margin_calls.values()
                          if m["advance_id"] == advance_id])


def advance_demands(advance_id):
    return by_created_at([d for d in db.demands.values()
                          if d["advance_id"] == advance_id])


def commitment_advances(commitment_id):
    return by_created_at([a for a in db.advances.values()
                          if a["investor_commitment_id"] == commitment_id])


def investor_commitments(investor_id):
    return by_created_at([c for c in db.commitments.values()
                          if c["investor_id"] == investor_id])


def investor_bailee_letters(investor_id):
    return by_created_at([b for b in db.bailee_letters.values()
                          if b["investor_id"] == investor_id])


def facility_demands(facility_id):
    ids = set(a["id"] for a in db.advances.values()
              if a["facility_id"] == facility_id)
    return by_created_at([d for d in db.demands.values() if d["advance_id"] in ids])


def rate_row_for(facility_id, product_code):
    for row in facility_rate_rows(facility_id):
        if row["product_code"] == product_code:
            return row
    return None


def advance_rate_row(advance):
    return rate_row_for(advance["facility_id"], advance["product_code"])


def advance_commitment(advance):
    cid = advance.get("investor_commitment_id")
    if cid is None:
        return None
    return db.commitments.get(cid)


# ------------------------------------------------------------------ balances

def _principal_sum(entries, direction):
    return sum(e["amount_cents"] for e in entries
               if e["entry_type"] in PRINCIPAL_TYPES and e["direction"] == direction)


def advance_outstanding(advance):
    entries = [e for e in db.ledger_entries.values()
               if e["advance_id"] == advance["id"]]
    return _principal_sum(entries, "DEBIT") - _principal_sum(entries, "CREDIT")


def facility_principal_totals(facility_id):
    entries = [e for e in db.ledger_entries.values()
               if e["facility_id"] == facility_id]
    debit = _principal_sum(entries, "DEBIT")
    credit = _principal_sum(entries, "CREDIT")
    return debit, credit


def outstanding_principal(facility_id):
    debit, credit = facility_principal_totals(facility_id)
    return debit - credit


def accrued_fee_balance(facility_id):
    total = 0
    for entry in db.ledger_entries.values():
        if entry["facility_id"] != facility_id:
            continue
        if entry["entry_type"] == "FEE_ACCRUAL":
            total += entry["amount_cents"]
        elif entry["entry_type"] == "FEE_PAYMENT":
            total -= entry["amount_cents"]
    return total


def availability(facility):
    return max(0, facility["committed_amount_cents"]
               - outstanding_principal(facility["id"]))


# -------------------------------------------------------- dwell and valuation

def dwell_days(advance):
    """PRD 3.6: zero while funded_at is null or funding_status is not FUNDED or
    SHIPPED; otherwise complete 86,400-second periods from funded_at."""
    if advance["funded_at"] is None or advance["funding_status"] not in ON_BOOK_FUNDING:
        return 0
    return max(0, elapsed_days(advance["funded_at"], clock.now()))


def is_aged(advance, row=None):
    row = row or advance_rate_row(advance)
    if row is None:
        return False
    if advance["funded_at"] is None or advance["funding_status"] not in ON_BOOK_FUNDING:
        return False
    return dwell_days(advance) > row["dwell_limit_days"]


def curtailment_steps(advance, row=None):
    row = row or advance_rate_row(advance)
    if row is None:
        return 0
    dwell = dwell_days(advance)
    limit = row["dwell_limit_days"]
    if dwell <= limit:
        return 0
    return int(math.ceil(Fraction(dwell - limit, row["aging_step_days"])))


def valuation(advance):
    """PRD 3.6.  Returns the three stored figures plus the derived helpers.

    Only advances whose funding_status is FUNDED or SHIPPED are valued at all:
    for any other state effective_advance_rate keeps whatever value it last
    held and required_paydown_cents is forced to zero.
    """
    outstanding = advance_outstanding(advance)
    if advance["funding_status"] not in ON_BOOK_FUNDING:
        return {
            "effective_advance_rate": advance.get("_effective_advance_rate", Fraction(0)),
            "eligible_collateral_value_cents":
                advance.get("_eligible_collateral_value_cents", 0),
            "required_paydown_cents": 0,
            "curtailment_steps": 0,
            "dwell_days": dwell_days(advance),
            "is_aged": False,
            "outstanding_balance_cents": outstanding,
        }
    row = advance_rate_row(advance)
    rate = frac(row["advance_rate"])
    # step one: base rate less the wet haircut while the file is not in hand
    if advance["funding_type"] == "WET" and \
            advance["custody_status"] in FILE_OUTSTANDING_CUSTODY:
        rate = rate - frac(row["wet_haircut"])
    # step two: aging curtailment
    steps = curtailment_steps(advance, row)
    if steps:
        rate = rate - steps * frac(row["curtailment_step_rate"])
    # step three: document-exception haircut
    if advance["custody_status"] == "RECEIVED_EXCEPTION":
        rate = rate - EXCEPTION_HAIRCUT
    # step four: orphan cap
    commitment = advance_commitment(advance)
    if commitment is None or commitment["status"] in ORPHANING_COMMITMENT_STATUSES:
        rate = min(rate, ORPHAN_RATE)
    if rate < 0:
        rate = Fraction(0)
    effective = round_half_up_rate(rate, 4)
    basis = min(advance["loan_amount_cents"], advance["market_value_cents"])
    eligible = floor_cents(frac(basis) * effective)
    required = max(0, outstanding - eligible)
    return {
        "effective_advance_rate": effective,
        "eligible_collateral_value_cents": eligible,
        "required_paydown_cents": required,
        "curtailment_steps": steps,
        "dwell_days": dwell_days(advance),
        "is_aged": dwell_days(advance) > row["dwell_limit_days"],
        "outstanding_balance_cents": outstanding,
    }


def store_valuation(advance):
    """Run the valuation and store the three figures on the advance."""
    result = valuation(advance)
    advance["_effective_advance_rate"] = result["effective_advance_rate"]
    advance["_eligible_collateral_value_cents"] = \
        result["eligible_collateral_value_cents"]
    advance["_required_paydown_cents"] = result["required_paydown_cents"]
    return result


def required_paydown(advance):
    return valuation(advance)["required_paydown_cents"]


# --------------------------------------------------------- facility rollups

def wet_outstanding(facility_id):
    total = 0
    for advance in db.advances.values():
        if advance["facility_id"] != facility_id:
            continue
        if advance["funding_type"] != "WET":
            continue
        if advance["funding_status"] not in ON_BOOK_FUNDING:
            continue
        if advance["custody_status"] not in FILE_OUTSTANDING_CUSTODY:
            continue
        total += advance_outstanding(advance)
    return total


def aged_outstanding(facility_id):
    total = 0
    for advance in db.advances.values():
        if advance["facility_id"] != facility_id:
            continue
        if advance["funding_status"] not in ON_BOOK_FUNDING:
            continue
        if not is_aged(advance):
            continue
        total += advance_outstanding(advance)
    return total


def scratch_and_dent_outstanding(facility_id):
    return product_outstanding(facility_id, "SCRATCH_AND_DENT")


def product_outstanding(facility_id, product_code):
    total = 0
    for advance in db.advances.values():
        if advance["facility_id"] != facility_id:
            continue
        if advance["product_code"] != product_code:
            continue
        if advance["funding_status"] not in ON_BOOK_FUNDING:
            continue
        total += advance_outstanding(advance)
    return total


def advance_outstanding_sum(facility_id):
    total = 0
    for advance in db.advances.values():
        if advance["facility_id"] != facility_id:
            continue
        if advance["funding_status"] not in ON_BOOK_FUNDING:
            continue
        total += advance_outstanding(advance)
    return total


def open_margin_call_count(facility_id):
    return len([m for m in db.margin_calls.values()
                if m["facility_id"] == facility_id
                and m["status"] in OPEN_CALL_STATUSES])


def has_defaulted_call(facility_id):
    return any(m["status"] == "DEFAULTED" for m in db.margin_calls.values()
               if m["facility_id"] == facility_id)


def escalated_demand_count(facility_id):
    return len([d for d in facility_demands(facility_id) if d["status"] == "ESCALATED"])


def _tests_newest_first(facility_id):
    tests = [t for t in db.covenant_tests.values() if t["facility_id"] == facility_id]
    return sorted(tests, key=lambda t: (t["period_end"], t["created_at"], t["_seq"]),
                  reverse=True)


def last_covenant_status(facility_id):
    """The status of the test with the greatest period_end, created_at
    descending as the tie-break; NOT_TESTED while no test exists."""
    tests = _tests_newest_first(facility_id)
    if not tests:
        return "NOT_TESTED"
    return tests[0]["status"]


def consecutive_breach_count(facility_id):
    """Consecutive tests ending at the latest period_end whose status is
    BREACH; a PASS test or a waiver of the latest breach resets it."""
    count = 0
    for test in _tests_newest_first(facility_id):
        if test["status"] == "BREACH":
            count += 1
        else:
            break
    return count


def facility_is_clean_for_restricted_exit(facility):
    return (open_margin_call_count(facility["id"]) == 0
            and last_covenant_status(facility["id"]) in CLEAN_COVENANT_STATUSES
            and escalated_demand_count(facility["id"]) == 0)


# -------------------------------------------------------- commitment buckets

def commitment_buckets(commitment):
    allocated = 0
    settled = 0
    for advance in db.advances.values():
        if advance["investor_commitment_id"] != commitment["id"]:
            continue
        if advance["funding_status"] in ON_BOOK_FUNDING:
            allocated += advance["advance_amount_cents"]
        elif advance["funding_status"] == "PURCHASED":
            settled += advance["advance_amount_cents"]
    remaining = commitment["committed_amount_cents"] - allocated - settled
    if remaining < 0:
        remaining = 0
    if commitment["status"] == "WITHDRAWN":
        remaining = 0
    return allocated, settled, remaining


def commitment_remaining(commitment):
    return commitment_buckets(commitment)[2]


def refresh_commitment_status(commitment):
    """PRD 3.2: status mirrors the buckets — OPEN while remaining equals the
    committed amount, PARTIALLY_ALLOCATED while strictly between, and
    FULLY_ALLOCATED when remaining reaches zero.  Terminal statuses are left
    untouched."""
    if commitment["status"] in ("WITHDRAWN", "EXPIRED"):
        return
    _, _, remaining = commitment_buckets(commitment)
    committed = commitment["committed_amount_cents"]
    if remaining >= committed:
        commitment["status"] = "OPEN"
    elif remaining <= 0:
        commitment["status"] = "FULLY_ALLOCATED"
    else:
        commitment["status"] = "PARTIALLY_ALLOCATED"


def investor_exposure(investor_id):
    """The sum of outstanding_balance_cents over the advances whose commitment
    belongs to that investor and whose funding_status is FUNDED or SHIPPED."""
    commitment_ids = set(c["id"] for c in db.commitments.values()
                         if c["investor_id"] == investor_id)
    total = 0
    for advance in db.advances.values():
        if advance["investor_commitment_id"] not in commitment_ids:
            continue
        if advance["funding_status"] not in ON_BOOK_FUNDING:
            continue
        total += advance_outstanding(advance)
    return total
