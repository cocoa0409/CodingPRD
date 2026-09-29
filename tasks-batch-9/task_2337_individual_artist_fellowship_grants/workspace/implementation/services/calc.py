"""The ten declared calculations (PRD section 6 / SCAFFOLD section 1.3).

Every money and score value is produced with Decimal arithmetic and
ROUND_HALF_UP.  Floats never take part in a computation; they only appear when
a rounded Decimal is handed to the JSON encoder.
"""

import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import constants as C

ZERO = Decimal(0)
ONE = Decimal(1)


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places) if places else ONE
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def money(value):
    """Round half up to whole cents."""
    return int(rhu(value, 0))


def num(value, places):
    """Round half up to `places` places and hand back a JSON number."""
    return float(rhu(value, places))


# ------------------------------------------------------- 1. residency months


def residency_months(start_date, deadline_dt):
    """Whole completed months between residency_start_date and the deadline."""
    if start_date is None or deadline_dt is None:
        return 0
    d1 = deadline_dt.date()
    months = (d1.year - start_date.year) * 12 + (d1.month - start_date.month)
    anniversary_day = min(start_date.day, calendar.monthrange(d1.year, d1.month)[1])
    if d1.day < anniversary_day:
        months -= 1
    return max(0, months)


# --------------------------------------------------- 2. review weighted score

WEIGHTS = (
    ("artistic_excellence", Decimal("0.40")),
    ("work_sample_quality", Decimal("0.30")),
    ("career_impact", Decimal("0.20")),
    ("public_value", Decimal("0.10")),
)


def review_weighted_score(review):
    total = ZERO
    for field, weight in WEIGHTS:
        total += weight * D(review[field])
    return num(total, 2)


# ----------------------------------------------- 3. application composite set

TRIM_MIN_SEATS = 5
SPREAD_REOPEN_THRESHOLD = Decimal("2.50")


def composite_scores(weighted_scores, seated_count):
    """Return (provisional, final, spread) for the counted review set.

    `weighted_scores` must already be in created_at ascending order.
    """
    values = [D(v) for v in weighted_scores]
    n = len(values)
    if n == 0:
        return None, None, None
    provisional = num(sum(values) / D(n), 2)
    kept = values
    if seated_count >= TRIM_MIN_SEATS and n >= 3:
        high = _first_index(values, max(values))
        rest = [i for i in range(n) if i != high]
        low = _first_index_in(values, rest, min(values[i] for i in rest))
        kept = [values[i] for i in range(n) if i not in (high, low)]
    final = num(sum(kept) / D(len(kept)), 2)
    spread = num(max(values) - min(values), 2)
    return provisional, final, spread


def _first_index(values, target):
    for i, value in enumerate(values):
        if value == target:
            return i
    return 0


def _first_index_in(values, indexes, target):
    for i in indexes:
        if values[i] == target:
            return i
    return indexes[0]


def spread_requires_reopen(spread):
    return spread is not None and D(spread) > SPREAD_REOPEN_THRESHOLD


# --------------------------------------------------- 4. panel readiness score

CHARTER_READINESS_MIN = Decimal("75.00")
CONFLICT_PENALTY_PER = Decimal("0.08")
CONFLICT_PENALTY_CAP = Decimal("0.40")
BONUS_EXPERTISE = "TRADITIONAL_ARTS"


def panel_readiness_score(seated_count, required_seats, region_coverage_count,
                          required_region_count, blocking_conflict_count, has_bonus):
    seat_ratio = min(ONE, D(seated_count) / D(required_seats)) if required_seats else ONE
    if required_region_count:
        region_ratio = min(ONE, D(region_coverage_count) / D(required_region_count))
    else:
        region_ratio = ONE
    penalty = min(CONFLICT_PENALTY_CAP, CONFLICT_PENALTY_PER * D(blocking_conflict_count))
    conflict_multiplier = ONE - penalty
    bonus = Decimal("1.10") if has_bonus else Decimal("1.00")
    raw = D(100) * seat_ratio * region_ratio * conflict_multiplier * bonus
    return num(min(D(100), raw), 2)


QUORUM_SEAT_RATIO_NUMERATOR = 6
QUORUM_FLOOR = 3


