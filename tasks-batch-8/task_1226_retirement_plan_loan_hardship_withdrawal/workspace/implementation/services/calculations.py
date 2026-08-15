"""Calculation rules per scaffold section 1.3.

All money is integer cents; rounding is ROUND_HALF_UP via Decimal.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

import db
from services.util import add_months, parse, iso, date_iso, today

getcontext().prec = 50

VESTED_RATIO = Decimal("0.5")
IRC_CAP_CENTS = 5_000_000
LOOKBACK_MONTHS = 12
FEE_TIER_THRESHOLD_CENTS = 1_000_000
FEE_LOW_CENTS = 5_000
FEE_HIGH_CENTS = 7_500
REFI_FEE_CENTS = 10_000


def _round_half_up_cents(value):
    """Round a Decimal to an integer number of cents, half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# amortization_schedule
# ---------------------------------------------------------------------------
def build_amortization_schedule(principal_cents, annual_rate_bps, term_months,
                                day_count_convention, disbursed_on_dt,
                                starting_installment_number=1,
                                first_due_date_dt=None):
    """Return (scheduled_payment_cents, [installment dicts]).

    installment dicts carry: installment_number, due_date (ISO str),
    scheduled_amount_cents, principal_portion_cents, interest_portion_cents.
    """
    annual = Decimal(annual_rate_bps) / Decimal(10000)
    monthly_rate = annual / Decimal(12)
    n = term_months
    if monthly_rate == 0:
        raw_payment = Decimal(principal_cents) / Decimal(n)
    else:
        factor = (Decimal(1) + monthly_rate) ** Decimal(-n)
        raw_payment = (Decimal(principal_cents) * monthly_rate) / (Decimal(1) - factor)
    scheduled_payment_cents = _round_half_up_cents(raw_payment)

    installments = []
    balance = principal_cents
    # First due date: one calendar month after disbursed_on (same day-of-month clamped)
    if first_due_date_dt is None:
        prev_due = disbursed_on_dt
        first_due = add_months(disbursed_on_dt, 1)
    else:
        # Rebuild cadence: continue monthly from last superseded row's due_date
        prev_due = first_due_date_dt
        first_due = add_months(first_due_date_dt, 1)

    due = first_due
    for k in range(1, n + 1):
        if day_count_convention == "ACT_360":
            days = (due.date() - prev_due.date()).days
            period_rate = annual * Decimal(days) / Decimal(360)
        else:  # THIRTY_360
            period_rate = monthly_rate
        interest_k = _round_half_up_cents(Decimal(balance) * period_rate)
        if k < n:
            principal_k = scheduled_payment_cents - interest_k
            scheduled_k = scheduled_payment_cents
        else:
            principal_k = balance
            scheduled_k = principal_k + interest_k
        installments.append({
            "installment_number": starting_installment_number + k - 1,
            "due_date": date_iso(due),
            "scheduled_amount_cents": scheduled_k,
            "principal_portion_cents": principal_k,
            "interest_portion_cents": interest_k,
        })
        balance -= principal_k
        prev_due = due
        due = add_months(due, 1)
    return scheduled_payment_cents, installments


# ---------------------------------------------------------------------------
# remittance waterfall
# ---------------------------------------------------------------------------
def eligible_loans_for_remittance(participant_id):
    out = []
    for loan in db.loans.values():
        if loan["participant_id"] != participant_id:
            continue
        if loan["lifecycle_status"] != "DISBURSED":
            continue
        if loan["delinquency_status"] == "DEEMED":
            continue
        out.append(loan)
    return out


def loan_installments(loan_id):
    rows = [r for r in db.loan_installments.values() if r["loan_id"] == loan_id]
    rows.sort(key=lambda r: r["installment_number"])
    return rows


def waterfall_candidates(loans):
    """Return list of (loan, installment) tuples in the pinned application order."""
    missed = []
    pending = []
    for loan in loans:
        for inst in loan_installments(loan["id"]):
            if inst["status"] not in ("MISSED", "PENDING"):
                continue
            if inst["paid_amount_cents"] >= inst["scheduled_amount_cents"]:
                continue
            entry = (loan, inst)
            if inst["status"] == "MISSED":
                missed.append(entry)
            else:
                pending.append(entry)

    def key(entry):
        loan, inst = entry
        return (parse(inst["due_date"]), parse(loan["created_at"]), inst["installment_number"])

    missed.sort(key=key)
    pending.sort(key=key)
    return missed + pending


