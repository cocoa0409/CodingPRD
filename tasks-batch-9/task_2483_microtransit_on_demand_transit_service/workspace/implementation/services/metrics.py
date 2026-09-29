"""The zone scorecard and the equivalent-service test (PRD Section 3.8)."""
from decimal import Decimal

import calculations as calc
import db

_METRIC_FIELDS = (
    "completed_trip_count", "unserved_trip_count", "avg_wait_minutes",
    "avg_ride_minutes", "boardings_per_revenue_hour", "wav_avg_wait_minutes",
    "nonwav_avg_wait_minutes", "wav_equivalence_ratio", "equivalence_verdict",
)


def _mean_2dp(values):
    if not values:
        return 0.00
    total = sum(calc.dec(v if v is not None else 0) for v in values)
    return calc.rhu_float(total / calc.dec(len(values)), 2)


def recompute_zone(zone):
    """Recompute every scorecard field; touch the zone only if something moved."""
    if zone is None:
        return
    zone_id = zone["id"]
    trips = [t for t in db.trip_requests.values() if t["zone_id"] == zone_id]
    completed = [t for t in trips if t["status"] == "COMPLETED"]

    avg_wait = _mean_2dp([t["wait_minutes"] for t in completed])
    avg_ride = _mean_2dp([t["ride_minutes"] for t in completed])

    wav = [t for t in completed if t["wav_required"] is True]
    nonwav = [t for t in completed if t["wav_required"] is False]
    wav_avg = _mean_2dp([t["wait_minutes"] for t in wav])
    nonwav_avg = _mean_2dp([t["wait_minutes"] for t in nonwav])

    if calc.dec(nonwav_avg) == Decimal("0.00"):
        ratio = 0.000
    else:
        ratio = calc.rhu_float(calc.dec(wav_avg) / calc.dec(nonwav_avg), 3)
    verdict = ("COMPLIANT" if calc.dec(ratio) <= calc.WAV_EQUIVALENCE_MAX_RATIO
               else "DEFICIENT")

    closed_blocks = [b for b in db.vehicle_blocks.values()
                     if b["zone_id"] == zone_id and b["state"] == "CLOSED"]
    total_boardings = sum(b["boardings_count"] for b in closed_blocks)
    total_revenue_hours = sum(calc.dec(b["actual_revenue_hours"])
                              for b in closed_blocks) if closed_blocks else Decimal(0)
    if total_revenue_hours == 0:
        boardings_per_revenue_hour = 0.00
    else:
        boardings_per_revenue_hour = calc.rhu_float(
            calc.dec(total_boardings) / total_revenue_hours, 2)

    computed = {
        "completed_trip_count": len(completed),
        "unserved_trip_count": len([t for t in trips if t["status"] == "NO_SERVICE"]),
        "avg_wait_minutes": avg_wait,
        "avg_ride_minutes": avg_ride,
        "boardings_per_revenue_hour": boardings_per_revenue_hour,
        "wav_avg_wait_minutes": wav_avg,
        "nonwav_avg_wait_minutes": nonwav_avg,
        "wav_equivalence_ratio": ratio,
        "equivalence_verdict": verdict,
    }

    changed = any(zone.get(field) != computed[field] for field in _METRIC_FIELDS)
    zone.update(computed)
    if changed:
        db.touch(zone)
    return changed


def recompute_zone_by_id(zone_id):
    recompute_zone(db.service_zones.get(zone_id))
