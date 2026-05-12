"""Storage fee, handover fee, and final-total pricing calculations."""
from decimal import Decimal, ROUND_HALF_UP, getcontext
from math import ceil

getcontext().prec = 28

T1_HOURS = 24
T2_HOURS = 72
RATE1 = Decimal("0.50")
RATE2 = Decimal("1.00")
RATE3 = Decimal("2.00")
SIZE_MULTIPLIER = {
    "S": Decimal("1.0"),
    "M": Decimal("1.0"),
    "L": Decimal("1.5"),
    "XL": Decimal("2.0"),
}

HANDOVER_FEE_PER_PARCEL = Decimal("0.80")


def _round2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round4(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def storage_fee_at(free_storage_deadline, t, size_class: str) -> float:
    """Compute storage fee for a parcel given its free_storage_deadline and an
    evaluation time t (datetime). Returns a 2-decimal float."""
    if free_storage_deadline is None or t is None:
        return 0.0
    if t <= free_storage_deadline:
        return 0.0
    diff_seconds = (t - free_storage_deadline).total_seconds()
    overdue_hours_real = diff_seconds / 3600.0
    overdue_hours = int(ceil(overdue_hours_real))
    if overdue_hours <= 0:
        return 0.0
    tier1 = min(overdue_hours, T1_HOURS)
    tier2 = max(0, min(overdue_hours - T1_HOURS, T2_HOURS))
    tier3 = max(0, overdue_hours - T1_HOURS - T2_HOURS)
    raw = Decimal(tier1) * RATE1 + Decimal(tier2) * RATE2 + Decimal(tier3) * RATE3
    mult = SIZE_MULTIPLIER.get(size_class, Decimal("1.0"))
    final = _round2(raw * mult)
    return float(final)


def handover_fee_amount(parcel_count: int) -> float:
    n = Decimal(parcel_count)
    return float(_round2(n * HANDOVER_FEE_PER_PARCEL))


def period_final_total(handover_total, factor, storage_total) -> float:
    """Pinned rounding order:
       round(handover_total * factor) FIRST, then add storage_total, then round again."""
    h = Decimal(str(handover_total))
    f = Decimal(str(factor))
    s = Decimal(str(storage_total))
    adjusted = _round2(h * f)
    final = _round2(adjusted + s)
    return float(final)


def round_money(v) -> float:
    return float(_round2(Decimal(str(v))))


def round_rate4(v) -> float:
    return float(_round4(Decimal(str(v))))


def quality_composite(mis_shelving_rate, lost_parcel_rate, complaint_rate,
                      response_timeliness_score) -> float:
    """Round each component rate to 4 decimals before mixing; composite to 2 decimals."""
    m = _round4(Decimal(str(mis_shelving_rate)))
    l = _round4(Decimal(str(lost_parcel_rate)))
    c = _round4(Decimal(str(complaint_rate)))
    r = _round4(Decimal(str(response_timeliness_score)))
    one = Decimal("1")
    composite = (
        Decimal("0.30") * (one - m)
        + Decimal("0.30") * (one - l)
        + Decimal("0.20") * (one - c)
        + Decimal("0.20") * r
    )
    return float(_round2(composite))


def quality_factor_for(composite: float) -> float:
    c = Decimal(str(composite))
    if c >= Decimal("0.95"):
        return 1.05
    if c >= Decimal("0.85"):
        return 1.00
    if c >= Decimal("0.70"):
        return 0.95
    return 0.85
