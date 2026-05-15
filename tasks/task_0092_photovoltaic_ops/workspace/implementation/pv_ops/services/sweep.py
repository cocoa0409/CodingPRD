"""Downsampling sweep + arrears watchdog."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from pv_ops.store import Store
from pv_ops.utils import D, fmt_dt, parse_dt, round_half_up


BUCKET_SIZES = {
    "AGG_15MIN": 15,
    "AGG_1H": 60,
    "AGG_1DAY": 1440,
}


def _bucket_start(dt: datetime, bucket_minutes: int) -> datetime:
    epoch_minutes = int(dt.timestamp() // 60)
    base_minutes = (epoch_minutes // bucket_minutes) * bucket_minutes
    return datetime.fromtimestamp(base_minutes * 60, tz=timezone.utc)


def run_sweep(store: Store) -> dict:
    """Idempotent downsampling sweep + arrears watchdog.

    Re-runs are safe: we remove existing AGG_* rows and re-create them.
    """
    # ---- Pass 1: downsample ----
    # Remove existing aggregated rows
    aggregated_ids = [
        rid for rid, r in store.generation_readings.items()
        if r.get("granularity") != "RAW_1MIN"
    ]
    for rid in aggregated_ids:
        del store.generation_readings[rid]

    aggregations = 0
    # Group RAW rows by (station_id, granularity, bucket_start)
    for granularity, bucket_minutes in BUCKET_SIZES.items():
        groups: Dict[tuple, List[dict]] = defaultdict(list)
        for row in store.generation_readings.values():
            if row.get("granularity") != "RAW_1MIN":
                continue
            ts = parse_dt(row["timestamp"], "timestamp")
            bs = _bucket_start(ts, bucket_minutes)
            groups[(row["station_id"], bs)].append(row)
        for (station_id, bucket_start), readings in groups.items():
            if not readings:
                continue
            n = len(readings)
            avg_dc = sum(D(r["dc_power_kw"]) for r in readings) / D(n)
            avg_ac = sum(D(r["ac_power_kw"]) for r in readings) / D(n)
            avg_ir = sum(D(r["irradiance_w_m2"]) for r in readings) / D(n)
            avg_temp = sum(D(r["module_temp_c"]) for r in readings) / D(n)
            agg_row = {
                "station_id": station_id,
                "timestamp": fmt_dt(bucket_start),
                "dc_power_kw": float(round_half_up(avg_dc, 3)),
                "ac_power_kw": float(round_half_up(avg_ac, 3)),
                "irradiance_w_m2": float(round_half_up(avg_ir, 1)),
                "module_temp_c": float(round_half_up(avg_temp, 2)),
                "granularity": granularity,
            }
            store.insert_lite(agg_row)
            store.generation_readings[agg_row["id"]] = agg_row
            aggregations += 1

    # ---- Pass 2: arrears watchdog ----
    now = store.clock.now()
    arrears_transitions = 0
    for decl in store.subsidy_declarations.values():
        if decl.get("state") != "APPROVED":
            continue
        due_raw = decl.get("approval_due_date")
        if due_raw is None:
            continue
        due = parse_dt(due_raw, "approval_due_date")
        if now > due + timedelta(days=30):
            decl["state"] = "ARREARS"
            store.bump(decl)
            arrears_transitions += 1

    return {
        "downsampled_rows": aggregations,
        "arrears_transitions": arrears_transitions,
        "now": store.clock.now_iso(),
    }
