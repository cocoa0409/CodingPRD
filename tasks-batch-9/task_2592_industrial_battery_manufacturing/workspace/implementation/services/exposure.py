"""Worker exposure index variants (PRD 3.2, calculation 2)."""
import datetime
from decimal import Decimal

from helpers import samples_of_worker
from util import q
from services.constants import (
    AIR_WINDOW_DAYS,
    BLL_LIMIT_UG_PER_DL,
    BLOOD_WINDOW_DAYS,
    PEL_AIR_UG_PER_M3,
)

ZERO_INDEX = Decimal("0.00")


def air_twa_index(worker_id, now):
    """90-day air time-weighted-average variant; inclusive lower bound."""
    floor_at = now - datetime.timedelta(days=AIR_WINDOW_DAYS)
    weighted = Decimal("0")
    minutes = Decimal("0")
    count = 0
    for sample in samples_of_worker(worker_id):
        if sample.get("sample_type") != "AIR":
            continue
        taken = sample.get("sampled_at")
        if taken is None or taken < floor_at or taken > now:
            continue
        duration = Decimal(sample["sample_duration_minutes"])
        weighted += sample["air_lead_ug_per_m3"] * duration
        minutes += duration
        count += 1
    if count == 0 or minutes == 0:
        return ZERO_INDEX, count
    twa = q(weighted / minutes, 3)
    return q(twa / PEL_AIR_UG_PER_M3 * Decimal("100"), 2), count


def blood_peak_index(worker_id, now):
    """180-day blood peak variant; inclusive lower bound."""
    floor_at = now - datetime.timedelta(days=BLOOD_WINDOW_DAYS)
    peak = None
    count = 0
    for sample in samples_of_worker(worker_id):
        if sample.get("sample_type") != "BLOOD":
            continue
        taken = sample.get("sampled_at")
        if taken is None or taken < floor_at or taken > now:
            continue
        reading = sample["blood_lead_ug_per_dl"]
        peak = reading if peak is None or reading > peak else peak
        count += 1
    if peak is None:
        return ZERO_INDEX, count
    return q(peak / BLL_LIMIT_UG_PER_DL * Decimal("100"), 2), count
