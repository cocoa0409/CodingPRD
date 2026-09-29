"""Exact integer arithmetic: rounding, royalty rating, the payable waterfall,
minimum-guarantee shortfalls, audit restatement and the central-pool split.

Every amount is an integer number of cents; every rate an integer number of
basis points. Rounding half up and flooring are never interchanged, and the
rounding operand / evaluation order of each step is pinned exactly as PRD
section 3 states it.
"""

from fractions import Fraction

CHANNEL_CLASS_ORDER = ["DEPARTMENT", "SPECIALTY", "MASS", "ECOMMERCE", "OFF_PRICE", "ALL"]

LATE_INTEREST_BPS_PER_DAY = 5
ADMIN_FEE_BPS = 150
ADMIN_FEE_WAIVER_FLOOR_CENTS = 100000
RECOUP_CAP_BPS_NORMAL = 10000
RECOUP_CAP_BPS_RESTRICTED = 5000
AUDIT_INTEREST_BPS_PER_QUARTER = 150
COST_SHIFT_THRESHOLD_BPS = 500
AUDIT_COST_FLAT_CENTS = 750000
GROUP_LICENSING_SHARE_BPS = 2500
EQUAL_SPLIT_BPS = 7500


# --------------------------------------------------------------------------- #
# rounding primitives                                                         #
# --------------------------------------------------------------------------- #

