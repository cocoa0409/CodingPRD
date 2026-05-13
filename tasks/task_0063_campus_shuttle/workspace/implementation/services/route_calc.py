"""Route distance / duration calculations per PRD §3.2 + scaffold §1.3."""
from decimal import Decimal, ROUND_HALF_UP
import math

import db
from services.util import haversine_km, half_up


AVG_SPEED_KMH = 25
DWELL_MIN = 1
PEAK_FACTOR = Decimal("1.25")


def route_stop_sequence_ids(route: dict) -> list:
    """Return [start_stop_id, *intermediate_stop_ids, end_stop_id]."""
    return [route["start_stop_id"]] + list(route.get("intermediate_stop_ids", [])) + [route["end_stop_id"]]


def compute_distance_km(route: dict) -> float:
    """Sum haversine distances between consecutive stops, per-segment 4dp, total 2dp."""
    seq_ids = route_stop_sequence_ids(route)
    total = Decimal("0")
    for i in range(len(seq_ids) - 1):
        a = db.stops[seq_ids[i]]
        b = db.stops[seq_ids[i + 1]]
        seg = haversine_km(a["latitude"], a["longitude"],
                           b["latitude"], b["longitude"])
        total += seg
    total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(total)


def compute_duration_minutes_base(distance_km: float, intermediate_count: int) -> int:
    """BASE variant: distance/speed*60 + 1 dwell per intermediate, ceiling to whole minute."""
    travel_min = (Decimal(str(distance_km)) / Decimal(AVG_SPEED_KMH)) * Decimal(60)
    total = travel_min + Decimal(DWELL_MIN * intermediate_count)
    return int(math.ceil(float(total)))


def compute_duration_minutes_peak_adjusted(distance_km: float,
                                           intermediate_count: int,
                                           is_peak: bool) -> int:
    """PEAK_ADJUSTED variant: travel time * 1.25 if peak; dwell unaffected; ceil."""
    travel_min = (Decimal(str(distance_km)) / Decimal(AVG_SPEED_KMH)) * Decimal(60)
    if is_peak:
        travel_min = travel_min * PEAK_FACTOR
    total = travel_min + Decimal(DWELL_MIN * intermediate_count)
    return int(math.ceil(float(total)))
