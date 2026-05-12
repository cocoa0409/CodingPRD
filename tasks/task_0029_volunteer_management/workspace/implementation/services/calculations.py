"""Pure calculation utilities — haversine, hours, points."""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from clock import parse_iso


EARTH_RADIUS_KM = 6371.0088
HOURS_TO_POINTS = 10
DIFFICULTY_MULTIPLIERS = {"EASY": "1.00", "MEDIUM": "1.50", "HARD": "2.00"}
ROLE_MULTIPLIERS = {"LEAD": "1.20", "SUPPORT": "1.00", "REGULAR": "0.90"}
DEFAULT_ROLE_MULTIPLIER = "1.00"
LEAVE_PENALTY = "0.50"
EARLY_PENALTY = "0.75"


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1 - a)))
    d = EARTH_RADIUS_KM * c
    quant = Decimal(str(d)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(quant)


def _round2(d_or_str) -> Decimal:
    return Decimal(str(d_or_str)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_service_hours(application: dict, activity: dict, role: dict | None) -> float:
    """Implements service_hour_calc per scaffold §1.3."""
    hour_rule = activity.get("hour_rule_type", "ACTUAL_DURATION")

    # Step 1: raw hours per branch
    if hour_rule == "FIXED_VALUE":
        raw = Decimal(str(activity.get("fixed_hour_value") or 0))
    else:
        ci = application.get("check_in_at")
        co = application.get("check_out_at")
        if not ci or not co:
            return 0.0
        elapsed_seconds = (parse_iso(co) - parse_iso(ci)).total_seconds()
        elapsed_hours = Decimal(str(elapsed_seconds / 3600.0))
        if hour_rule == "ROLE_COEFFICIENT":
            coeff = Decimal(str((role or {}).get("coefficient", 1.0)))
            raw = elapsed_hours * coeff
        else:  # ACTUAL_DURATION
            raw = elapsed_hours

    # Step 2/3: leave (dominant) vs early-departure (mutually exclusive in this order).
    if application.get("_leave_was_reached"):
        hours = raw * Decimal(LEAVE_PENALTY)
    elif application.get("early_departure_marker"):
        hours = raw * Decimal(EARLY_PENALTY)
    else:
        hours = raw

    return float(_round2(hours))


def compute_points_awarded(adjusted_hours: float, activity: dict, role: dict | None) -> int:
    """Implements point_earn_calc per scaffold §1.3 with pinned evaluation order."""
    base = _round2(Decimal(str(adjusted_hours)) * Decimal(HOURS_TO_POINTS))
    diff_mult = Decimal(DIFFICULTY_MULTIPLIERS.get(activity.get("difficulty", "MEDIUM"), "1.50"))
    if role and role.get("role_label") in ROLE_MULTIPLIERS:
        role_mult = Decimal(ROLE_MULTIPLIERS[role["role_label"]])
    else:
        role_mult = Decimal(DEFAULT_ROLE_MULTIPLIER)
    raw_points = base * diff_mult * role_mult
    floored = raw_points.quantize(Decimal("1"), rounding=ROUND_FLOOR)
    return int(floored)
