"""Plant, bit-pool, posture, QC-scoring and encoder-pool calculations."""
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from fractions import Fraction

import store
import timeutil
from constants import (ACTIVE_OVERRIDE_STATES, CRITICAL_DEFECTS, DEFECT_POINTS,
                       DURATION_PENALTY_CAP, DURATION_TOLERANCE_SECONDS,
                       FAULT_PENALTY_CAP, FAULT_POINTS, LOUDNESS_PENALTY_POINTS,
                       LOUDNESS_TOLERANCE_LKFS, MAJOR_FAULT_DEGRADE_THRESHOLD,
                       OPEN_FAULT_STATES, PASS_MIN, PASS_WITH_EXCEPTION_MIN,
                       REDUCED_DERATE_THRESHOLD_PCT, TARGET_LKFS)
from errors import fail


# --- derate and capacity ---------------------------------------------------

def derate_for(tx):
    state = tx["operational_state"]
    if state == "OFF_AIR":
        return 0.0
    if state == "REDUCED_POWER":
        if tx["current_power_pct"] >= REDUCED_DERATE_THRESHOLD_PCT:
            return 0.75
        return 0.5
    return 1.0


def effective_capacity(mux):
    tx = store.transmitters.get(mux["transmitter_id"])
    derate = Decimal(str(tx["derate_factor"] if tx else 1.0))
    product = (Decimal(mux["total_capacity_kbps"]) * derate).to_integral_value(rounding=ROUND_FLOOR)
    return max(0, int(product) - int(mux["pilot_reserved_kbps"]))


def _set(rec, field, value, touched):
    if rec.get(field) != value:
        rec[field] = value
        touched.add(rec["id"])