def round_half_up(numerator, denominator=1):
    """Nearest whole unit, exact half away from zero."""
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((-2 * numerator + denominator) // (2 * denominator))


def round_half_up_frac(value):
    return round_half_up(value.numerator, value.denominator)


def floor_div(numerator, denominator=1):
    return numerator // denominator


def floor_frac(value):
    return value.numerator // value.denominator


def apply_rate_floor(amount, bps):
    return (amount * bps) // 10000


def apply_rate_half_up(amount, bps):
    return round_half_up(amount * bps, 10000)


# --------------------------------------------------------------------------- #
# tier lookup                                                                 #
# --------------------------------------------------------------------------- #

def tier_rate_for(category, basis):
    for tier in category["tier_schedule"]:
        upper = tier["to_cents"]
        if tier["from_cents"] <= basis and (upper is None or basis < upper):
            return tier["rate_bps"]
    return category["tier_schedule"][-1]["rate_bps"]


def line_sort_key(line):
    cls = line.get("channel_class")
    if cls in CHANNEL_CLASS_ORDER:
        return CHANNEL_CLASS_ORDER.index(cls)
    return len(CHANNEL_CLASS_ORDER)


def ordered_lines(lines):
    return sorted(lines, key=line_sort_key)


def closeout_eligible_for(line, category):
    return min(line["closeout_sales_cents"],
               apply_rate_floor(line["gross_sales_cents"], category["closeout_cap_pct_bps"]))


def allowed_deduction_for(line, category):
    return min(line["deductions_cents"],
               apply_rate_floor(line["gross_sales_cents"], category["deduction_cap_pct_bps"]))


# --------------------------------------------------------------------------- #
# PROVISIONAL_QUARTERLY royalty computation                                    #
# --------------------------------------------------------------------------- #

def compute_royalty(lines, category):
    """Per-line carve-outs, one report-wide tier rate, per-line rounding then sum."""
    parts = []
    net_total = 0
    closeout_total = 0
    for line in ordered_lines(lines):
        ce = closeout_eligible_for(line, category)
        ad = allowed_deduction_for(line, category)
        nr = line["gross_sales_cents"] - ce - ad
        parts.append((nr, ce))
        net_total += nr
        closeout_total += ce

    rate_bps = tier_rate_for(category, net_total)

    royalty = 0
    for nr, ce in parts:
        royalty += apply_rate_half_up(nr, rate_bps)
        royalty += apply_rate_half_up(ce, category["closeout_rate_bps"])

    return {
        "net_regular_total_cents": net_total,
        "closeout_eligible_total_cents": closeout_total,
        "applied_tier_rate_bps": rate_bps,
        "royalty_due_cents": royalty,
    }


# --------------------------------------------------------------------------- #
# the six-step payable waterfall                                              #
# --------------------------------------------------------------------------- #

def recoup_cap_bps(posture):
    if posture in ("PROBATION", "FROZEN"):
        return RECOUP_CAP_BPS_RESTRICTED
    return RECOUP_CAP_BPS_NORMAL


def payable_waterfall(royalty_cents, unrecouped_advance_cents, posture, late_days):
    cap = recoup_cap_bps(posture)
    recoupment = min(unrecouped_advance_cents, apply_rate_floor(royalty_cents, cap))
    cash_due_pre_fee = royalty_cents - recoupment
    interest = round_half_up(
        cash_due_pre_fee * LATE_INTEREST_BPS_PER_DAY * late_days, 10000)
    if cash_due_pre_fee >= ADMIN_FEE_WAIVER_FLOOR_CENTS:
        admin_fee = 0
    else:
        admin_fee = apply_rate_half_up(cash_due_pre_fee, ADMIN_FEE_BPS)
    total = cash_due_pre_fee + interest + admin_fee
    return {
        "recoupment_applied_cents": recoupment,
        "cash_due_pre_fee_cents": cash_due_pre_fee,
        "late_days": late_days,
        "late_filing_interest_cents": interest,
        "admin_fee_cents": admin_fee,
        "total_payable_cents": total,
    }


# --------------------------------------------------------------------------- #
# minimum-guarantee shortfall variants                                        #
# --------------------------------------------------------------------------- #

def term_quarter_counts(start_quarter, end_quarter, as_of_quarter, elapsed_quarters):
    total = elapsed_quarters(start_quarter, end_quarter) + 1
    elapsed = elapsed_quarters(start_quarter, as_of_quarter) + 1
    if elapsed < 0:
        elapsed = 0
    if elapsed > total:
        elapsed = total
    return total, elapsed


def interim_shortfall(minimum_guarantee_cents, earned_cents, total_quarters, elapsed):
    prorated = round_half_up(minimum_guarantee_cents * elapsed, total_quarters)
    return max(0, prorated - earned_cents)


def final_shortfall(minimum_guarantee_cents, earned_cents):
    return max(0, minimum_guarantee_cents - earned_cents)


# --------------------------------------------------------------------------- #
# audit restatement                                                           #
# --------------------------------------------------------------------------- #

def restate_entry(entry, category):
    gross = entry["audited_gross_sales_cents"]
    closeout_eligible = min(entry["audited_closeout_cents"],
                            apply_rate_floor(gross, category["closeout_cap_pct_bps"]))
    allowed_deduction = min(entry["audited_deductions_cents"],
                            apply_rate_floor(gross, category["deduction_cap_pct_bps"]))
    net_regular = gross - closeout_eligible - allowed_deduction
    rate_bps = tier_rate_for(category, net_regular)
    recomputed = (apply_rate_half_up(net_regular, rate_bps)
                  + apply_rate_half_up(closeout_eligible, category["closeout_rate_bps"]))
    return recomputed


def audit_interest(underreported_cents, elapsed):
    return round_half_up(
        underreported_cents * AUDIT_INTEREST_BPS_PER_QUARTER * elapsed, 10000)


def underreport_rate(underreported_cents, reported_cents):
    if reported_cents == 0:
        return 0
    return (underreported_cents * 10000) // reported_cents


# --------------------------------------------------------------------------- #
# annual true-up                                                              #
# --------------------------------------------------------------------------- #

def marginal_tier_total(category, cumulative_basis):
    total = 0
    for tier in category["tier_schedule"]:
        upper = tier["to_cents"]
        width = cumulative_basis if upper is None else upper - tier["from_cents"]
        portion = cumulative_basis - tier["from_cents"]
        if portion < 0:
            portion = 0
        if portion > width:
            portion = width
        total += apply_rate_half_up(portion, tier["rate_bps"])
    return total


# --------------------------------------------------------------------------- #
# central pool split                                                          #
# --------------------------------------------------------------------------- #

def split_club_pool(club_pool_cents, clubs):
    """clubs: list of dicts with club_code and revenue_share_units, any order.

    Returns a list of allocation dicts in ascending club_code order.
    """
    participants = sorted(clubs, key=lambda c: c["club_code"])
    count = len(participants)
    units_total = sum(c["revenue_share_units"] for c in participants)

    equal_total = apply_rate_floor(club_pool_cents, EQUAL_SPLIT_BPS)
    weighted_total = club_pool_cents - equal_total

    rows = []
    for club in participants:
        exact_equal = Fraction(equal_total, count)
        if units_total > 0:
            exact_weighted = Fraction(weighted_total * club["revenue_share_units"],
                                      units_total)
        else:
            exact_weighted = Fraction(0)
        exact_raw = exact_equal + exact_weighted
        base = floor_frac(exact_raw)
        rows.append({
            "club": club,
            "equal_component_cents": floor_frac(exact_equal),
            "weighted_component_cents": floor_frac(exact_weighted),
            "base_cents": base,
            "fraction": exact_raw - base,
        })

    remainder = club_pool_cents - sum(r["base_cents"] for r in rows)
    ranked = sorted(rows, key=lambda r: (-r["fraction"], r["club"]["club_code"]))
    for index, row in enumerate(ranked):
        row["remainder_cent_applied"] = 1 if index < remainder else 0
    for row in rows:
        row["amount_cents"] = row["base_cents"] + row["remainder_cent_applied"]
    return rows