def interest_already_covered(inst):
    """Interest portion already covered by payments on this installment.

    Payments first cover interest up to interest_portion_cents, then principal.
    """
    paid = inst["paid_amount_cents"]
    return min(paid, inst["interest_portion_cents"])


def apply_to_installment(inst, amount):
    """Apply `amount` to an installment; return (to_interest, to_principal)."""
    remaining_interest = inst["interest_portion_cents"] - interest_already_covered(inst)
    to_interest = min(amount, max(0, remaining_interest))
    to_principal = amount - to_interest
    inst["paid_amount_cents"] += amount
    return to_interest, to_principal


# ---------------------------------------------------------------------------
# loan_maximum_amount
# ---------------------------------------------------------------------------
def current_outstanding_total(participant_id):
    total = 0
    for loan in db.loans.values():
        if loan["participant_id"] != participant_id:
            continue
        if loan["lifecycle_status"] == "DISBURSED":
            total += loan.get("outstanding_principal_cents", 0) or 0
    return total


def outstanding_loan_count(participant_id):
    n = 0
    for loan in db.loans.values():
        if loan["participant_id"] != participant_id:
            continue
        if loan["lifecycle_status"] in ("REQUESTED", "APPROVED", "DISBURSED"):
            n += 1
    return n


def _reconstruct_high_water(participant_id, today_dt):
    """Reconstruct the trailing 12-month daily high-water mark of outstanding principal.

    For each calendar day D in [today - 12 months, today - 1 day], compute the
    end-of-day sum of outstanding_principal_cents across all of the participant's
    loans, reconstructed chronologically from disbursement and remittance posting
    dates (created_at ASC tie-break for same-day events).

    Loans DEEMED/OFFSET/REFINANCED/REPAID contribute to the historical mark but
    not to the current total. We model each loan's outstanding trajectory as a
    piecewise-constant function of time driven by events:
      - disbursement at disbursed_on: outstanding becomes principal_amount_cents
      - remittance posting (non-reversed): outstanding decreases by that
        remittance's to_principal applied to that loan
      - terminal events (REPAID / REFINANCED / OFFSET) drive outstanding to 0
        effective on the event date.
    """
    window_start = add_months(today_dt, -LOOKBACK_MONTHS).date()
    window_end = (today_dt - timedelta(days=1)).date()
    if window_end < window_start:
        return 0

    loans = [l for l in db.loans.values() if l["participant_id"] == participant_id]

    # Build per-loan event timelines
    # Each event: (date, created_at, delta_or_set, kind)
    events = []  # (date, created_at, loan_id, kind, value)
    for loan in loans:
        if loan.get("disbursed_on"):
            d = parse(loan["disbursed_on"]).date()
            events.append((d, loan["created_at"], loan["id"], "disburse",
                           loan["principal_amount_cents"]))
        # remittance postings for this loan
        for rem in db.payroll_remittances.values():
            if rem["participant_id"] != participant_id:
                continue
            if rem["status"] != "POSTED":
                continue
            for alloc in rem.get("applied_allocations") or []:
                if alloc["loan_id"] != loan["id"]:
                    continue
                d = parse(rem["created_at"]).date()
                events.append((d, rem["created_at"], loan["id"], "principal",
                               -alloc["to_principal_cents"]))
        # terminal zeroing events
        if loan["lifecycle_status"] in ("REPAID", "REFINANCED", "OFFSET"):
            # outstanding went to 0 on the terminal date
            term_date = None
            if loan["lifecycle_status"] == "OFFSET":
                # participant terminated_on
                part = db.participants.get(participant_id)
                if part and part.get("terminated_on"):
                    term_date = parse(part["terminated_on"]).date()
            elif loan["lifecycle_status"] == "REFINANCED":
                # find the new loan created by refinance (its created_at)
                for nl in db.loans.values():
                    if nl.get("refinances_loan_id") == loan["id"]:
                        term_date = parse(nl["created_at"]).date()
                        break
            elif loan["lifecycle_status"] == "REPAID":
                # date of the remittance that drove outstanding to 0:
                # approximate with loan.updated_at (the REPAID transition touched it).
                term_date = parse(loan["updated_at"]).date()
            if term_date is not None:
                events.append((term_date, loan["updated_at"], loan["id"], "zero", 0))

    # Group events by date; for each day in window compute end-of-day total
    from collections import defaultdict
    by_date = defaultdict(list)
    for ev in events:
        by_date[ev[0]].append(ev)
    for d in by_date:
        # same-day events: created_at ASC tie-break
        by_date[d].sort(key=lambda e: e[1])

    # Walk days chronologically
    if not by_date:
        return 0
    first_event_date = min(by_date.keys())
    start = min(window_start, first_event_date)

    # current outstanding per loan (rolling state as we walk forward)
    outstanding = {l["id"]: 0 for l in loans}
    high = 0
    d = start
    one = timedelta(days=1)
    while d <= window_end:
        todays = by_date.get(d, [])
        # apply events in order
        for (_, _, loan_id, kind, value) in todays:
            if kind == "disburse":
                outstanding[loan_id] = value
            elif kind == "principal":
                outstanding[loan_id] = max(0, outstanding.get(loan_id, 0) + value)
            elif kind == "zero":
                outstanding[loan_id] = 0
        if d >= window_start:
            total = sum(outstanding.values())
            if total > high:
                high = total
        d += one
    return high


