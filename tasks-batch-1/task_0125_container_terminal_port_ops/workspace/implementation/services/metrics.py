"""Dwell-time and reefer aggregation calculations.

dwell_time_hours (SCAFFOLD §1.3): wall-clock hours from the GATE_IN EIR's
recorded_at to the GATE_OUT EIR's recorded_at, or to the clock if still in yard;
round_half_up to 2 decimals; 0.0 if no GATE_IN exists.

reefer_excursion_flag / reefer_excursion_summary (SCAFFOLD §1.3): strict-band
excursion test and the count/max-deviation aggregate.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Tuple

import db
from db import EXCURSION_BAND_C
from services.common import clock_dt, parse_dt


def _round_half_up(value: float, places: int) -> float:
    q = Decimal(1).scaleb(-places)  # e.g. places=2 -> Decimal("0.01")
    return float(Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP))


def dwell_hours(container_id: str) -> float:
    gate_in = None
    gate_out = None
    for e in db.eirs.values():
        if e["container_id"] != container_id:
            continue
        if e["direction"] == "GATE_IN":
            gate_in = e
        elif e["direction"] == "GATE_OUT":
            gate_out = e
    if gate_in is None:
        return 0.0
    start = parse_dt(gate_in["recorded_at"])
    if gate_out is not None:
        end = parse_dt(gate_out["recorded_at"])
    else:
        end = clock_dt()
    seconds = (end - start).total_seconds()
    hours = seconds / 3600.0
    return _round_half_up(hours, 2)


def excursion_flag(temperature_c: float, setpoint_c: float) -> bool:
    deviation = abs(float(temperature_c) - float(setpoint_c))
    # strictly greater than the band; equal to band is NOT an excursion.
    return deviation > EXCURSION_BAND_C


def reefer_summary(container: Dict[str, Any]) -> Tuple[int, float]:
    cid = container["id"]
    setpoint = container.get("setpoint_c")
    readings = [r for r in db.reefer_readings.values() if r["container_id"] == cid]
    excursion_count = sum(1 for r in readings if r["is_excursion"])
    if not readings or setpoint is None:
        return excursion_count, 0.0
    max_dev = max(abs(float(r["temperature_c"]) - float(setpoint)) for r in readings)
    return excursion_count, _round_half_up(max_dev, 1)
