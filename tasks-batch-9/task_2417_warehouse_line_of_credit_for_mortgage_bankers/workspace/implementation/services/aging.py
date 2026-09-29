"""The nightly aging run and fee accrual (PRD 3.9)."""

from datetime import date

from clock import clock, elapsed_days, plus_days
from db import base_row, db, touch
from money import frac, round_half_up_cents
from services import computed
from services.constants import (
    AGING_RUN_DEMAND_DAYS,
    DAY_COUNT_BASIS,
    FACILITY_SPREAD,
    ON_BOOK_FUNDING,
)
from services.ledger import post_entry
from services.states import (
    create_margin_call,
    has_open_call,
    restrict_if_active,
    suspend_facility,
)


def _raise_demand(advance, reason):
    now = clock.now()
    demand = base_row()
    demand.update({
        "advance_id": advance["id"],
        "reason": reason,
        "demand_amount_cents": computed.advance_outstanding(advance),
        "raised_at": now,
        "deadline_at": plus_days(now, AGING_RUN_DEMAND_DAYS),
        "status": "OPEN",
    })
    db.demands[demand["id"]] = demand
    return demand


def fee_accrual(facility, on_book_advances):
    """The seventh piece of work: a single facility-level posting whose rounding
    order is pinned — each advance's interest is rounded to whole cents first and
    the rounded figures are then summed; the unused-line fee is rounded once on
    its own line."""
    now = clock.now()
    last = facility["last_accrual_at"]
    if last is None:
        # No accrual baseline exists until the facility is approved.
        return 0, 0
    accrual_days = elapsed_days(last, now)
    if accrual_days <= 0:
        if last != now:
            facility["last_accrual_at"] = now
            touch(facility)
        return 0, accrual_days

    interest_total = 0
    for advance in on_book_advances:
        balance = computed.advance_outstanding(advance)
        amount = (frac(balance) * (frac(advance["note_rate"]) + FACILITY_SPREAD)
                  / frac(DAY_COUNT_BASIS) * frac(accrual_days))
        interest_total += round_half_up_cents(amount)

    undrawn = max(0, facility["committed_amount_cents"]
                  - computed.outstanding_principal(facility["id"]))
    unused_fee = round_half_up_cents(
        frac(undrawn) * frac(facility["unused_line_fee_rate"])
        / frac(DAY_COUNT_BASIS) * frac(accrual_days))

    total = interest_total + unused_fee
    if total > 0:
        post_entry(facility["id"], None, "FEE_ACCRUAL", "DEBIT", total,
                   "Facility fee accrual for %d day(s)" % accrual_days)
    facility["last_accrual_at"] = now
    touch(facility)
    return total, accrual_days


def run(facility):
    now = clock.now()
    facility_id = facility["id"]
    calls_issued = 0

    # First: refresh dwell_days and is_aged for every FUNDED or SHIPPED advance.
    on_book = [a for a in computed.facility_advances(facility_id)
               if a["funding_status"] in ON_BOOK_FUNDING]
    advances_evaluated = len(on_book)

    # Second: re-run the collateral valuation for each of them.
    curtailed_advance_ids = []
    for advance in on_book:
        result = computed.store_valuation(advance)
        if result["curtailment_steps"] >= 1:
            curtailed_advance_ids.append(advance["id"])
        if result["required_paydown_cents"] > 0 and not has_open_call(advance["id"]):
            call = create_margin_call(facility, advance, "DWELL_EXCEEDED",
                                      result["required_paydown_cents"])
            if call is not None:
                calls_issued += 1

    # Third: expire live bailee letters and raise BAILEE_EXPIRED demands.
    bailee_letters_expired = 0
    repurchase_demands_raised = 0
    letters = [b for b in db.bailee_letters.values()
               if b["advance_id"] in db.advances
               and db.advances[b["advance_id"]]["facility_id"] == facility_id]
    for letter in sorted(letters, key=lambda b: (b["created_at"], b["_seq"])):
        if letter["status"] != "ISSUED":
            continue
        if now < letter["expires_at"]:
            continue
        letter["status"] = "EXPIRED"
        touch(letter)
        bailee_letters_expired += 1
        advance = db.advances[letter["advance_id"]]
        if advance["funding_status"] == "SHIPPED":
            _raise_demand(advance, "BAILEE_EXPIRED")
            repurchase_demands_raised += 1

    # Fourth: wet advances whose receipt deadline has passed.
    receipts_overdue = 0
    for advance in computed.facility_advances(facility_id):
        if advance["funding_type"] != "WET":
            continue
        if advance["funding_status"] != "FUNDED":
            continue
        if advance["custody_status"] != "PENDING_RECEIPT":
            continue
        deadline = advance["wet_receipt_deadline_at"]
        if deadline is None or now < deadline:
            continue
        advance["custody_status"] = "RECEIPT_OVERDUE"
        touch(advance)
        receipts_overdue += 1
        result = computed.store_valuation(advance)
        if result["required_paydown_cents"] > 0 and not has_open_call(advance["id"]):
            call = create_margin_call(facility, advance, "CUSTODY_EXCEPTION",
                                      result["required_paydown_cents"])
            if call is not None:
                calls_issued += 1

    # Fifth: expire commitments whose window has closed, orphaning their advances.
    today = now.date()
    for commitment in computed.facility_commitments(facility_id):
        if commitment["status"] not in ("OPEN", "PARTIALLY_ALLOCATED"):
            continue
        expires_on = date.fromisoformat(commitment["expires_on"])
        if not (expires_on < today):
            continue
        commitment["status"] = "EXPIRED"
        touch(commitment)
        for advance in computed.commitment_advances(commitment["id"]):
            if advance["funding_status"] not in ON_BOOK_FUNDING:
                continue
            result = computed.store_valuation(advance)
            if result["required_paydown_cents"] > 0 and not has_open_call(advance["id"]):
                call = create_margin_call(facility, advance, "COMMITMENT_WITHDRAWN",
                                          result["required_paydown_cents"])
                if call is not None:
                    calls_issued += 1

    # Sixth: default margin calls whose cure deadline has passed.
    defaulted = 0
    for call in computed.facility_margin_calls(facility_id):
        if call["status"] not in ("ISSUED", "PARTIALLY_CURED"):
            continue
        if now < call["cure_deadline_at"]:
            continue
        call["status"] = "DEFAULTED"
        touch(call)
        defaulted += 1
    if defaulted and facility["status"] == "RESTRICTED":
        suspend_facility(facility)

    # Seventh: fee accrual.
    fee_accrual_cents, accrual_days = fee_accrual(facility, on_book)

    # Finally: an ACTIVE facility that issued at least one call moves to RESTRICTED.
    if calls_issued > 0:
        restrict_if_active(facility)

    return {
        "facility_id": facility_id,
        "run_at": now,
        "advances_evaluated": advances_evaluated,
        "curtailed_advance_ids": curtailed_advance_ids,
        "margin_calls_issued": calls_issued,
        "bailee_letters_expired": bailee_letters_expired,
        "receipts_overdue": receipts_overdue,
        "repurchase_demands_raised": repurchase_demands_raised,
        "fee_accrual_cents": fee_accrual_cents,
        "accrual_days": accrual_days,
    }
