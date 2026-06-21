"""Calculation rules (SCAFFOLD Table 3 / PRD Section 3)."""
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# --- Constants from the scaffold ---
POVERTY_BASE_CENTS = 130000
POVERTY_PER_PERSON_CENTS = 47000
ELIGIBILITY_CUTOFF = Decimal("1.25")

APPEAL_BASE_FEE_CENTS = 5000
RATE1 = 50   # cents/page for pages 1-100
RATE2 = 30   # cents/page for pages 101-500
RATE3 = 15   # cents/page for pages 501+

BPS_DIVISOR = 10000
DAYS_PER_YEAR = 365

POSTURE_DEADLINE_LIMIT = 5


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO-8601 datetime/date string into a tz-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # Date-only string like YYYY-MM-DD
            d = date.fromisoformat(str(value).strip())
            dt = datetime(d.year, d.month, d.day)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_date(value):
    return parse_dt(value).date()


def end_of_day_utc(d):
    """Pin a date to 23:59:59.000Z."""
    dt = datetime.combine(d, time(23, 59, 59, 0), tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _is_nonbusiness(d, holidays, business_days_only):
    if not business_days_only:
        return False
    if d.weekday() >= 5:  # Sat=5, Sun=6
        return True
    if d.isoformat() in holidays:
        return True
    return False


# ---------------------------------------------------------------------------
# due_date_calc
# ---------------------------------------------------------------------------
def due_date_calc(anchor_date, interval_days, counting_mode, court):
    """Compute a Deadline.due_date per the two calendaring variants."""
    business_days_only = court.get("business_days_only", True)
    holidays = set(court.get("holidays", []) or [])
    base = to_date(anchor_date)

    if counting_mode == "CALENDAR":
        # Variant A: add the full interval as calendar days, then roll forward
        # off a weekend/holiday landing without re-counting.
        d = base + timedelta(days=interval_days)
        while _is_nonbusiness(d, holidays, business_days_only):
            d = d + timedelta(days=1)
    else:  # COURT_DAYS
        # Variant B: step one day at a time from the day after the anchor,
        # counting only court days until interval_days have been counted.
        d = base
        counted = 0
        while counted < interval_days:
            d = d + timedelta(days=1)
            if not _is_nonbusiness(d, holidays, business_days_only):
                counted += 1
    return end_of_day_utc(d)


# ---------------------------------------------------------------------------
# judgment_interest
# ---------------------------------------------------------------------------
def judgment_interest(judgment, current_clock):
    principal = judgment.get("principal_cents", 0) or 0
    rate_bps = judgment.get("interest_rate_bps", 0) or 0
    entered_at = judgment.get("entered_at")
    if entered_at is None:
        return principal
    entered_date = to_date(entered_at)
    current_date = current_clock.date()
    elapsed_days = (current_date - entered_date).days
    if elapsed_days < 0:
        elapsed_days = 0
    daily_rate = Decimal(rate_bps) / Decimal(BPS_DIVISOR) / Decimal(DAYS_PER_YEAR)
    raw = Decimal(principal) * daily_rate * Decimal(elapsed_days)
    interest_cents = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return principal + interest_cents


# ---------------------------------------------------------------------------
# fee_waiver_eligibility
# ---------------------------------------------------------------------------
def fee_waiver_eligibility(monthly_income_cents, household_size):
    threshold = POVERTY_BASE_CENTS + (household_size - 1) * POVERTY_PER_PERSON_CENTS
    ratio = (Decimal(monthly_income_cents) / Decimal(threshold)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return float(ratio)


# ---------------------------------------------------------------------------
# appeal_transmittal_fee
# ---------------------------------------------------------------------------
def appeal_transmittal_fee(record_page_count):
    p = record_page_count
    tier1 = min(p, 100)
    tier2 = min(max(p - 100, 0), 400)
    tier3 = max(p - 500, 0)
    per_page = tier1 * RATE1 + tier2 * RATE2 + tier3 * RATE3
    return APPEAL_BASE_FEE_CENTS + per_page
