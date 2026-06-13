"""Geographic distance and ETA (PRD §2.5)."""
import math
from decimal import Decimal, ROUND_HALF_UP

EARTH_RADIUS_MILES = 3958.7613
AVG_SPEED_MPH = 40
MAX_DISPATCH_RADIUS_MILES = 50


def haversine_miles(lat1, lng1, lat2, lng2):
    """Great-circle distance in miles, rounded to 3 decimals (round-half-up)."""
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2)
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    miles = EARTH_RADIUS_MILES * c
    return float(Decimal(str(miles)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def eta_minutes(offer_distance_miles):
    """ceil(distance / AVG_SPEED_MPH * 60) — whole minutes.

    Use Decimal so that a mathematically-exact integer-minute value (e.g. a
    distance yielding exactly 30.0 minutes) ceils to 30, not 31, while genuine
    fractional minutes round up.
    """
    minutes = (Decimal(str(offer_distance_miles)) / Decimal(AVG_SPEED_MPH)) * Decimal(60)
    return int(minutes.to_integral_value(rounding="ROUND_CEILING"))
