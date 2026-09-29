"""The fifteen calculation rules of the price posting program.

Money is always an integer count of cents. Percentages are decimal fractions.
Rounding is round-half-up everywhere except the promotional allowance cap, which
floors (PRD section 2.6).
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from store import MONTH_RE, SECONDS_PER_DAY, db, dt_of, fmt_iso, seq_of

CLERICAL_LIMIT_PCT = Decimal("0.10")

# invoice_settlement_total bands
BAND_1_UPPER_CENTS = 500000
BAND_2_UPPER_CENTS = 2000000
BAND_1_PCT = Decimal("0.000")
BAND_2_PCT = Decimal("0.005")
BAND_3_PCT = Decimal("0.010")

# combination_sale_min_price bands
COMBO_BAND_1_UPPER_CENTS = 50000
COMBO_BAND_2_UPPER_CENTS = 150000
COMBO_BAND_1_PCT = Decimal("0.00")
COMBO_BAND_2_PCT = Decimal("0.05")
COMBO_BAND_3_PCT = Decimal("0.10")

# audit_penalty_assessment tiers
TIER_1_MAX_PRIOR = 2
TIER_2_MAX_PRIOR = 9
TIER_1_MULTIPLIER = Decimal("1.00")
TIER_2_MULTIPLIER = Decimal("1.50")
TIER_3_MULTIPLIER = Decimal("2.00")


def dec(value):
    """Exact Decimal from an int, float or string without binary artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal to whole cents, halves going away from zero."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_cents(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# 1. schedule_effective_date
# ---------------------------------------------------------------------------
def schedule_effective_date(posting_month):
    m = MONTH_RE.match(posting_month)
    year, month = int(m.group(1)), int(m.group(2))
    if month == 12:
        eff_year, eff_month = year + 1, 1
    else:
        eff_year, eff_month = year, month + 1
    return "%04d-%02d-01T00:00:00.000Z" % (eff_year, eff_month)


# ---------------------------------------------------------------------------
# 2. late_filing_determination
# ---------------------------------------------------------------------------
def deadline_instant(posting_month, posting_deadline_day):
    m = MONTH_RE.match(posting_month)
    year, month = int(m.group(1)), int(m.group(2))
    return datetime(
        year,
        month,
        int(posting_deadline_day),
        23,
        59,
        59,
        999000,
        tzinfo=timezone.utc,
    )


def is_late_filing(posting_month, posting_deadline_day, filed_at_dt):
    """The deadline instant itself is inclusive -- only strictly after it is late."""
    return filed_at_dt > deadline_instant(posting_month, posting_deadline_day)


# ---------------------------------------------------------------------------
# 3. hold_window_containment
# ---------------------------------------------------------------------------
def hold_window_end(certified_at_dt, hold_window_days):
    return certified_at_dt + timedelta(seconds=int(hold_window_days) * SECONDS_PER_DAY)


def hold_window_is_open(schedule, now_dt_value):
    """Half-open interval [certified_at, hold_window_ends_at)."""
    certified_at = dt_of(schedule.get("certified_at"))
    window_end = dt_of(schedule.get("hold_window_ends_at"))
    if certified_at is None or window_end is None:
        return False
    return certified_at <= now_dt_value < window_end


# ---------------------------------------------------------------------------
# 4. correction_window_containment
# ---------------------------------------------------------------------------
def correction_window_end(certified_at_dt, correction_window_days):
    return certified_at_dt + timedelta(
        seconds=int(correction_window_days) * SECONDS_PER_DAY
    )


def correction_window_is_open(schedule, program, now_dt_value):
    certified_at = dt_of(schedule.get("certified_at"))
    if certified_at is None:
        return False
    end = correction_window_end(certified_at, program["correction_window_days"])
    return now_dt_value < end


# ---------------------------------------------------------------------------
# 5. correction_variance_pct
# ---------------------------------------------------------------------------
def correction_variance_pct(prior_case_price_cents, corrected_case_price_cents):
    """Unrounded decimal fraction of the case-price movement."""
    if prior_case_price_cents == 0:
        return Decimal(0)
    return abs(
        dec(corrected_case_price_cents) - dec(prior_case_price_cents)
    ) / dec(prior_case_price_cents)


def exceeds_clerical_limit(variance):
    """Strictly greater than the limit is a rewrite; exactly equal is accepted."""
    return dec(variance) > CLERICAL_LIMIT_PCT


# ---------------------------------------------------------------------------
# 6. tier_discounted_case_price
# ---------------------------------------------------------------------------
def tier_discounted_case_price(case_price_cents, discount_pct):
    return round_half_up(dec(case_price_cents) * (Decimal(1) - dec(discount_pct)))


# ---------------------------------------------------------------------------
# 7. posted_case_price_resolution
# ---------------------------------------------------------------------------
def posting_key(item):
    schedule = db.price_schedules[item["schedule_id"]]
    brand = db.brands[item["brand_id"]]
    return (
        schedule["wholesaler_id"],
        schedule["state_program_id"],
        brand["brand_name"],
        brand["beverage_class"],
        item["size_ml"],
        item["bottles_per_case"],
    )


