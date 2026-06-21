"""Calculation rules (SCAFFOLD §1.3, PRD §2.9 / §3.2 / §3.5 / §3.6 / §3.9)."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta
import math

R_MILES = 3958.7613
AVG_SPEED_MPH = 25.0


def _round_half_up(value, places):
    """Round-half-up to a fixed number of decimal places, returned as a float."""
    q = Decimal(1).scaleb(-places)  # e.g. places=2 -> Decimal('0.01')
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    return float(d)


def haversine_miles(lat1, lng1, lat2, lng2):
    """Great-circle straight-line distance in miles (raw, unrounded)."""
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    c = 2 * math.asin(math.sqrt(a))
    return R_MILES * c


def home_distance_miles(home_lat, home_lng, school_lat, school_lng):
    """home -> school great-circle distance, rounded half-up to 2 dp."""
    raw = haversine_miles(home_lat, home_lng, school_lat, school_lng)
    return _round_half_up(raw, 2)


def eligibility_basis(distance_2dp, threshold, hazard_override_enabled, hazard_zone):
    """Distance dominates; hazard is an override only when enabled. Strict > on
    the 2-dp ROUNDED distance vs threshold (round-then-compare)."""
    if distance_2dp > threshold:
        return "DISTANCE"
    if hazard_override_enabled and hazard_zone:
        return "HAZARD"
    return "NONE"


def eta_minutes(origin_lat, origin_lng, next_lat, next_lng):
    """Straight-line distance origin -> next stop / avg speed -> minutes, 1 dp."""
    dist = haversine_miles(origin_lat, origin_lng, next_lat, next_lng)
    minutes = (dist / AVG_SPEED_MPH) * 60.0
    return _round_half_up(minutes, 1)


def parse_iso(ts):
    """Parse an ISO 8601 timestamp (with or without trailing Z) to aware UTC."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def deadline_after(scheduled_departure_iso, grace_minutes):
    """scheduled_departure + grace_minutes as an aware UTC datetime."""
    return parse_iso(scheduled_departure_iso) + timedelta(minutes=grace_minutes)
