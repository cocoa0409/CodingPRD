"""Pure calculation routines per SCAFFOLD §1.3.

All monetary values are integer cents. Decimal is used for
employer charge allocation to keep the rounding deterministic.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Tuple

from ..util import add_quarters, quarter_of_month


# -- Constants from SCAFFOLD --------------------------------------------------
MIN_BASE_PERIOD_WAGES_CENTS = 150_000      # $1,500.00
MIN_HIGH_QUARTER_WAGES_CENTS = 90_000      # $900.00
WBA_DIVISOR = 26
MIN_WBA_CENTS = 4_000                      # $40.00
MAX_WBA_CENTS = 60_000                     # $600.00
WEEKS_DENOMINATOR_FACTOR = 3
MIN_REGULAR_WEEKS = 13
MAX_REGULAR_WEEKS = 26
EARNINGS_DISREGARD_PCT = 25
APPEAL_WINDOW_DAYS = 30
STATUTE_OF_LIMITATIONS_DAYS = 1825         # 5 years
MIN_WORK_SEARCH_CONTACTS = 3
FLOOR_RATE_BPS = 100
CEILING_RATE_BPS = 540


def filing_quarter(filing_year: int, filing_month: int) -> Tuple[int, int]:
    """Return (year, quarter_index 1..4) for the filing month."""
    return filing_year, quarter_of_month(filing_month)


def standard_base_period_quarters(fy: int, fq: int) -> List[Tuple[int, int]]:
    """STANDARD base period: filing_quarter [t-5, t-4, t-3, t-2]."""
    return [add_quarters(fy, fq, delta) for delta in (-5, -4, -3, -2)]


def alternate_base_period_quarters(fy: int, fq: int) -> List[Tuple[int, int]]:
    """ALTERNATE base period: filing_quarter [t-4, t-3, t-2, t-1]."""
    return [add_quarters(fy, fq, delta) for delta in (-4, -3, -2, -1)]


def sum_wages_in_quarters(
    wage_records: List[Dict[str, Any]],
    claimant_id: str,
    quarters: List[Tuple[int, int]],
) -> int:
    qset = set(quarters)
    return sum(
        wr["wages_cents"]
        for wr in wage_records
        if wr["claimant_id"] == claimant_id
        and (wr["quarter_year"], wr["quarter_index"]) in qset
    )


def high_quarter_wages_in_quarters(
    wage_records: List[Dict[str, Any]],
    claimant_id: str,
    quarters: List[Tuple[int, int]],
) -> int:
    qset = set(quarters)
    per_quarter: Dict[Tuple[int, int], int] = {}
    for wr in wage_records:
        if wr["claimant_id"] != claimant_id:
            continue
        key = (wr["quarter_year"], wr["quarter_index"])
        if key not in qset:
            continue
        per_quarter[key] = per_quarter.get(key, 0) + wr["wages_cents"]
    if not per_quarter:
        return 0
    return max(per_quarter.values())


def choose_base_period(
    wage_records: List[Dict[str, Any]],
    claimant_id: str,
    filing_year: int,
    filing_month: int,
) -> Tuple[str, int, int, List[Tuple[int, int]]]:
    """Choose STANDARD or ALTERNATE base period per pinned variant order.

    Returns (variant, total_wages_cents, high_quarter_wages_cents, quarters).
    """
    fy, fq = filing_quarter(filing_year, filing_month)
    std_qs = standard_base_period_quarters(fy, fq)
    alt_qs = alternate_base_period_quarters(fy, fq)

    std_total = sum_wages_in_quarters(wage_records, claimant_id, std_qs)
    alt_total = sum_wages_in_quarters(wage_records, claimant_id, alt_qs)

    if std_total >= MIN_BASE_PERIOD_WAGES_CENTS:
        chosen = "STANDARD"
        qs = std_qs
        total = std_total
    elif alt_total >= MIN_BASE_PERIOD_WAGES_CENTS:
        chosen = "ALTERNATE"
        qs = alt_qs
        total = alt_total
    else:
        chosen = "STANDARD"
        qs = std_qs
        total = std_total

    hq = high_quarter_wages_in_quarters(wage_records, claimant_id, qs)
    return chosen, total, hq, qs


def compute_weekly_benefit_amount(high_quarter_wages_cents: int) -> int:
    """WBA = clamp(floor(high_q / 26), MIN, MAX). Truncate, not round."""
    wba_raw = high_quarter_wages_cents // WBA_DIVISOR  # python floor div on positives
    return max(MIN_WBA_CENTS, min(MAX_WBA_CENTS, wba_raw))


def compute_max_weeks(base_period_total_wages_cents: int, wba_cents: int) -> int:
    """max weeks = clamp(floor(total / (wba * 3)), 13, 26)."""
    if wba_cents <= 0:
        return MIN_REGULAR_WEEKS
    denom = wba_cents * WEEKS_DENOMINATOR_FACTOR
    potential = base_period_total_wages_cents // denom
    return min(MAX_REGULAR_WEEKS, max(MIN_REGULAR_WEEKS, potential))


def compute_payable_amount(wba_cents: int, earnings_reported_cents: int) -> int:
    """Earnings disregard: floor(wba * 25 / 100). Offset above; payable >=0."""
    disregard = (wba_cents * EARNINGS_DISREGARD_PCT) // 100
    offset = max(0, earnings_reported_cents - disregard)
    return max(0, wba_cents - offset)


def allocate_employer_charges(
    payment_amount_cents: int,
    base_period_total_wages_cents: int,
    wages_by_employer: List[Tuple[str, int]],
) -> List[Tuple[str, int]]:
    """Allocate `payment_amount_cents` across employers proportionally to
    `wages_by_employer` (a list of (employer_id, wages_E_cents) tuples).

    Rounding order (PINNED):
      1. Compute charge_E_raw at full precision (no rounding).
      2. Round each to nearest cent using ROUND_HALF_UP.
      3. residual = payment_amount_cents - sum(rounded).
      4. Distribute residual one cent at a time to employers sorted by
         wages_E DESCENDING; tie-break by Employer.id ASCENDING.
    """
    if base_period_total_wages_cents <= 0 or payment_amount_cents <= 0:
        return [(eid, 0) for (eid, _w) in wages_by_employer]

    total = Decimal(base_period_total_wages_cents)
    amount = Decimal(payment_amount_cents)

    raw: List[Tuple[str, int, Decimal]] = []
    rounded_sum = 0
    rounded_charges: Dict[str, int] = {}
    for emp_id, wages_e in wages_by_employer:
        share = Decimal(wages_e) / total
        raw_charge = amount * share
        rounded = int(raw_charge.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        rounded_charges[emp_id] = rounded
        rounded_sum += rounded
        raw.append((emp_id, wages_e, raw_charge))

    residual = payment_amount_cents - rounded_sum

    # Sort employers by wages_e DESC, then employer_id ASC for residual distribution
    order = sorted(wages_by_employer, key=lambda t: (-t[1], t[0]))

    if residual > 0:
        i = 0
        while residual > 0 and order:
            emp_id = order[i % len(order)][0]
            rounded_charges[emp_id] += 1
            residual -= 1
            i += 1
    elif residual < 0:
        i = 0
        while residual < 0 and order:
            emp_id = order[i % len(order)][0]
            rounded_charges[emp_id] -= 1
            residual += 1
            i += 1

    # Preserve the input order of wages_by_employer in the result
    return [(eid, rounded_charges[eid]) for (eid, _w) in wages_by_employer]


def compute_experience_rate_bps(
    reserve_ratio_basis_cents: int,
    taxable_payroll_cents: int,
    active_charges_sum: int,
    relieved_charges_sum: int,
) -> int:
    """Return tier rate in basis points.

    net_charges = active_charges_sum - relieved_charges_sum
    adjusted_reserve = max(0, reserve_basis - net_charges)
    reserve_ratio = adjusted_reserve / taxable_payroll (rational; we use Decimal)

    Tier table (lower-bound inclusive, picking largest bound the ratio satisfies):
      >= 0.10 -> 100
      >= 0.07 -> 180
      >= 0.04 -> 270
      >= 0.01 -> 380
      >= 0.00 -> 460
      <  0.00 -> 540

    NOTE: PRD §3.3 says "the greater of zero and (reserve - net_charges)". So
    the adjusted_reserve floor is 0, which means reserve_ratio is never
    strictly negative as long as taxable_payroll > 0. However, we keep the
    540 ceiling for the strictly-negative case for parity with the scaffold.
    """
    if taxable_payroll_cents <= 0:
        # Undefined; default to ceiling.
        return CEILING_RATE_BPS

    net_charges = active_charges_sum - relieved_charges_sum
    adjusted_reserve = reserve_ratio_basis_cents - net_charges
    # PRD §3.3: adjusted_reserve = max(0, reserve_basis - net_charges)
    floored_reserve = max(0, adjusted_reserve)

    ratio = Decimal(floored_reserve) / Decimal(taxable_payroll_cents)

    # Pre-floor case: if adjusted_reserve was strictly negative before floor,
    # the ratio "should" be < 0 per the literal scaffold formula. We surface
    # that as 540. After the floor, ratio is at least 0, so we need a
    # separate flag for the negative case.
    if adjusted_reserve < 0:
        return CEILING_RATE_BPS

    if ratio >= Decimal("0.10"):
        return 100
    if ratio >= Decimal("0.07"):
        return 180
    if ratio >= Decimal("0.04"):
        return 270
    if ratio >= Decimal("0.01"):
        return 380
    if ratio >= Decimal("0.00"):
        return 460
    return CEILING_RATE_BPS
