"""Calculation rules (PRD §3.2-§3.5, SCAFFOLD §1.3).

All money is integer cents. round_half_up is used wherever fractions arise.
"""
from validate import quarter_key, quarter_of_date, round_half_up, round_half_up_dollar

# Constants (SCAFFOLD §1.3)
QUALIFYING_MIN_TOTAL_CENTS = 260000
HIGH_QUARTER_MIN_CENTS = 130000
WBA_DIVISOR = 26
WBA_FLOOR_CENTS = 4000
WBA_CEILING_CENTS = 60000
MAX_REGULAR_WEEKS = 26
MBA_WAGE_FRACTION_NUM = 1   # 50% = 1/2
MBA_WAGE_FRACTION_DEN = 2
EARNINGS_DISREGARD_PCT = 0.25
EARNINGS_DISREGARD_FLOOR_CENTS = 5000
FRAUD_PENALTY_RATE = 0.15


def _completed_quarters_before(filed_date):
    """(year, qnum) of the quarter that contains filed_date; completed quarters
    are those strictly before it."""
    return quarter_of_date(filed_date)


def base_period_sets(filed_date):
    """Return (standard_quarter_keys, alternate_quarter_keys) as sets of
    (year, qnum). May be fewer than 4 if history is short.

    completed = quarters strictly before the quarter containing filed_date.
    last_five = the 5 most recent completed quarters.
    STANDARD  = first four of last_five (drop the single most recent).
    ALTERNATE = the four most recent completed quarters (drop oldest of five).
    """
    filing_q = _completed_quarters_before(filed_date)

    # Enumerate completed quarter keys is unbounded; instead we derive the
    # last five completed quarter keys directly by stepping back from filing_q.
    completed = []
    y, q = filing_q
    for _ in range(5):
        # step back one quarter
        q -= 1
        if q == 0:
            q = 4
            y -= 1
        completed.append((y, q))
    # completed is in descending chronological order (most recent first)
    last_five = completed  # already 5 most recent (descending)

    # STANDARD = first four of those last five chronologically; "first four"
    # means dropping the single MOST RECENT completed quarter.
    # last_five descending: [most_recent, ..., oldest]
    standard = set(last_five[1:5])      # drop most recent -> 4 older quarters
    alternate = set(last_five[0:4])     # drop oldest -> 4 most recent quarters
    return standard, alternate


def _wage_records_for_claimant(claimant_id, all_wage_records):
    return [w for w in all_wage_records if w["claimant_id"] == claimant_id]


def base_period_figures(quarter_set, claimant_wage_records):
    """Return (base_total_cents, high_quarter_cents) for a quarter set.

    include(wr) = wr.calendar_quarter in set AND not wr.is_disputed
    base_total  = sum of gross_wages_cents over included
    high_quarter = max per-quarter sum (0 if none)
    """
    per_quarter = {}
    for w in claimant_wage_records:
        if w.get("is_disputed"):
            continue
        qk = quarter_key(w["calendar_quarter"])
        if qk not in quarter_set:
            continue
        per_quarter[qk] = per_quarter.get(qk, 0) + w["gross_wages_cents"]
    base_total = sum(per_quarter.values())
    high_quarter = max(per_quarter.values()) if per_quarter else 0
    return base_total, high_quarter


def qualifies(base_total, high_quarter):
    """All three sub-tests (PRD §3.2 'Monetary qualification').

    1. base_total >= QUALIFYING_MIN_TOTAL_CENTS
    2. high_quarter >= HIGH_QUARTER_MIN_CENTS
    3. 2*base_total >= 3*high_quarter   (i.e. base_total >= 1.5*high_quarter)
    """
    if base_total < QUALIFYING_MIN_TOTAL_CENTS:
        return False
    if high_quarter < HIGH_QUARTER_MIN_CENTS:
        return False
    if 2 * base_total < 3 * high_quarter:
        return False
    return True


def select_method(filed_date, claimant_wage_records):
    """Return (method, base_total, high_quarter).

    method is 'STANDARD', 'ALTERNATE', or 'NONE'. Selection order pinned:
    try STANDARD first; if it qualifies, select it (ALTERNATE not evaluated
    for selection); else test ALTERNATE.
    """
    standard_set, alternate_set = base_period_sets(filed_date)
    std_total, std_high = base_period_figures(standard_set, claimant_wage_records)
    if qualifies(std_total, std_high):
        return "STANDARD", std_total, std_high
    alt_total, alt_high = base_period_figures(alternate_set, claimant_wage_records)
    if qualifies(alt_total, alt_high):
        return "ALTERNATE", alt_total, alt_high
    return "NONE", 0, 0


