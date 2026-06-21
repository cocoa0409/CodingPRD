"""Core domain logic: calculations, time parsing, day-phase derivation,
counter recomputation, and shared validation gates.

Every behavior traces to a verbatim PRD sentence (§2.5-2.9, §3).
"""
import math
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
import errors

# --- Constants (SCAFFOLD §1.3) ---
VQ_SUPPLY_FRACTION = 0.40       # return_window_slot_capacity
RIDE_PEAK_LOAD = 0.75           # lightning_lane_price phase derivation
SINGLE_PASS_CAP_CENTS = 9900    # lightning_lane_price tier cap
STANDBY_BASELINE = 20           # posted_wait_estimate
VQ_MAX_PER_GUEST = 2            # max_concurrent_hold_check (VQ ceiling)


# ---------------------------------------------------------------------------
# Time handling — the logical clock (PRD §2.5)
# ---------------------------------------------------------------------------
def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Malformed -> ERR_VALIDATION (PRD §2.10).
    """
    if not isinstance(value, str) or not value:
        errors.err(errors.ERR_VALIDATION, f"Field {field} must be an ISO 8601 datetime")
    raw = value
    try:
        s = raw
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        errors.err(errors.ERR_VALIDATION, f"Field {field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def park_now(park):
    """The park's logical clock instant, or None if unset (PRD §2.5)."""
    cur = park.get("current_utc")
    if cur is None:
        return None
    return parse_dt(cur, "current_utc")


# ---------------------------------------------------------------------------
# Calc: return_window_slot_capacity (SCAFFOLD §1.3, PRD §3.1)
# ---------------------------------------------------------------------------
def compute_slot_capacity(hourly_throughput, start_dt, end_dt):
    # window length in whole minutes, truncated toward zero
    total_seconds = (end_dt - start_dt).total_seconds()
    window_minutes = int(total_seconds // 60)
    if window_minutes < 0:
        window_minutes = 0
    raw = hourly_throughput * (window_minutes / 60.0) * VQ_SUPPLY_FRACTION
    return int(math.floor(raw))


# ---------------------------------------------------------------------------
# Calc: posted_wait_estimate (SCAFFOLD §1.3, PRD §3.8)
# ---------------------------------------------------------------------------
def recompute_posted_wait(ride):
    if ride["operational_status"] != "OPEN":
        new_val = 0
    else:
        standby_demand = ride["booked_slot_count"] + STANDBY_BASELINE
        minutes = standby_demand / ride["hourly_throughput"] * 60
        new_val = int(math.ceil(minutes))
        if new_val < 0:
            new_val = 0
    ride["posted_wait_minutes"] = new_val


# ---------------------------------------------------------------------------
# Calc: lightning_lane_price (SCAFFOLD §1.3, PRD §3.6)
# ---------------------------------------------------------------------------
def _ride_load(ride):
    # ride_load = booked_slot_count / max(1, sum slot_capacity of OPEN/EXHAUSTED windows)
    total_cap = 0
    for w in db.return_windows.values():
        if w["ride_id"] == ride["id"] and w["window_status"] in ("OPEN", "EXHAUSTED"):
            total_cap += w["slot_capacity"]
    denom = max(1, total_cap)
    return ride["booked_slot_count"] / denom


def compute_lightning_lane_price(ride, plan):
    load = _ride_load(ride)
    phase = "PEAK" if load >= RIDE_PEAK_LOAD else "OPEN"
    base = plan["price_cents"]
    if phase == "PEAK":
        surged = base * plan["surge_multiplier"]
    else:
        surged = base
    if plan["tier"] == "SINGLE_PASS":
        capped = min(surged, SINGLE_PASS_CAP_CENTS)
        charged = _round_half_up(capped)
    else:
        charged = _round_half_up(surged)
    return charged


def _round_half_up(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Park day_phase derivation (PRD §2.8)
# ---------------------------------------------------------------------------
def recompute_day_phase(park):
    admitted = park["admitted_count"]
    cap = park["gate_capacity"]
    if admitted >= cap:
        park["day_phase"] = "FULL"
    else:
        occ = admitted / cap if cap else 0
        if occ < park["peak_threshold_pct"]:
            park["day_phase"] = "OPEN"
        else:
            park["day_phase"] = "PEAK"


# ---------------------------------------------------------------------------
# Counter recomputation
# ---------------------------------------------------------------------------
def recompute_window_reserved_count(window):
    """reserved_count = HELD or BOOKED VIRTUAL_QUEUE reservations on this window."""
    count = 0
    for r in db.reservations.values():
        if (r["return_window_id"] == window["id"]
                and r["queue_type"] == "VIRTUAL_QUEUE"
                and r["reservation_status"] in ("HELD", "BOOKED")):
            count += 1
    window["reserved_count"] = count


def recompute_ride_booked_slot_count(ride):
    """booked_slot_count = HELD or BOOKED VIRTUAL_QUEUE reservations on this ride."""
    count = 0
    for r in db.reservations.values():
        if (r["ride_id"] == ride["id"]
                and r["queue_type"] == "VIRTUAL_QUEUE"
                and r["reservation_status"] in ("HELD", "BOOKED")):
            count += 1
    ride["booked_slot_count"] = count


def maybe_exhaust_window(window):
    """OPEN -> EXHAUSTED when reserved_count >= slot_capacity (PRD §3.3)."""
    if window["window_status"] == "OPEN" and window["reserved_count"] >= window["slot_capacity"]:
        window["window_status"] = "EXHAUSTED"
        db.touch(window)


def maybe_unexhaust_window(window, park):
    """EXHAUSTED -> OPEN when a slot frees while window not yet expired (PRD §3.4)."""
    if window["window_status"] != "EXHAUSTED":
        return
    if window["reserved_count"] >= window["slot_capacity"]:
        return
    now = park_now(park)
    end = parse_dt(window["window_end_utc"], "window_end_utc")
    if now is not None and now >= end:
        return
    window["window_status"] = "OPEN"
    db.touch(window)


# ---------------------------------------------------------------------------
# Per-guest aggregation gates (calc max_concurrent_hold_check)
# ---------------------------------------------------------------------------
def active_vq_reservation_count(guest_id):
    return sum(
        1 for r in db.reservations.values()
        if r["guest_id"] == guest_id
        and r["queue_type"] == "VIRTUAL_QUEUE"
        and r["reservation_status"] in ("HELD", "BOOKED")
    )


def active_ll_hold_count(guest_id):
    return sum(
        1 for p in db.lightning_lane_purchases.values()
        if p["guest_id"] == guest_id and p["hold_status"] == "ACTIVE"
    )


def guest_has_active_multipass(park_id, guest_id):
    """True if guest holds an ACTIVE MULTI_PASS LightningLanePurchase in this park.

    The plan's tier (MULTI_PASS) is what satisfies the peak gate (PRD §3.3/§3.6).
    """
    for p in db.lightning_lane_purchases.values():
        if (p["park_id"] == park_id
                and p["guest_id"] == guest_id
                and p["hold_status"] == "ACTIVE"):
            plan = db.entitlement_plans.get(p["plan_id"])
            if plan and plan["tier"] == "MULTI_PASS":
                return True
    return False