_MIN_DT = datetime(1, 1, 1, tzinfo=timezone.utc)


def resolve_posted_item(subject_item, as_of_dt):
    """The candidate that won the resolution, or None when no price is posted."""
    key = posting_key(subject_item)
    best = None
    best_rank = None
    for candidate in db.price_schedule_items.values():
        if candidate["status"] not in ("EFFECTIVE", "SUPERSEDED"):
            continue
        if posting_key(candidate) != key:
            continue
        schedule = db.price_schedules[candidate["schedule_id"]]
        effective = dt_of(schedule.get("effective_date"))
        if effective is None or effective > as_of_dt:
            continue
        certified = dt_of(schedule.get("certified_at")) or _MIN_DT
        rank = (effective, certified, dt_of(candidate["created_at"]), seq_of(candidate))
        if best is None or _resolution_better(rank, best_rank):
            best = candidate
            best_rank = rank
    return best


def _resolution_better(a, b):
    """Greatest effective_date, then greatest certified_at, then earliest created_at."""
    if a[0] != b[0]:
        return a[0] > b[0]
    if a[1] != b[1]:
        return a[1] > b[1]
    if a[2] != b[2]:
        return a[2] < b[2]
    return a[3] < b[3]


def posted_prices(resolved_item, variant):
    if resolved_item is None:
        return None, None
    if variant == "as_certified":
        return (
            resolved_item.get("certified_case_price_cents"),
            resolved_item.get("certified_unit_price_cents"),
        )
    return resolved_item["case_price_cents"], resolved_item["unit_price_cents"]


# ---------------------------------------------------------------------------
# 8. wholesaler_penalty_exposure
# ---------------------------------------------------------------------------
def accrued_exposure(wholesaler):
    return (
        wholesaler["late_filing_penalty_accrued_cents"]
        + wholesaler["correction_penalty_accrued_cents"]
        + wholesaler["amendment_penalty_accrued_cents"]
        + wholesaler["assessed_penalty_cents"]
    )


def provisional_exposure(wholesaler):
    """Projection of findings sitting in OPEN and COLLECTED audits, multiplier 1.00."""
    total = 0
    for audit in db.compliance_audits.values():
        if audit["wholesaler_id"] != wholesaler["id"]:
            continue
        if audit["status"] not in ("OPEN", "COLLECTED"):
            continue
        program = db.state_programs.get(audit["state_program_id"])
        rate = program["off_posted_penalty_rate_pct"] if program else 0
        for finding in db.audit_findings.values():
            if finding["audit_id"] != audit["id"]:
                continue
            total += round_half_up(dec(finding["variance_cents"]) * dec(rate))
    return total


# ---------------------------------------------------------------------------
# 9. invoice_line_net_price
# ---------------------------------------------------------------------------
def _tiers_of_item(item_id):
    return [t for t in db.quantity_discount_tiers.values() if t["item_id"] == item_id]


def select_quantity_tier(item_id, cases_quantity):
    """Greatest min_cases, then greatest discount_pct, then earliest created_at."""
    best = None
    best_rank = None
    for tier in _tiers_of_item(item_id):
        if tier["status"] != "ACTIVE":
            continue
        if tier["min_cases"] > cases_quantity:
            continue
        rank = (
            tier["min_cases"],
            dec(tier["discount_pct"]),
            dt_of(tier["created_at"]),
            seq_of(tier),
        )
        if best is None or _tier_better(rank, best_rank):
            best = tier
            best_rank = rank
    return best


def _tier_better(a, b):
    if a[0] != b[0]:
        return a[0] > b[0]
    if a[1] != b[1]:
        return a[1] > b[1]
    if a[2] != b[2]:
        return a[2] < b[2]
    return a[3] < b[3]


def price_invoice_line(line, item, program):
    """Gross, quantity discount, capped allowances and the resulting net amount."""
    cases = line["cases_quantity"]
    bottles = line["bottles_quantity"]
    gross = cases * line["case_price_charged_cents"] + bottles * line[
        "unit_price_charged_cents"
    ]

    quantity_discount = 0
    if program["quantity_discount_allowed"]:
        tier = select_quantity_tier(item["id"], cases)
        if tier is not None:
            quantity_discount = cases * (
                item["case_price_cents"] - tier["discounted_case_price_cents"]
            )

    promotional_cap = floor_cents(
        dec(gross) * dec(program["max_promotional_allowance_pct"])
    )
    allowed_promotional = min(line["promotional_allowance_cents"], promotional_cap)
    excess_promotional = line["promotional_allowance_cents"] - allowed_promotional

    depletion_cap = cases * program["depletion_allowance_per_case_cents"]
    allowed_depletion = min(line["depletion_allowance_cents"], depletion_cap)
    excess_depletion = line["depletion_allowance_cents"] - allowed_depletion

    net = gross - quantity_discount - allowed_promotional - allowed_depletion
    return {
        "gross_cents": gross,
        "quantity_discount_cents": quantity_discount,
        "allowed_promotional_cents": allowed_promotional,
        "excess_promotional_cents": excess_promotional,
        "allowed_depletion_cents": allowed_depletion,
        "excess_depletion_cents": excess_depletion,
        "net_price_cents": net,
    }