def quorum_min_reviews(required_seats):
    seats = int(required_seats or 0)
    return max(QUORUM_FLOOR, (seats * QUORUM_SEAT_RATIO_NUMERATOR + 9) // 10)


# ------------------------------------------------------ 5. cycle admin assessment

ASSESSMENT_TIERS = (
    (2000000, Decimal("0.085")),
    (8000000, Decimal("0.070")),
)
ASSESSMENT_TOP_RATE = Decimal("0.055")


def admin_assessment(funded_total_cents):
    """Return (rate, assessment_cents); the basis is evaluated exactly once."""
    basis = int(funded_total_cents or 0)
    if basis == 0:
        return 0.0, 0
    rate = ASSESSMENT_TOP_RATE
    for ceiling, tier_rate in ASSESSMENT_TIERS:
        if basis <= ceiling:
            rate = tier_rate
            break
    return float(rate), money(D(basis) * rate)


# ------------------------------------------------------- 6. cycle budget posture

RESERVE_RATE = Decimal("0.05")


def reserve_cents(cycle):
    if cycle["status"] in C.RESERVE_STATUSES:
        return money(D(cycle["total_budget_cents"]) * RESERVE_RATE)
    return 0


def budget_posture(cycle, funded_total, assessment, reserve, breach_count, blocking_count):
    committed = int(funded_total) + int(assessment)
    available = int(cycle["total_budget_cents"]) - int(reserve) - committed
    if cycle["status"] == "CANCELLED":
        posture = "FROZEN"
    elif breach_count > 0:
        posture = "FROZEN"
    elif available < int(cycle["base_award_cents"]):
        posture = "RESTRICTED"
    elif blocking_count > 0:
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    return committed, available, posture


# --------------------------------------------------- 7. award waterfall allocation


def waterfall_allocation(cycle, discipline, committed_cents):
    """Return (amount_cents, is_prorated) or (None, None) when exhausted."""
    remaining = int(discipline["allocation_cents"]) - int(committed_cents)
    base = int(cycle["base_award_cents"])
    floor = int(cycle["min_prorated_award_cents"])
    if remaining >= base:
        return base, False
    if remaining >= floor and cycle["proration_policy"] == "PRORATE":
        return remaining, True
    return None, None


# ------------------------------------------------ 8. installment payment schedule

BACKUP_WITHHOLDING_RATE = Decimal("0.2707")
INSTALLMENT_SPLITS = (Decimal("0.40"), Decimal("0.35"))
INSTALLMENT_OFFSET_DAYS = (0, 120, 240)


def payment_schedule(gross_cents, tin_status, grant_period_start_date):
    rate = ZERO if tin_status == "ON_FILE" else BACKUP_WITHHOLDING_RATE
    gross = int(gross_cents)
    first = money(D(gross) * INSTALLMENT_SPLITS[0])
    second = money(D(gross) * INSTALLMENT_SPLITS[1])
    third = gross - first - second
    out = []
    for index, amount in enumerate((first, second, third)):
        withholding = money(D(amount) * rate)
        out.append(
            {
                "installment_number": index + 1,
                "gross_cents": amount,
                "withholding_rate": float(rate),
                "withholding_cents": withholding,
                "net_cents": amount - withholding,
                "offset_days": INSTALLMENT_OFFSET_DAYS[index],
                "scheduled_date": grant_period_start_date
                + timedelta(days=INSTALLMENT_OFFSET_DAYS[index]),
            }
        )
    return out


# ------------------------------------------------ 9. award tax reportable amount


def tax_reportable(installments, tax_year, basis):
    gross = 0
    withholding = 0
    counted = []
    for row in installments:
        if basis == "CASH":
            if row["status"] != "PAID" or not row.get("paid_at"):
                continue
            stamp = row["paid_at"]
        else:
            if row["status"] == "VOIDED":
                continue
            stamp = row["scheduled_date"]
        if stamp is None or int(str(stamp)[:4]) != int(tax_year):
            continue
        counted.append(row)
        gross += int(row["gross_cents"])
        withholding += int(row["withholding_cents"])
    return {
        "gross_cents": gross,
        "withholding_cents": withholding,
        "net_cents": gross - withholding,
        "installment_count": len(counted),
    }


# --------------------------------------------- 10. cycle diversity evaluation


def diversity_evaluation(pool, funded_count, disciplines, discipline_rows):
    """Return the evaluation payload for a cycle."""
    total = len(pool)
    if total == 0:
        return {
            "eligible_pool_size": 0,
            "region_hhi": None,
            "geographic_distribution_score": None,
            "funded_rate": None,
            # An empty pool reports both breakdowns empty (§3.11).
            "region_breakdown": [],
            "discipline_breakdown": [],
        }
    counts = {}
    for app in pool:
        region = app.get("applicant_region")
        counts[region] = counts.get(region, 0) + 1
    hhi = ZERO
    for count in counts.values():
        share = D(count) / D(total)
        hhi += share * share
    hhi_rounded = rhu(hhi, 4)
    score = rhu(D(125) * (ONE - hhi_rounded), 2)
    breakdown = []
    for region in sorted(counts, key=lambda value: (value is None, value)):
        breakdown.append(
            {
                "region": region,
                "applicant_count": counts[region],
                "share": num(D(counts[region]) / D(total), 4),
            }
        )
    return {
        "eligible_pool_size": total,
        "region_hhi": float(hhi_rounded),
        "geographic_distribution_score": float(score),
        "funded_rate": num(D(funded_count) / D(total), 4),
        "region_breakdown": breakdown,
        "discipline_breakdown": discipline_rows,
    }
