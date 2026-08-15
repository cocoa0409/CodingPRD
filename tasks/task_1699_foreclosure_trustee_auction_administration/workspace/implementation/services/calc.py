"""Calculation rules (SCAFFOLD §1.3), implemented exactly.

Pinned rounding orders (PRD §2.6, non-negotiable):
  - per-diem interest: round the daily amount to whole cents FIRST, then
    multiply by the day count. Rounding after multiplication is forbidden.
  - quote lines: each line computed and rounded to integer cents first, then
    a single sum. Sum-then-round is forbidden.
"""
from decimal import Decimal

from util import rhu, dec_rate, day_count, parse_date_strict

# --- statutory / fee constants (SCAFFOLD calculations.constants) ---
REINSTATEMENT_PERIOD_DAYS = 90
REINSTATEMENT_CUTOFF_BUSINESS_DAYS = 5
NOTS_MIN_DAYS_BEFORE_SALE = 14
FIRST_PUBLICATION_MIN_DAYS_BEFORE_SALE = 20
PUBLICATION_MIN_GAP_DAYS = 7
PUBLICATIONS_REQUIRED = 3
MAX_POSTPONEMENTS_PER_NOTS = 3
POSTPONEMENT_MAX_DAYS_PER_EVENT = 30
DEED_RECORDING_DEADLINE_DAYS = 15
CLAIMS_WINDOW_DAYS = 180
AUCTION_DURATION_MINUTES = 60

REINSTATEMENT_FEE_CENTS = 50000
PAYOFF_FEE_CENTS = 25000
PREPAYMENT_PENALTY_PCT = Decimal("0.02")

FEE_PCT = Decimal("0.005")
FEE_FLOOR_CENTS = 75000
FEE_CAP_CENTS = 475000

MIN_INCREMENT_CENTS = 50000
INCREMENT_PCT = Decimal("0.005")

DEPOSIT_FLOOR_CENTS = 1000000
DEPOSIT_PCT = Decimal("0.01")


def per_diem_interest(base_cents, note_rate_pct, from_date, to_date):
    """per_diem = round_half_up(base * rate / 100 / 365); interest = per_diem
    * day_count(from excluded, to included). Round-then-multiply pinned."""
    per_diem = rhu(Decimal(base_cents) * dec_rate(note_rate_pct) / Decimal(100) / Decimal(365))
    return per_diem * day_count(from_date, to_date)


def quote_amounts(case, quote_type, good_through_date, approved_costs_cents,
                  recorded_nod_recording_date):
    """Compute the six quote line items (all integer cents) and their total.

    quote_type: REINSTATEMENT | PAYOFF.
    recorded_nod_recording_date: date of the case's RECORDED NOD, or None
    (a REFERRED case has none; reinstatement interest then anchors to
    nothing and is 0).
    """
    costs = approved_costs_cents
    if quote_type == "REINSTATEMENT":
        arrears = case["monthly_payment_cents"] * case["months_in_arrears"]
        late_fees = case["late_fee_per_month_cents"] * case["months_in_arrears"]
        if recorded_nod_recording_date is not None:
            interest = per_diem_interest(arrears + late_fees, case["note_rate_pct"],
                                         recorded_nod_recording_date, good_through_date)
        else:
            interest = 0
        trustee_fee = REINSTATEMENT_FEE_CENTS
        penalty = 0
    else:  # PAYOFF
        arrears = 0
        late_fees = 0
        interest = per_diem_interest(case["unpaid_principal_balance_cents"],
                                     case["note_rate_pct"],
                                     parse_date_strict(case["last_interest_paid_date"]),
                                     good_through_date)
        trustee_fee = PAYOFF_FEE_CENTS
        penalty = (rhu(Decimal(case["unpaid_principal_balance_cents"]) * PREPAYMENT_PENALTY_PCT)
                   if case["prepayment_penalty_applies"] else 0)
    total = arrears + late_fees + costs + interest + trustee_fee + penalty
    if quote_type == "PAYOFF":
        # A payoff retires the loan: the total tendered must also cover the
        # full unpaid principal balance (SCAFFOLD quote_amounts PAYOFF
        # variant "full principal + ..."; verified against the difficulty
        # design's pinned totals 41471640 / 10052126 / 41468870). The six
        # stored line items are unaffected — arrears stays 0 for PAYOFF.
        total += case["unpaid_principal_balance_cents"]
    return {
        "arrears_cents": arrears,
        "late_fees_cents": late_fees,
        "costs_cents": costs,
        "interest_cents": interest,
        "trustee_fee_cents": trustee_fee,
        "prepayment_penalty_cents": penalty,
        "total_cents": total,
    }


def trustee_compensation_fee(winner_type, winning_bid_cents, total_debt_at_close_cents):
    """base = winning bid when THIRD_PARTY else total debt at close;
    fee = min(cap, max(floor, round_half_up(0.5% * base)))."""
    base = winning_bid_cents if winner_type == "THIRD_PARTY" else total_debt_at_close_cents
    proportional = rhu(Decimal(base) * FEE_PCT)
    return min(FEE_CAP_CENTS, max(FEE_FLOOR_CENTS, proportional))


def total_debt_at_close(case, close_date):
    """UPB + per-diem interest on principal from last_interest_paid_date
    through the close date."""
    return case["unpaid_principal_balance_cents"] + per_diem_interest(
        case["unpaid_principal_balance_cents"], case["note_rate_pct"],
        parse_date_strict(case["last_interest_paid_date"]), close_date)


def minimum_next_bid(opening_bid_cents, existing_bid_amounts):
    """increment(base) = max(50000, round_half_up(0.5% * base)); required min
    = base + increment(base); base is opening bid when no bids, else current
    high bid. Acceptance is >= required_min (equal accepted)."""
    if existing_bid_amounts:
        base = max(existing_bid_amounts)
    else:
        base = opening_bid_cents
    increment = max(MIN_INCREMENT_CENTS, rhu(Decimal(base) * INCREMENT_PCT))
    return base + increment


def required_bidder_deposit(opening_reference_cents):
    """max(1000000, round_half_up(1% * opening_reference))."""
    return max(DEPOSIT_FLOOR_CENTS, rhu(Decimal(opening_reference_cents) * DEPOSIT_PCT))


def pro_rata_shares(pool_cents, unpaid_amounts):
    """Split pool proportionally to unpaid amounts: floor shares, then the
    leftover cents (< tier size) one cent at a time in list order (callers
    pass claims in created_at ASC order) until exhausted."""
    total = sum(unpaid_amounts)
    if total <= 0 or pool_cents <= 0:
        return [0] * len(unpaid_amounts)
    shares = [(pool_cents * u) // total for u in unpaid_amounts]
    leftover = pool_cents - sum(shares)
    i = 0
    while leftover > 0 and i < len(shares):
        shares[i] += 1
        leftover -= 1
        i += 1
    return shares
