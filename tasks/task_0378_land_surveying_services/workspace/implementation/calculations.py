"""Fee, window, and risk calculations (PRD §3.7, §3.8)."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

# Constants (PRD §3.7)
BASE_FEE_BY_TYPE = {
    "BOUNDARY": 120000,
    "TOPO": 180000,
    "ALTA": 350000,
    "ELEVATION": 90000,
}
# Acre tiers: (band width in acres, rate cents/acre). Last band is unbounded.
# First 5 acres @ 8000; next 15 (above 5 up to 20) @ 5000; remainder @ 3000.
ACRE_TIERS = [
    (Decimal("5"), Decimal("8000")),
    (Decimal("15"), Decimal("5000")),
    (None, Decimal("3000")),
]
RUSH_PCT = Decimal("0.30")
TAX_PCT = Decimal("0.0825")

RESEAL_FEE_BY_REASON = {
    "CLIENT_CHANGE": 40000,
    "DEED_DISCREPANCY": 25000,
    "FIELD_ERROR": 0,
}

MAX_SEALABLE_CLOSURE_PPM = 100
TURNAROUND_MINUTES = 60

# Risk score constants (PRD §3.8)
OPEN_CAP = 5
EXPIRY_WARN_DAYS = 30
W_LOAD = Decimal("0.6")
W_LICENSE = Decimal("0.4")


def round_half_up(value):
    """Round a Decimal to nearest whole integer, half rounds up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def field_fee_cents(acreage):
    """Tiered per-acre field-fee component (PRD §3.7).

    For each band, multiply acres in band by band rate, round the product
    half-up, then sum the rounded band products.
    """
    acres = Decimal(str(acreage))
    remaining = acres
    total = 0
    for width, rate in ACRE_TIERS:
        if remaining <= 0:
            break
        if width is None:
            band_acres = remaining
        else:
            band_acres = min(remaining, width)
        band_product = round_half_up(band_acres * rate)
        total += band_product
        remaining -= band_acres
    return total


def estimate_fee_cents(survey_type, acreage, rush):
    """order_fee_estimate (PRD §3.7 estimate variant)."""
    base = BASE_FEE_BY_TYPE[survey_type]
    field = field_fee_cents(acreage)
    pre_rush = base + field
    rush_fee = round_half_up(Decimal(pre_rush) * RUSH_PCT) if rush else 0
    return base, field, rush_fee, base + field + rush_fee


def invoice_final_components(order, applied_reseal_total):
    """invoice_final_fee (PRD §3.7 actual variant). Returns (subtotal, tax, total)."""
    base = order["base_fee_cents"]
    field = field_fee_cents(order["acreage"])
    pre_rush = base + field
    rush_fee = round_half_up(Decimal(pre_rush) * RUSH_PCT) if order["rush"] else 0
    subtotal = base + field + rush_fee + applied_reseal_total
    tax = round_half_up(Decimal(subtotal) * TAX_PCT)
    total = subtotal + tax
    return subtotal, tax, total


def reseal_fee_for_reason(reason):
    return RESEAL_FEE_BY_REASON[reason]


def window_minutes(scheduled_start, scheduled_end):
    """floor((end - start) / 60) in whole minutes (PRD §3.7)."""
    start = _parse_dt(scheduled_start)
    end = _parse_dt(scheduled_end)
    delta_seconds = (end - start).total_seconds()
    return int(delta_seconds // 60)


def crew_risk_score(crew):
    """crew_member_risk_score (PRD §3.8)."""
    open_count = crew.get("open_assignment_count", 0)
    capped = min(open_count, OPEN_CAP)
    load_factor = Decimal(capped) / Decimal(OPEN_CAP)
    license_factor = Decimal("0")
    if crew.get("role_type") == "PLS" and crew.get("license_expires_on"):
        expires = _parse_dt(crew["license_expires_on"])
        now = datetime.now(timezone.utc)
        delta_days = (expires - now).total_seconds() / 86400.0
        # within thirty days of the current moment
        if delta_days <= EXPIRY_WARN_DAYS:
            license_factor = Decimal("1")
    raw = W_LOAD * load_factor + W_LICENSE * license_factor
    return round_half_up(raw * Decimal("100"))


def _parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