# ---------------------------------------------------------------------------
# 10. off_posted_detection
# ---------------------------------------------------------------------------
def detect_off_posted(line, item, priced, invoice_date_dt):
    resolved = resolve_posted_item(item, invoice_date_dt)
    cases = line["cases_quantity"]
    bottles = line["bottles_quantity"]
    gross = priced["gross_cents"]
    if resolved is None:
        return {
            "posted_gross_cents": 0,
            "variance_cents": 0,
            "finding_variance_cents": gross,
            "is_off_posted": True,
        }, None
    posted_case, posted_unit = posted_prices(resolved, "as_amended")
    posted_gross = cases * (posted_case or 0) + bottles * (posted_unit or 0)
    variance = posted_gross - gross
    finding_variance = (
        abs(variance) + priced["excess_promotional_cents"] + priced["excess_depletion_cents"]
    )
    return {
        "posted_gross_cents": posted_gross,
        "variance_cents": variance,
        "finding_variance_cents": finding_variance,
        "is_off_posted": finding_variance != 0,
    }, resolved


# ---------------------------------------------------------------------------
# 11. invoice_settlement_total
# ---------------------------------------------------------------------------
def surcharge_pct_for(subtotal_cents):
    if subtotal_cents < BAND_1_UPPER_CENTS:
        return BAND_1_PCT
    if subtotal_cents < BAND_2_UPPER_CENTS:
        return BAND_2_PCT
    return BAND_3_PCT


def settle_invoice(lines):
    subtotal = sum(line["net_price_cents"] for line in lines)
    surcharge = round_half_up(dec(subtotal) * surcharge_pct_for(subtotal))
    total_allowance = sum(
        line["allowed_promotional_cents"] + line["allowed_depletion_cents"]
        for line in lines
    )
    off_posted = [line for line in lines if line["is_off_posted"]]
    return {
        "subtotal_cents": subtotal,
        "surcharge_cents": surcharge,
        "total_cents": subtotal + surcharge,
        "total_allowance_cents": total_allowance,
        "off_posted_line_count": len(off_posted),
        "total_variance_cents": sum(
            line["finding_variance_cents"] for line in off_posted
        ),
    }


# ---------------------------------------------------------------------------
# 12. combination_sale_min_price
# ---------------------------------------------------------------------------
def combo_band_pct(floor_price_cents):
    if floor_price_cents < COMBO_BAND_1_UPPER_CENTS:
        return COMBO_BAND_1_PCT
    if floor_price_cents < COMBO_BAND_2_UPPER_CENTS:
        return COMBO_BAND_2_PCT
    return COMBO_BAND_3_PCT


def combination_sale_min_price(member_items):
    floor_price = sum(item["case_price_cents"] for item in member_items)
    band = combo_band_pct(floor_price)
    minimum = round_half_up(dec(floor_price) * (Decimal(1) - band))
    return floor_price, minimum


# ---------------------------------------------------------------------------
# 13. combination_window_cooldown
# ---------------------------------------------------------------------------
def combination_conflicts(new_start, new_end, existing_start, existing_end, cooldown_days):
    buffer_delta = timedelta(seconds=int(cooldown_days) * SECONDS_PER_DAY)
    return (new_start < existing_end + buffer_delta) and (
        existing_start < new_end + buffer_delta
    )


# ---------------------------------------------------------------------------
# 14. audit_penalty_assessment
# ---------------------------------------------------------------------------
def penalty_component(variance_cents, off_posted_penalty_rate_pct):
    return round_half_up(dec(variance_cents) * dec(off_posted_penalty_rate_pct))


def tier_multiplier_for(prior_violation_count):
    if prior_violation_count <= TIER_1_MAX_PRIOR:
        return TIER_1_MULTIPLIER
    if prior_violation_count <= TIER_2_MAX_PRIOR:
        return TIER_2_MULTIPLIER
    return TIER_3_MULTIPLIER


def escalated_penalty(base_penalty_cents, multiplier):
    return round_half_up(dec(base_penalty_cents) * dec(multiplier))


# ---------------------------------------------------------------------------
# 15. amendment_price_admissibility
# ---------------------------------------------------------------------------
def is_reduction(new_case_price_cents, amending_case_price_cents):
    return new_case_price_cents < amending_case_price_cents


def is_at_or_above_reference(new_case_price_cents, reference_case_price_cents):
    return new_case_price_cents >= reference_case_price_cents
