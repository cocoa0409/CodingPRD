"""All calculation rules (PRD §2.5, §3; SCAFFOLD §1.3).

Monetary amounts are integer cents. Fractional intermediates (percentage
discounts, per-kg anesthesia) round half up (away from zero) per PRD §2.5.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --- vaccine constants (SCAFFOLD §1.3 vaccine_next_due) ---
STANDARD_VACCINE_FEE_CENTS = 4500
REMINDER_LEAD_DAYS = 14
MIN_INTERVAL_DAYS = {
    "RABIES": 365,
    "DHPP": 21,
    "BORDETELLA": 180,
    "FVRCP": 21,
}

# --- wellness constants ---
REFERENCE_ANNUAL_SERVICE_CENTS = 60000
TIER_SERVICE_DISCOUNT_PCT = {
    "BASIC": Decimal("0.10"),
    "PLUS": Decimal("0.20"),
    "PREMIER": Decimal("0.30"),
}
TIER_BUNDLED_VACCINES = {
    "BASIC": 2,
    "PLUS": 4,
    "PREMIER": 8,
}

# --- surgery constants (SCAFFOLD §1.3 surgery_total) ---
PROCEDURE_BASE_CENTS = 20000
ANES_RATE_SMALL_CENTS = 800
ANES_RATE_MEDIUM_CENTS = 600
ANES_RATE_LARGE_CENTS = 500
FREE_MINUTES = 60
TIME_RATE_CENTS_PER_MIN = 150
MIN_SURGERY_CENTS = 25000
MAX_SURGERY_CENTS = 500000

# --- controlled substance ---
CONTROLLED_COOLDOWN_DAYS = 30


def round_half_up(value):
    """Round a numeric (possibly Decimal/float/int) to the nearest integer,
    half rounding away from zero (PRD §2.5)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_dt(value):
    """Parse an ISO 8601 string to a timezone-aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = value
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# -----------------------------------------------------------------------------
# Rule 1A: estimate_projected_total (forward-looking; round per line, then sum)
# -----------------------------------------------------------------------------
def estimate_projected_total(line_items, plan):
    """PRD §3.6: discounts rounded per line item BEFORE summing."""
    total = 0
    discount_pct = plan["service_discount_pct"] if plan else None
    for li in line_items:
        gross = int(li["unit_price_cents"]) * int(li["qty"])
        if li.get("eligible_for_plan_discount") and plan is not None:
            discount = round_half_up(Decimal(gross) * Decimal(str(discount_pct)))
        else:
            discount = 0
        total += gross - discount
    return total


# -----------------------------------------------------------------------------
# Rule 1B: wellness savings (projected vs realized)
# -----------------------------------------------------------------------------
def wellness_projected_savings(tier, service_discount_pct):
    """PRD §3.2: full bundle * standard fee + round_half_up(ref spend * pct)."""
    bundle_savings = TIER_BUNDLED_VACCINES[tier] * STANDARD_VACCINE_FEE_CENTS
    service_savings = round_half_up(
        Decimal(REFERENCE_ANNUAL_SERVICE_CENTS) * Decimal(str(service_discount_pct))
    )
    return bundle_savings + service_savings


# -----------------------------------------------------------------------------
# Rule 2: surgery_total (>=3 inputs, weight-band tiered, clamp)
# -----------------------------------------------------------------------------
def surgery_total(weight_kg, window_start, window_end):
    """PRD §3.8."""
    base = PROCEDURE_BASE_CENTS
    w = Decimal(str(weight_kg))
    if w <= 5:
        anesthesia_raw = w * ANES_RATE_SMALL_CENTS
    elif w <= 25:
        anesthesia_raw = w * ANES_RATE_MEDIUM_CENTS
    else:
        anesthesia_raw = w * ANES_RATE_LARGE_CENTS
    anesthesia = round_half_up(anesthesia_raw)

    minutes = window_minutes(window_start, window_end)
    excess = max(0, minutes - FREE_MINUTES)
    time_surcharge = excess * TIME_RATE_CENTS_PER_MIN

    raw = base + anesthesia + time_surcharge
    return min(MAX_SURGERY_CENTS, max(MIN_SURGERY_CENTS, raw))


def window_minutes(window_start, window_end):
    start = parse_dt(window_start)
    end = parse_dt(window_end)
    return int((end - start).total_seconds() // 60)


# -----------------------------------------------------------------------------
# boarding_total: inclusive-day night count
# -----------------------------------------------------------------------------
def boarding_total(check_in_date, check_out_date, nightly_rate_cents):
    """PRD §3.9: nights = inclusive-day span; same-day == 1 night."""
    ci = parse_dt(check_in_date).date()
    co = parse_dt(check_out_date).date()
    nights = (co - ci).days + 1
    return int(nightly_rate_cents) * nights


# -----------------------------------------------------------------------------
# vaccine_next_due / reminder schedule
# -----------------------------------------------------------------------------
def vaccine_schedule(vaccine_code, administered_at):
    """PRD §3.4: next_due = administered + interval days; reminder = next_due - 14 days."""
    interval = MIN_INTERVAL_DAYS[vaccine_code]
    adm = parse_dt(administered_at)
    next_due = adm + timedelta(days=interval)
    reminder = next_due - timedelta(days=REMINDER_LEAD_DAYS)
    return to_iso(next_due), to_iso(reminder)
