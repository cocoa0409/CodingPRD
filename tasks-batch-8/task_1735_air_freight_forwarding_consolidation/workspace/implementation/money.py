"""Decimal arithmetic helpers (PRD §2.8, scaffold §1.3).

All money is Decimal, rounded half-up to exactly two decimal places.
Chargeable weight rounds UP (ceiling) to the next 0.5 kg — never banker's
rounding, never nearest.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

CENT = Decimal("0.01")
HALF_KG = Decimal("0.5")
DIM_FACTOR_M3_PER_KG = Decimal("0.006")   # 1 kg per 6000 cm3 (IATA divisor)
SPOT_THRESHOLD_PCT = Decimal("85.0")      # inclusive
SDR_PER_KG = Decimal("22")                # Montreal Convention 1999
SDR_TO_USD = Decimal("1.35")              # fixed conversion for this benchmark
DEMERIT_LIMIT = 3                         # inclusive


def dec(value):
    """Coerce a JSON number (int/float/str) to Decimal without float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value.strip())
    raise ValueError("not a number")


def round2(d):
    """Round half-up to two decimal places."""
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def ceil_half_kg(d):
    """Round UP to the next 0.5 kg step (ceiling in 0.5 kg units)."""
    return (d / HALF_KG).quantize(Decimal("1"), rounding=ROUND_CEILING) * HALF_KG


def chargeable_weight(gross_weight_kg, volume_m3):
    """max(gross, volume / DIM_FACTOR) rounded up to the next 0.5 kg."""
    dim = volume_m3 / DIM_FACTOR_M3_PER_KG
    raw = gross_weight_kg if gross_weight_kg >= dim else dim
    return ceil_half_kg(raw)


def num(d):
    """Serialize a Decimal (or plain number) as a JSON number."""
    if isinstance(d, Decimal):
        return float(d)
    return d
