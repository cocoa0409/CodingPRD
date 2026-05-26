"""Calculation rules per SCAFFOLD §1.3 and PRD §3.3/§3.5/§3.7/§3.8.

All monetary math uses Decimal with ROUND_HALF_UP. No floats for money.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


# --- Poverty guideline constants (per SCAFFOLD §1.3 idr_monthly_payment.constants) ---
POVERTY_BASE_CENTS = {
    "CONTIGUOUS_48": 1558000,
    "ALASKA":        1947000,
    "HAWAII":        1791000,
}
POVERTY_PER_MEMBER_CENTS = {
    "CONTIGUOUS_48": 548000,
    "ALASKA":        686000,
    "HAWAII":        630000,
}

# Map of two-letter US state codes to poverty-guideline table key.
# Per scaffold: state_code "selects the poverty-guideline table (CONTIGUOUS_48, ALASKA, HAWAII)".
_STATE_TO_TABLE = {"AK": "ALASKA", "HI": "HAWAII"}


def _poverty_table_key(state_code: str) -> str:
    return _STATE_TO_TABLE.get(state_code, "CONTIGUOUS_48")


def round_half_up(value: Decimal) -> int:
    """Round Decimal to integer using ROUND_HALF_UP."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ============================================================
# Date parsing helpers
# ============================================================

def parse_iso_to_dt(s: str) -> datetime:
    """Parse an ISO 8601 string to a tz-aware UTC datetime."""
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    s = str(s)
    # Accept trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Try parsing date-only forms
        try:
            d = date.fromisoformat(s)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_to_date(s: str) -> date:
    """Get the calendar date (UTC) component."""
    return parse_iso_to_dt(s).date()


# ============================================================
# idr_monthly_payment (SCAFFOLD §1.3)
# ============================================================

def compute_monthly_payment_cents(plan_type: str, principal_cents: int,
                                  rate_bps: int, agi_cents, family_size,
                                  state_code) -> int:
    """Return monthly payment in integer cents.

    For STANDARD: 120-month amortization on principal_cents at rate_bps.
    For IBR/PAYE/SAVE: discretionary-income formula.
    """
    if plan_type == "STANDARD":
        # monthly_rate = rate_bps / 10000 / 12
        monthly_rate = Decimal(rate_bps) / Decimal(10000) / Decimal(12)
        n = 120
        principal = Decimal(principal_cents)
        if monthly_rate == 0:
            monthly = principal / Decimal(n)
        else:
            # monthly = P * r / (1 - (1+r)^(-n))
            one_plus_r_pow_minus_n = (Decimal(1) + monthly_rate) ** (-n)
            denom = Decimal(1) - one_plus_r_pow_minus_n
            monthly = principal * monthly_rate / denom
        return round_half_up(monthly)

    # IDR plans require certified income evidence.
    if agi_cents is None or family_size is None or state_code is None:
        # Per PRD: monthly_payment_cents is computed immediately at create time;
        # if no certified evidence exists, treat discretionary as zero -> payment 0.
        return 0

    table = _poverty_table_key(state_code)
    pg_base = POVERTY_BASE_CENTS[table]
    pg_per_member = POVERTY_PER_MEMBER_CENTS[table]
    poverty_line = Decimal(pg_base) + Decimal(pg_per_member) * (Decimal(family_size) - Decimal(1))

    if plan_type == "SAVE":
        multiplier = Decimal("2.25")
        rate = Decimal("0.10")
    elif plan_type in ("IBR", "PAYE"):
        multiplier = Decimal("1.50")
        rate = Decimal("0.15") if plan_type == "IBR" else Decimal("0.10")
    else:
        # Unknown plan type — should be guarded upstream.
        return 0

    discretionary = Decimal(agi_cents) - multiplier * poverty_line
    if discretionary < 0:
        discretionary = Decimal(0)
    annual = rate * discretionary
    monthly = annual / Decimal(12)
    return round_half_up(monthly)


# ============================================================
# interest_accrual (SCAFFOLD §1.3 interest_accrual)
# ============================================================

# Statuses on which DIRECT_SUB is subsidized (no accrual today).
_SUBSIDIZED_STATUSES = {"IN_SCHOOL", "GRACE", "DEFERMENT"}


def accrue_interest(loan: dict, status_history: list, target_dt: datetime):
    """Replay each day in [last_accrual_date, target_dt) inclusive of start, exclusive of end.

    status_history: list of (effective_at_dt, to_status) tuples, ordered ASC,
                    representing the loan's status timeline.
    Per-day rounding mandated by §2.6 and §1.3.

    Mutates loan in place: accrued_interest_cents bumped; last_accrual_date := target_dt.
    """
    last = parse_iso_to_dt(loan["last_accrual_date"])
    if target_dt <= last:
        return  # nothing to accrue

    # Build a function that returns loan status on a given UTC date.
    # status_history entries: list of (dt, status). The loan's status at any moment
    # is the most recent entry with dt <= moment, falling back to ORIGINATED if none.
    def status_at(day: date) -> str:
        # Use end-of-day as the query instant for "status on this calendar day".
        # A status change recorded at any instant within the calendar day governs that day.
        query_dt = datetime(day.year, day.month, day.day, 23, 59, 59, 999000, tzinfo=timezone.utc)
        # Walk history; pick last entry with effective_at <= query_dt.
        chosen = None
        for eff_at, st in status_history:
            if eff_at <= query_dt:
                chosen = st
            else:
                break
        return chosen if chosen is not None else "ORIGINATED"

    rate_bps = loan["interest_rate_bps"]
    daily_rate = Decimal(rate_bps) / Decimal(10000) / Decimal(365)
    loan_type = loan["loan_type"]

    cur_day = last.date()
    end_day = target_dt.date()
    accrued_delta = 0
    while cur_day < end_day:
        st_today = status_at(cur_day)
        subsidized = (loan_type == "DIRECT_SUB" and st_today in _SUBSIDIZED_STATUSES)
        if not subsidized:
            principal = Decimal(loan["principal_balance_cents"])
            day_accrual = principal * daily_rate
            accrued_delta += round_half_up(day_accrual)
        cur_day = cur_day + timedelta(days=1)

    loan["accrued_interest_cents"] = int(loan["accrued_interest_cents"]) + accrued_delta
    # Advance last_accrual_date to current clock (per formula final step).
    loan["last_accrual_date"] = _iso_z(target_dt)


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
