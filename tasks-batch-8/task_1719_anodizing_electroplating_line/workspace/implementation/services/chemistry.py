"""Chemistry calculations: titration, dosing, amp-hours, bath life, dragout."""
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR


EQ_WEIGHTS = {
    "SULFURIC": Decimal("49.0"),
    "CHROMIC": Decimal("33.3"),
    "NICKEL": Decimal("29.35"),
    "ZINC": Decimal("32.69"),
    "COPPER": Decimal("31.77"),
    "CYANIDE": Decimal("49.0"),
}

DRAGOUT_RATE = Decimal("0.0008")  # g/L depleted per dm^2 of load surface area


def _d(v):
    return Decimal(str(v))


def round3(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_float(dec: Decimal) -> float:
    """Render a Decimal as a JSON number via float (values are small, exact-enough)."""
    return float(dec)


def titration_concentration(chemistry_family, titrant_volume_ml, titrant_normality, sample_volume_ml):
    """measured = round_half_up(titrant_volume_ml * normality * EQ_WEIGHT / sample_volume_ml, 3)."""
    eq = EQ_WEIGHTS[chemistry_family]
    measured = (_d(titrant_volume_ml) * _d(titrant_normality) * eq) / _d(sample_volume_ml)
    return round3(measured)


def dose_resulting_concentration(current_concentration_g_l, quantity_g, volume_liters):
    """round_half_up(current + quantity_g / volume_liters, 3)."""
    result = _d(current_concentration_g_l) + (_d(quantity_g) / _d(volume_liters))
    return round3(result)


def recommended_dose_g(bath):
    """round_half_up(max(0, target - current) * volume_liters, 0). Null current -> based on 0 shortfall? PRD: exposed in bath detail reads."""
    current = bath.get("current_concentration_g_l")
    if current is None:
        shortfall = _d(bath["target_concentration_g_l"])
    else:
        shortfall = _d(bath["target_concentration_g_l"]) - _d(current)
    if shortfall < 0:
        shortfall = Decimal("0")
    rec = (shortfall * _d(bath["volume_liters"])).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(rec)


def estimate_amp_hours(surface_area_dm2, current_density_a_dm2, duration_minutes):
    """round_half_up(surface_area * current_density * duration_minutes / 60, 2)."""
    est = (_d(surface_area_dm2) * _d(current_density_a_dm2) * _d(duration_minutes)) / Decimal("60")
    return round2(est)


def dragout_depletion(current_concentration_g_l, surface_area_dm2):
    """round_half_up(max(0, current - surface_area * 0.0008), 3)."""
    new = _d(current_concentration_g_l) - (_d(surface_area_dm2) * DRAGOUT_RATE)
    if new < 0:
        new = Decimal("0")
    return round3(new)


def nameplate_remaining_ah(bath):
    """amp_hour_capacity - amp_hour_used, carried to two decimals."""
    return round2(_d(bath["amp_hour_capacity"]) - _d(bath["amp_hour_used"]))


def effective_remaining_ah(bath):
    """floor((capacity - used) * efficiency); efficiency = 1.0 if current >= target
    else max(0.5, current/target). Requires current concentration non-null."""
    current = bath.get("current_concentration_g_l")
    if current is None:
        return None
    target = _d(bath["target_concentration_g_l"])
    if _d(current) >= target:
        efficiency = Decimal("1.0")
    else:
        ratio = _d(current) / target
        efficiency = ratio if ratio > Decimal("0.5") else Decimal("0.5")
    remaining = (_d(bath["amp_hour_capacity"]) - _d(bath["amp_hour_used"])) * efficiency
    floored = remaining.quantize(Decimal("1"), rounding=ROUND_FLOOR)
    return int(floored)


def concentration_in_band(bath):
    """current within [low, high] inclusive; null current -> False."""
    current = bath.get("current_concentration_g_l")
    if current is None:
        return False
    return _d(bath["low_concentration_g_l"]) <= _d(current) <= _d(bath["high_concentration_g_l"])


# Chemistry-to-analyte map for the exceedance cascade
CHEMISTRY_TO_ANALYTE = {
    "NICKEL": "NICKEL",
    "ZINC": "ZINC",
    "COPPER": "COPPER",
    "CHROMIC": "CHROME",
    "CYANIDE": "CYANIDE",
    "SULFURIC": None,  # never quarantined by exceedance
}
