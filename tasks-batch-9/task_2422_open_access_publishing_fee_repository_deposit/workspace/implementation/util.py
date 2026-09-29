"""Numeric, rounding and calendar helpers (PRD 2.7, 3.8)."""
import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

FISCAL_YEAR_START_MONTH = 7
FISCAL_YEAR_START_DAY = 1


def dec(value):
    """Decimal from an int/float/str without binary float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal/number to a whole integer, half away from zero."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_places(value, places):
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def parse_iso_date(raw):
    """Strict YYYY-MM-DD parse. Returns a date or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def iso_date(value):
    if value is None:
        return None
    return value.isoformat()


def add_days(base, days):
    return base + timedelta(days=days)


def add_months(base, months):
    """Keep the day of month, clamping to the last day of the target month."""
    total = base.month - 1 + months
    year = base.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(base.day, last_day))


def fiscal_year_of(day):
    """FY N runs (N-1)-07-01 .. N-06-30 inclusive (PRD 2.7)."""
    if (day.month, day.day) >= (FISCAL_YEAR_START_MONTH, FISCAL_YEAR_START_DAY):
        return day.year + 1
    return day.year


def fiscal_year_window(fiscal_year):
    return (date(fiscal_year - 1, 7, 1), date(fiscal_year, 6, 30))