def weekly_benefit_amount(high_quarter_cents):
    """WBA = round_half_up_dollar(high_quarter / 26), then clamp [4000,60000].

    Rounding to whole dollar happens BEFORE the clamp; clamp does not re-round.
    """
    raw = high_quarter_cents / WBA_DIVISOR
    rounded = round_half_up_dollar(raw)
    return min(max(rounded, WBA_FLOOR_CENTS), WBA_CEILING_CENTS)


def floor_to_dollar(cents):
    """Floor a cents value down to a whole dollar (multiple of 100)."""
    return (int(cents) // 100) * 100


def base_maximum_benefit_amount(wba_cents, base_total_cents):
    """Base MBA = min(duration_cap, wage_pct_cap).

    duration_cap = wba * 26
    wage_pct_cap = floor_to_dollar(50% of base_total)
    """
    duration_cap = wba_cents * MAX_REGULAR_WEEKS
    # 50% of base_total, then floor to whole dollar
    half = (base_total_cents * MBA_WAGE_FRACTION_NUM) / MBA_WAGE_FRACTION_DEN
    wage_pct_cap = floor_to_dollar(half)
    return min(duration_cap, wage_pct_cap)


def maximum_benefit_amount(wba_cents, base_total_cents, extension_weeks_granted=0):
    """MBA = base_mba + extension_weeks_granted * wba (no re-round)."""
    base = base_maximum_benefit_amount(wba_cents, base_total_cents)
    return base + extension_weeks_granted * wba_cents


def weekly_payable_amount(wba_cents, reported_earnings_cents, remaining_balance_cents):
    """Payable for the week (PRD §3.5.1).

    disregard = max(5000, round_half_up(wba * 0.25))
    countable = max(0, reported_earnings - disregard)
    gross_payable = max(0, wba - countable)
    payable = min(gross_payable, remaining_balance)
    """
    disregard = max(EARNINGS_DISREGARD_FLOOR_CENTS,
                    round_half_up(wba_cents * EARNINGS_DISREGARD_PCT))
    countable = max(0, reported_earnings_cents - disregard)
    gross_payable = max(0, wba_cents - countable)
    return min(gross_payable, remaining_balance_cents)


def overpayment_penalty(cause, principal_cents):
    """FRAUD -> round_half_up(principal * 0.15); NONFRAUD -> 0.
    Returns (penalty_cents, total_assessed_cents)."""
    if cause == "FRAUD":
        penalty = round_half_up(principal_cents * FRAUD_PENALTY_RATE)
    else:
        penalty = 0
    return penalty, principal_cents + penalty


def employer_charge_allocation(payable_amount_cents, employer_wage_pairs):
    """Allocate payable across base-period employers by largest-remainder.

    employer_wage_pairs: list of (employer_id, wages_cents, employer_created_at,
                                   employer_seq) for distinct base-period employers.
    Returns dict employer_id -> charge_amount_cents. Sum == payable_amount_cents.

    Tie-break order for leftover cents (PRD §3.5.2):
      (1) largest fractional remainder DESC,
      (2) larger base-period wages DESC,
      (3) earlier Employer.created_at ASC (never id).
    """
    if not employer_wage_pairs:
        return {}
    total_wages = sum(w for (_eid, w, _ca, _sq) in employer_wage_pairs)
    if total_wages <= 0:
        return {eid: 0 for (eid, _w, _ca, _sq) in employer_wage_pairs}

    floors = {}
    remainders = {}  # employer_id -> (remainder_numerator)
    for (eid, wages, created_at, seq) in employer_wage_pairs:
        # raw_share = payable * wages / total_wages
        numerator = payable_amount_cents * wages
        floor_share = numerator // total_wages
        rem = numerator - floor_share * total_wages  # remainder numerator
        floors[eid] = floor_share
        remainders[eid] = rem

    leftover = payable_amount_cents - sum(floors.values())

    # Order employers for leftover distribution.
    # Build a lookup for wages/created_at/seq.
    meta = {eid: (wages, created_at, seq)
            for (eid, wages, created_at, seq) in employer_wage_pairs}

    def order_key(eid):
        wages, created_at, seq = meta[eid]
        # remainder DESC -> negate; wages DESC -> negate; created_at ASC; seq ASC
        return (-remainders[eid], -wages, created_at, seq)

    ordered = sorted(meta.keys(), key=order_key)
    charges = dict(floors)
    for i in range(leftover):
        charges[ordered[i]] += 1
    return charges
