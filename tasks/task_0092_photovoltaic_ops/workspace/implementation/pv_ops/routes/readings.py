"""Generation reading ingestion + performance endpoint."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, current_app, request

from pv_ops.auth import require_roles
from pv_ops.errors import APIError, ERR_NOT_FOUND, ERR_VALIDATION
from pv_ops.responses import created, success
from pv_ops.services import serializers
from decimal import ROUND_HALF_UP

from pv_ops.utils import (
    D,
    fmt_dt,
    get_body,
    parse_dt,
    require_number,
)


bp = Blueprint("readings", __name__)


@bp.route("/pv-ops/stations/<station_id>/readings", methods=["POST"])
@require_roles("PlatformAdmin")
def ingest_reading(station_id: str):
    body = get_body()
    ts = parse_dt(body.get("timestamp"), "timestamp")
    dc = require_number(body, "dc_power_kw", ge=0.0)
    ac = require_number(body, "ac_power_kw", ge=0.0)
    irr = require_number(body, "irradiance_w_m2", ge=0.0)
    temp = require_number(body, "module_temp_c")
    store = current_app.extensions["store"]
    with store.lock:
        if station_id not in store.stations:
            raise APIError(ERR_NOT_FOUND, 404, "Station not found")
        row = {
            "station_id": station_id,
            "timestamp": fmt_dt(ts),
            "dc_power_kw": float(dc),
            "ac_power_kw": float(ac),
            "irradiance_w_m2": float(irr),
            "module_temp_c": float(temp),
            "granularity": "RAW_1MIN",
        }
        store.insert_lite(row)
        store.generation_readings[row["id"]] = row
        return created(serializers.reading_view(row))


@bp.route("/pv-ops/stations/<station_id>/performance", methods=["GET"])
@require_roles("PlatformAdmin", "O&MEngineer", "FinanceOfficer")
def performance(station_id: str):
    window_start_raw = request.args.get("window_start")
    window_end_raw = request.args.get("window_end")
    if not window_start_raw or not window_end_raw:
        raise APIError(ERR_VALIDATION, 422, "window_start and window_end are required")
    window_start = parse_dt(window_start_raw, "window_start")
    window_end = parse_dt(window_end_raw, "window_end")
    if window_end <= window_start:
        raise APIError(ERR_VALIDATION, 422, "window_end must be after window_start")

    store = current_app.extensions["store"]
    with store.lock:
        station = store.stations.get(station_id)
        if not station:
            raise APIError(ERR_NOT_FOUND, 404, "Station not found")

        # Collect RAW_1MIN readings in [window_start, window_end)
        raw = []
        for r in store.generation_readings.values():
            if r.get("station_id") != station_id:
                continue
            if r.get("granularity") != "RAW_1MIN":
                continue
            ts = parse_dt(r["timestamp"], "timestamp")
            if window_start <= ts < window_end:
                raw.append((ts, r))
        raw.sort(key=lambda x: x[0])

        # --- expected ---
        ref_irr = D(1000)
        installed = D(station["installed_capacity_kw"])
        slice_hours = D(1) / D(60)
        expected = D(0)
        for _, r in raw:
            expected += (D(r["irradiance_w_m2"]) / ref_irr) * installed * slice_hours
        expected = expected.quantize(D("0.001"), rounding=ROUND_HALF_UP)
        # --- actual ---
        # Collect alarms for inverters under station
        inverter_ids = {
            inv["id"] for inv in store.inverters.values() if inv.get("station_id") == station_id
        }
        excluding_alarms = []
        for alarm in store.alarm_events.values():
            if alarm.get("inverter_id") not in inverter_ids:
                continue
            if alarm.get("severity") not in ("MAJOR", "CRITICAL"):
                continue
            if alarm.get("state") not in ("OPEN", "ACKNOWLEDGED"):
                continue
            fs = parse_dt(alarm["first_seen_at"], "first_seen_at")
            ls = parse_dt(alarm["last_seen_at"], "last_seen_at")
            excluding_alarms.append((fs, ls))

        actual = D(0)
        for ts, r in raw:
            excluded = False
            for fs, ls in excluding_alarms:
                if fs <= ts <= ls:
                    excluded = True
                    break
            if excluded:
                continue
            actual += D(r["ac_power_kw"]) * slice_hours
        actual = actual.quantize(D("0.001"), rounding=ROUND_HALF_UP)

        # --- PR ---
        if expected > 0:
            pr = (actual / expected).quantize(D("0.0001"), rounding=ROUND_HALF_UP)
        else:
            pr = D(0).quantize(D("0.0001"), rounding=ROUND_HALF_UP)

        # --- capacity factor ---
        # hours_between(window_start, window_end)
        seconds = (window_end - window_start).total_seconds()
        hours = D(str(seconds)) / D(3600)
        ac_cap = D(station["ac_capacity_kw"])
        denom = ac_cap * hours
        if denom > 0:
            cf = (actual / denom).quantize(D("0.0001"), rounding=ROUND_HALF_UP)
        else:
            cf = D(0).quantize(D("0.0001"), rounding=ROUND_HALF_UP)

        return success(
            {
                "station_id": station_id,
                "window_start": fmt_dt(window_start),
                "window_end": fmt_dt(window_end),
                "expected_generation_kwh": float(expected),
                "actual_generation_kwh": float(actual),
                "performance_ratio": float(pr),
                "capacity_factor": float(cf),
            }
        )