def run_waterfall(mux, clear_pins=False, exempt_channel_id=None):
    """The five-step bitrate waterfall (PRD 3.2). Returns the set of changed channel ids.

    ``exempt_channel_id`` names a channel being created by the very call that runs
    this waterfall: its allocation is part of its own admission rather than a later
    mutation, so its version stays at 1 (PRD 2.5).
    """
    touched = set()
    capacity = effective_capacity(mux)
    candidates = [c for c in store.channels_of(mux["id"])
                  if c["allocation_state"] in ("ACTIVE", "STANDBY", "STARVED")]
    candidates.sort(key=lambda c: (c["priority_rank"], c["created_at"], c["_seq"]))
    if clear_pins:
        for c in candidates:
            if c.get("_pin_allocated_kbps") is not None:
                c["_pin_allocated_kbps"] = None
                touched.add(c["id"])

    running = 0
    granted = []
    for c in candidates:
        floor = int(c["floor_bitrate_kbps"])
        if running + floor <= capacity:
            granted.append(c)
            running += floor
            _set(c, "allocation_state", "STANDBY" if c["allocation_state"] == "STANDBY" else "ACTIVE", touched)
        else:
            _set(c, "allocation_state", "STARVED", touched)
            _set(c, "allocated_bitrate_kbps", 0, touched)

    remainder = capacity - running
    total_weight = sum(int(c["requested_bitrate_kbps"]) - int(c["floor_bitrate_kbps"]) for c in granted)
    shares = {}
    for c in granted:
        weight = int(c["requested_bitrate_kbps"]) - int(c["floor_bitrate_kbps"])
        if total_weight == 0:
            share = 0
        else:
            share = min((remainder * weight) // total_weight, weight)
        shares[c["id"]] = share
        _set(c, "allocated_bitrate_kbps", int(c["floor_bitrate_kbps"]) + share, touched)

    leftover = remainder - sum(shares.values())
    while leftover > 0:
        under = [c for c in granted
                 if c.get("_pin_allocated_kbps") is None
                 and c["allocated_bitrate_kbps"] < c["requested_bitrate_kbps"]]
        if not under:
            break
        for c in under:
            if leftover <= 0:
                break
            _set(c, "allocated_bitrate_kbps", c["allocated_bitrate_kbps"] + 1, touched)
            leftover -= 1

    for c in granted:
        pin = c.get("_pin_allocated_kbps")
        if pin is not None:
            _set(c, "allocated_bitrate_kbps", int(pin), touched)

    assigned = sum(c["allocated_bitrate_kbps"] for c in candidates
                   if c["allocation_state"] in ("ACTIVE", "STANDBY"))
    mux["effective_capacity_kbps"] = capacity
    mux["assigned_kbps"] = assigned
    mux["available_kbps"] = capacity - assigned
    mux["starved_channel_count"] = len([c for c in candidates if c["allocation_state"] == "STARVED"])
    # Bandwidth invariant (PRD 2.11): exact integer equality, no tolerance.
    assert mux["available_kbps"] + mux["assigned_kbps"] == mux["effective_capacity_kbps"]
    for cid in touched:
        if cid != exempt_channel_id:
            store.bump(store.channels[cid])
    for c in candidates:
        recompute_posture(c)
    return touched


def floor_sum_unsatisfiable(mux, extra_floor=0, exclude_channel_id=None, override_floors=None):
    """True when the floors of the channels that would have to be ACTIVE exceed capacity."""
    capacity = effective_capacity(mux)
    total = extra_floor
    for c in store.channels_of(mux["id"]):
        if exclude_channel_id is not None and c["id"] == exclude_channel_id:
            continue
        if c["allocation_state"] != "ACTIVE":
            continue
        floor = int(c["floor_bitrate_kbps"])
        if override_floors and c["id"] in override_floors:
            floor = int(override_floors[c["id"]])
        total += floor
    return total > capacity


def pinned_total(mux, extra_pin=0, exclude_channel_id=None):
    """The bandwidth the pool would have to hand out once the pin is honoured.

    A pinned channel consumes exactly its pin; every other channel that must be
    ACTIVE still has to keep its own floor, so the total that the effective
    capacity has to cover is the pin plus those floors (PRD 3.2).
    """
    total = extra_pin
    for c in store.channels_of(mux["id"]):
        if exclude_channel_id is not None and c["id"] == exclude_channel_id:
            continue
        pin = c.get("_pin_allocated_kbps")
        if pin is not None:
            total += int(pin)
        elif c["allocation_state"] == "ACTIVE":
            total += int(c["floor_bitrate_kbps"])
    return total


# --- channel posture -------------------------------------------------------

def open_faults(channel_id):
    return [f for f in store.faults_of_channel(channel_id) if f["state"] in OPEN_FAULT_STATES]


def active_overrides(channel_id):
    return [o for o in store.overrides_of(channel_id) if o["state"] in ACTIVE_OVERRIDE_STATES]


def compute_posture(channel):
    tx = store.transmitter_of_channel(channel)
    faults = open_faults(channel["id"])
    if channel["allocation_state"] == "STARVED" or (tx and tx["operational_state"] == "OFF_AIR"):
        return "SUSPENDED", len(faults)
    if active_overrides(channel["id"]):
        return "EMERGENCY", len(faults)
    if any(f["severity"] == "CRITICAL" for f in faults):
        return "DEGRADED_CRITICAL", len(faults)
    majors = len([f for f in faults if f["severity"] == "MAJOR"])
    if majors >= MAJOR_FAULT_DEGRADE_THRESHOLD or (tx and tx["operational_state"] == "REDUCED_POWER"):
        return "DEGRADED", len(faults)
    return "NORMAL", len(faults)


def recompute_posture(channel, bump=True):
    posture, count = compute_posture(channel)
    changed = channel.get("posture") != posture or channel.get("open_fault_count") != count
    channel["posture"] = posture
    channel["open_fault_count"] = count
    if changed and bump:
        store.bump(channel)
    return changed


# --- QC technical scoring --------------------------------------------------

def _ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


def defect_penalty(defect_codes):
    distinct = set(defect_codes or [])
    return sum(DEFECT_POINTS[code] for code in distinct if code in DEFECT_POINTS)


def duration_penalty(measured, expected):
    discrepancy = abs(int(measured) - int(expected))
    if discrepancy <= DURATION_TOLERANCE_SECONDS:
        return 0
    return min(_ceil_div(discrepancy, 2) * 3, DURATION_PENALTY_CAP)


def loudness_penalty(loudness):
    if loudness is None:
        return 0
    if abs(float(loudness) - TARGET_LKFS) > LOUDNESS_TOLERANCE_LKFS + 1e-9:
        return LOUDNESS_PENALTY_POINTS
    return 0


def fault_penalty(asset, basis):
    if basis != "AIR_CHECK":
        return 0
    total = 0
    for fault in store.rows(store.faults):
        if fault["state"] != "RESOLVED":
            continue
        item_id = fault.get("playlist_item_id")
        if not item_id:
            continue
        item = store.items.get(item_id)
        if not item or item.get("asset_id") != asset["id"]:
            continue
        if item["playout_status"] not in ("PLAYED", "TRUNCATED"):
            continue
        total += FAULT_POINTS.get(fault["fault_code"], 0)
    return min(total, FAULT_PENALTY_CAP)


def score_report(asset, basis, defect_codes, measured_duration_seconds, loudness_override=None):
    d_pen = defect_penalty(defect_codes)
    du_pen = duration_penalty(measured_duration_seconds, asset["expected_duration_seconds"])
    loudness = asset.get("audio_loudness_lkfs")
    l_pen = loudness_penalty(loudness)
    f_pen = fault_penalty(asset, basis)
    score = 100 - d_pen - du_pen - l_pen - f_pen
    score = max(0, min(100, score))
    distinct = set(defect_codes or [])
    disqualified = (
        any(code in distinct for code in CRITICAL_DEFECTS)
        or (asset.get("captions_required") and not asset.get("caption_present"))
        or (asset.get("delivered_resolution_class") is not None
            and asset.get("delivered_resolution_class") != asset.get("required_resolution_class"))
    )
    if score < PASS_WITH_EXCEPTION_MIN or disqualified:
        verdict = "FAIL"
    elif score < PASS_MIN:
        verdict = "PASS_WITH_EXCEPTION"
    else:
        verdict = "PASS"
    return {
        "defect_penalty_points": d_pen,
        "duration_penalty_points": du_pen,
        "loudness_penalty_points": l_pen,
        "fault_penalty_points": f_pen,
        "technical_score": score,
        "verdict": verdict,
    }


# --- live encoder concurrency ----------------------------------------------

def encoder_peak(mux, extra_window=None):
    """Peak concurrent live-encoder occupancy across the multiplex (PRD 3.7)."""
    windows = [w for w in store.windows_of_multiplex(mux["id"])
               if w["state"] in ("PLANNED", "JOINED")]
    points = []
    for w in windows:
        points.append((timeutil.sec(w["join_utc"]), 1, int(w["live_encoder_units"])))
        points.append((timeutil.sec(w["breakaway_utc"]), 0, -int(w["live_encoder_units"])))
    if extra_window is not None:
        points.append((timeutil.sec(extra_window["join_utc"]), 1, int(extra_window["live_encoder_units"])))
        points.append((timeutil.sec(extra_window["breakaway_utc"]), 0, -int(extra_window["live_encoder_units"])))
    # releases (kind 0) sort before claims (kind 1) at an identical timestamp
    points.sort(key=lambda p: (p[0], p[1]))
    running = 0
    peak = 0
    for _, _, delta in points:
        running += delta
        if running > peak:
            peak = running
    return peak


def refresh_encoder_peak(mux):
    peak = encoder_peak(mux)
    if mux.get("live_encoder_units_peak") != peak:
        mux["live_encoder_units_peak"] = peak
        store.bump(mux)
    return peak


def round_half_up(value):
    """Half-up rounding to whole units; exact rationals are honoured without float drift."""
    if isinstance(value, Fraction):
        value = Decimal(value.numerator) / Decimal(value.denominator)
    elif isinstance(value, float):
        value = Decimal(str(value))
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))