def loan_maximum_amount(participant, plan, today_dt):
    vested = participant["vested_balance_cents"]
    vested_component = int((Decimal(vested) * VESTED_RATIO).to_integral_value(
        rounding="ROUND_FLOOR"))
    current_total = current_outstanding_total(participant["id"])
    high_water = _reconstruct_high_water(participant["id"], today_dt)
    reduction = max(0, high_water - current_total)
    irc_cap = IRC_CAP_CENTS - reduction
    if irc_cap < 0:
        irc_cap = 0
    return min(vested_component, irc_cap, plan["max_loan_amount_cents"])


# ---------------------------------------------------------------------------
# cure_window_deadline
# ---------------------------------------------------------------------------
def earliest_unpaid_missed_due_date(loan_id):
    rows = [r for r in db.loan_installments.values()
            if r["loan_id"] == loan_id and r["status"] == "MISSED"
            and r["paid_amount_cents"] < r["scheduled_amount_cents"]]
    if not rows:
        return None
    rows.sort(key=lambda r: (parse(r["due_date"]), r["installment_number"]))
    return parse(rows[0]["due_date"])


# ---------------------------------------------------------------------------
# distribution_taxable_amount
# ---------------------------------------------------------------------------
def accrued_unpaid_interest_through(loan, cutoff_dt):
    total = 0
    for inst in loan_installments(loan["id"]):
        if inst["status"] not in ("PENDING", "MISSED"):
            continue
        if parse(inst["due_date"]) > cutoff_dt:
            continue
        covered = interest_already_covered(inst)
        total += max(0, inst["interest_portion_cents"] - covered)
    return total


def taxable_amount_for_loan(loan, cutoff_dt):
    return (loan.get("outstanding_principal_cents", 0) or 0) + \
        accrued_unpaid_interest_through(loan, cutoff_dt)


def recompute_accrued_unpaid_interest(loan, eval_dt):
    loan["accrued_unpaid_interest_cents"] = accrued_unpaid_interest_through(loan, eval_dt)


# ---------------------------------------------------------------------------
# hardship_gross_up
# ---------------------------------------------------------------------------
def hardship_gross_up(amount_cents, amount_semantics, withholding_rate_bps):
    w = Decimal(withholding_rate_bps) / Decimal(10000)
    one_minus_w = Decimal(1) - w
    if amount_semantics == "NET":
        provisional_gross = Decimal(amount_cents) / one_minus_w
        fee = FEE_LOW_CENTS if provisional_gross <= Decimal(FEE_TIER_THRESHOLD_CENTS) else FEE_HIGH_CENTS
        gross = _round_half_up_cents((Decimal(amount_cents) + Decimal(fee)) / one_minus_w)
    else:  # GROSS
        gross = amount_cents
        fee = FEE_LOW_CENTS if gross <= FEE_TIER_THRESHOLD_CENTS else FEE_HIGH_CENTS
    withholding = _round_half_up_cents(Decimal(gross) * w)
    net = gross - withholding - fee
    return {
        "gross_withdrawal_cents": gross,
        "withholding_cents": withholding,
        "fee_cents": fee,
        "net_disbursed_cents": net,
    }


# ---------------------------------------------------------------------------
# refinance_terms
# ---------------------------------------------------------------------------
def refinance_new_principal(old_loan, cash_out_cents, today_dt):
    accrued = accrued_unpaid_interest_through(old_loan, today_dt)
    return (old_loan.get("outstanding_principal_cents", 0) or 0) + accrued + \
        cash_out_cents + REFI_FEE_CENTS
