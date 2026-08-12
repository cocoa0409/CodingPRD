"""Operations checkpoint, census-leveling report, and logical clock endpoints."""

from datetime import timedelta, datetime, timezone
from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from services.core import (
    touch, round2, round4, active_covering_shift,
    EXPECTED_LOS_DAYS, LOS_ALERT_MULTIPLIER, OBS_CONVERT_THRESHOLD_HOURS,
    SLA_MINUTES, REOPEN_WINDOW_HOURS,
    LEVELING_THRESHOLD, PROJECTION_HORIZON_HOURS,
    MAX_CROSS_COVER_LOAD, NIGHT_CROSS_COVER_MULTIPLIER,
    CONSULT_LOAD_WEIGHT, HANDOFF_LOAD_WEIGHT,
)
from services import serializers
import clock

bp = Blueprint("ops", __name__)


def _body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be an object", 400)
    return data


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles(["GroupAdmin"])
    body = _body()
    to_iso8601 = body.get("to_iso8601")
    dt = clock.parse_iso(to_iso8601)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO8601 datetime", 400)
    clock.set_current(dt)
    return success_object({"current_utc": clock.iso(clock.now())})


@bp.route("/ops/monitor-run", methods=["POST"])
def monitor_run():
    require_roles(["GroupAdmin"])
    now = clock.now()

    obs_converted = []
    escalated = []
    closed_consults = []
    locked_windows = []
    closed_windows = []

    # 1. Observation conversions: OBS_ACTIVE with elapsed >= 48h converts
    threshold = timedelta(hours=float(OBS_CONVERT_THRESHOLD_HOURS))
    for p in store["patients"].values():
        if p["observation_status"] == "OBS_ACTIVE":
            started = p.get("observation_started_at")
            if started is not None and (now - started) >= threshold:
                p["observation_status"] = "OBS_CONVERTED"
                p["stay_type"] = "INPATIENT"
                touch(p)
                obs_converted.append(p["id"])

    # 2. LOS refresh on every ADMITTED patient
    for p in store["patients"].values():
        if p["admission_status"] != "ADMITTED":
            continue
        admitted = p["admitted_at"]
        # los_midnights: count of UTC calendar dates d with date(admitted_at) < d <= date(now)
        d_admit = admitted.date()
        d_now = now.date()
        midnights = (d_now - d_admit).days
        if midnights < 0:
            midnights = 0
        p["los_midnights"] = midnights
        # los_blocks: floor(elapsed / 24h) at second precision
        elapsed = (now - admitted).total_seconds()
        blocks = int(elapsed // 86400) if elapsed >= 0 else 0
        p["los_blocks"] = blocks
        expected = EXPECTED_LOS_DAYS[p["stay_type"]][p["acuity"]]
        p["los_alert_flag"] = Decimal(midnights) > Decimal(expected) * LOS_ALERT_MULTIPLIER
        touch(p)

    # 3. Consult escalations (OPEN and now > sla_deadline) and auto-close
    for c in store["consult_requests"].values():
        if c["status"] == "OPEN" and now > c["sla_deadline"]:
            c["status"] = "ESCALATED"
            c["escalation_count"] += 1
            touch(c)
            escalated.append(c["id"])
        elif c["status"] == "COMPLETED" and c.get("completed_at") is not None:
            if now > c["completed_at"] + timedelta(hours=REOPEN_WINDOW_HOURS):
                c["status"] = "CLOSED"
                touch(c)
                closed_consults.append(c["id"])

    # 4. Coverage window locks and closures
    for w in store["coverage_windows"].values():
        if w["status"] in ("OPEN", "FULL") and now >= w["start_at"]:
            w["status"] = "LOCKED"
            touch(w)
            locked_windows.append(w["id"])
        if w["status"] == "LOCKED" and now >= w["end_at"]:
            w["status"] = "CLOSED"
            touch(w)
            closed_windows.append(w["id"])

    # 5. Cross-cover load recompute on LOCKED windows
    census_g = sum(1 for a in store["assignments"].values() if a["status"] == "ACTIVE")
    consults_g = sum(1 for c in store["consult_requests"].values() if c["status"] in ("OPEN", "ESCALATED"))
    handoffs_g = sum(1 for h in store["handoffs"].values() if h["status"] == "SUBMITTED")
    for w in store["coverage_windows"].values():
        if w["status"] == "LOCKED":
            mult = NIGHT_CROSS_COVER_MULTIPLIER if w["window_type"] == "NIGHT_CROSS_COVER" else Decimal("1.0")
            load = (
                Decimal(census_g) * mult
                + Decimal(consults_g) * CONSULT_LOAD_WEIGHT
                + Decimal(handoffs_g) * HANDOFF_LOAD_WEIGHT
            )
            load = round2(load)
            if load > MAX_CROSS_COVER_LOAD:
                load = MAX_CROSS_COVER_LOAD
            w["current_load"] = load
            touch(w)

    return success_object({
        "evaluated_at": clock.iso(now),
        "obs_converted_patient_ids": obs_converted,
        "escalated_consult_ids": escalated,
        "closed_consult_ids": closed_consults,
        "locked_window_ids": locked_windows,
        "closed_window_ids": closed_windows,
    })


@bp.route("/reports/census-leveling", methods=["GET"])
def census_leveling():
    require_roles(["GroupAdmin", "Hospitalist"])
    now = clock.now()
    horizon_end = now + timedelta(hours=PROJECTION_HORIZON_HOURS)

    # step 1: current census per hospitalist
    census = {}
    for h in store["hospitalists"].values():
        census[h["id"]] = sum(
            1 for a in store["assignments"].values()
            if a["hospitalist_id"] == h["id"] and a["status"] == "ACTIVE"
        )

    # step 2: eligible set
    eligible = [
        h for h in store["hospitalists"].values()
        if h["employment_status"] == "ACTIVE"
        and active_covering_shift(h["id"], now) is not None
    ]
    total_census = sum(census[h["id"]] for h in eligible)
    divisor = max(1, len(eligible))
    group_avg = Decimal(total_census) / Decimal(divisor)

    rows = []
    max_abs_dev = Decimal("0")
    for h in eligible:
        hid = h["id"]
        current = census[hid]
        # step 3: projection
        offered = sum(
            1 for a in store["admissions"].values()
            if a["status"] == "OFFERED" and a["offered_to_hospitalist_id"] == hid
        )
        impending = 0
        for o in store["discharge_orders"].values():
            if o["status"] not in ("PLANNED", "ORDERED"):
                continue
            if o["target_discharge_at"] > horizon_end:
                continue
            # join to ACTIVE assignment of this hospitalist on the same patient
            if any(
                a["patient_id"] == o["patient_id"] and a["hospitalist_id"] == hid and a["status"] == "ACTIVE"
                for a in store["assignments"].values()
            ):
                impending += 1
        projected = current + offered - impending

        denom = max(Decimal("1"), group_avg)
        dev_forward = round4((Decimal(projected) - group_avg) / denom)
        dev_chrono = round4((Decimal(current) - group_avg) / denom)
        if abs(dev_forward) > max_abs_dev:
            max_abs_dev = abs(dev_forward)
        rows.append({
            "hospitalist_id": hid,
            "current_census": current,
            "projected_census": projected,
            "deviation_forward": float(dev_forward),
            "deviation_chronological": float(dev_chrono),
        })

    leveling_needed = max_abs_dev > LEVELING_THRESHOLD

    return success_object({
        "generated_at": clock.iso(now),
        "group_avg_census": float(group_avg),
        "leveling_needed": leveling_needed,
        "rows": rows,
    })
