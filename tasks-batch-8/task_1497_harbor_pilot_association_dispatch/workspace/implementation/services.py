"""Business logic: calculations, selectors, state helpers, serializers.

Implements scaffold section 1.3 calculation rules exactly:
- tariff_base_fee (provisional_average and final_marginal variants)
- invoice_final_composition (per-component round_half_up, then sum)
- fatigue_rolling_duty (7-day inclusive window, 4320-minute ceiling)
- rest_requirement (480-minute inclusive long-duty threshold; 960/600 rest)
- rotation_pilot_selection (position ASC, created_at ASC tie-break)
- pilot_boat_selection (created_at ASC, name ASC tie-break)
- pilot_interval_overlap (CLOSED intervals, no buffer; touching collides)
- boat_interval_overlap (HALF-OPEN + 45-minute end-side turnaround buffer)
- apprentice_readiness (track-dependent variants)
- revenue_distribution (levy keyed on gross before deduction; per-share
  round_half_up then cent-by-cent remainder reconciliation)
- tariff_schedule_resolution (ACTIVE / SCHEDULED / SUPERSEDED vs the clock)
"""
from datetime import timedelta
from decimal import Decimal

from db import DB, fmt_dt, new_id, next_seq, now
from util import dec, minutes_between, round_half_up_cents

MAX_DUTY_MINUTES_7D = 4320
DUTY_WINDOW_DAYS = 7
LONG_DUTY_THRESHOLD_MINUTES = 480
LONG_REST_MINUTES = 960
SHORT_REST_MINUTES = 600
BOAT_TURNAROUND_BUFFER_MINUTES = 45
LEVY_TIER_THRESHOLD_CENTS = 10000000
LEVY_LOW_PCT = Decimal("0.08")
LEVY_HIGH_PCT = Decimal("0.10")

OPEN_ASSIGNMENT_STATES = ("ASSIGNED", "EN_ROUTE", "ABOARD")


# ---------------------------------------------------------------------------
# Tariff schedule resolution (computed status; greatest effective_from <= now
# is ACTIVE, tie-break created_at ASC; effective_from > now is SCHEDULED;
# every remaining row is SUPERSEDED).
# ---------------------------------------------------------------------------

def schedule_status(sched):
    eff = sched["effective_from"]
    if eff > now():
        return "SCHEDULED"
    candidates = [
        s for s in DB["tariff_schedules"].values() if s["effective_from"] <= now()
    ]
    if not candidates:
        return "SUPERSEDED"
    active = min(candidates, key=lambda s: (-s["effective_from"].timestamp(), s["_seq"]))
    return "ACTIVE" if active["id"] == sched["id"] else "SUPERSEDED"


def active_schedule():
    candidates = [
        s for s in DB["tariff_schedules"].values() if s["effective_from"] <= now()
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda s: (-s["effective_from"].timestamp(), s["_seq"]))


# ---------------------------------------------------------------------------
# Tariff engine (two variants over the same pinned schedule; the draft
# surcharge applies identically in both: draft_dm strictly greater than the
# threshold multiplies the base by (1 + pct), rounded half-up once).
# ---------------------------------------------------------------------------

def _apply_surcharge(base_cents, schedule, draft_dm):
    base = Decimal(base_cents)
    if draft_dm > schedule["draft_surcharge_threshold_dm"]:
        base = base * (Decimal(1) + dec(schedule["draft_surcharge_pct"]))
    return round_half_up_cents(base)


def tariff_provisional_average(schedule, gt, draft_dm):
    """Average-rate variant: the single tier containing gt prices the ENTIRE
    tonnage at that tier's rate."""
    rate = None
    for tier in schedule["tiers"]:
        lo = tier["min_gt_exclusive"]
        hi = tier["max_gt_inclusive"]
        if gt > lo and (hi is None or gt <= hi):
            rate = tier["rate_cents_per_gt"]
            break
    if rate is None:
        # gt outside every declared band: fall back to the open-ended top tier
        # (or the last declared tier) so intake never crashes.
        rate = schedule["tiers"][-1]["rate_cents_per_gt"]
    return _apply_surcharge(gt * rate, schedule, draft_dm)


def tariff_final_marginal(schedule, gt, draft_dm):
    """Marginal variant: each tier prices only the tonnage inside its band."""
    total = 0
    for tier in schedule["tiers"]:
        lo = tier["min_gt_exclusive"]
        hi = tier["max_gt_inclusive"]
        upper = gt if hi is None else min(gt, hi)
        chargeable = max(0, upper - lo)
        total += chargeable * tier["rate_cents_per_gt"]
    return _apply_surcharge(total, schedule, draft_dm)


def invoice_composition(order, schedule, detention_minutes, delay_minutes):
    """Final invoice composition. Pinned rounding order: each component is
    rounded to integer cents FIRST, then summed."""
    base = tariff_final_marginal(schedule, order["gt"], order["draft_dm"])
    detention = round_half_up_cents(
        Decimal(max(0, detention_minutes - schedule["detention_free_minutes"]))
        * Decimal(schedule["detention_rate_cents_per_minute"])
    )
    delay = round_half_up_cents(
        Decimal(delay_minutes) * Decimal(schedule["delay_rate_cents_per_minute"])
    )
    return base, detention, delay, base + detention + delay


# ---------------------------------------------------------------------------
# Fatigue: rolling duty and rest.
# ---------------------------------------------------------------------------

def rolling_duty_minutes(pilot_id):
    """Sum of (actual_end - actual_start) minutes over the pilot's COMPLETED
    assignments with actual_end >= now - 7 days (boundary inclusive)."""
    window_start = now() - timedelta(days=DUTY_WINDOW_DAYS)
    total = 0
    for a in DB["assignments"].values():
        if a["pilot_id"] != pilot_id or a["service_status"] != "COMPLETED":
            continue
        if a["actual_end"] is None or a["actual_end"] < window_start:
            continue
        total += minutes_between(a["actual_start"], a["actual_end"])
    return total


def duty_ok(pilot_id, planned_minutes):
    """Eligibility: projected load at most 4320 (equality passes)."""
    return rolling_duty_minutes(pilot_id) + planned_minutes <= MAX_DUTY_MINUTES_7D


def rest_ok(pilot):
    return pilot["rest_until"] is None or pilot["rest_until"] <= now()


# ---------------------------------------------------------------------------
# Interval semantics (PRD 2.10).
# ---------------------------------------------------------------------------

def pilot_interval_conflict(pilot_id, new_start, new_end, exclude_assignment_id=None):
    """CLOSED intervals, no buffer: touching endpoints collide."""
    for a in DB["assignments"].values():
        if a["pilot_id"] != pilot_id or a["service_status"] not in OPEN_ASSIGNMENT_STATES:
            continue
        if exclude_assignment_id and a["id"] == exclude_assignment_id:
            continue
        s1, e1 = a["scheduled_start"], a["scheduled_end"]
        if not (new_end < s1 or new_start > e1):
            return True
    return False


def boat_interval_conflict(boat_id, new_start, new_end, exclude_assignment_id=None):
    """HALF-OPEN intervals WITH a 45-minute end-side turnaround buffer:
    occupation is [s1, e1 + buffer); new_start == e1 + buffer is allowed."""
    buf = timedelta(minutes=BOAT_TURNAROUND_BUFFER_MINUTES)
    for a in DB["assignments"].values():
        if a["boat_id"] != boat_id or a["service_status"] not in OPEN_ASSIGNMENT_STATES:
            continue
        if exclude_assignment_id and a["id"] == exclude_assignment_id:
            continue
        s1, e1 = a["scheduled_start"], a["scheduled_end"]
        if not (new_end + buf <= s1 or new_start >= e1 + buf):
            return True
    return False


# ---------------------------------------------------------------------------
# Selectors.
# ---------------------------------------------------------------------------

def pilot_rotation_entry(pilot_id):
    for r in DB["rotation_entries"].values():
        if r["pilot_id"] == pilot_id:
            return r
    return None


def pilot_has_current_endorsement(pilot_id, gt=None):
    """Currency check (expires_at strictly after the clock); when gt is given
    the endorsement must also cover the tonnage."""
    found = False
    for e in DB["endorsements"].values():
        if e["pilot_id"] != pilot_id:
            continue
        if e["status"] != "CURRENT" or e["expires_at"] <= now():
            continue
        if gt is None or e["tonnage_cap_gt"] >= gt:
            found = True
            break
    return found


def select_pilot(order, new_start, new_end, exclude_assignment_id=None):
    """Rotation selector: ACTIVE, IN_ROTATION, current endorsement covering the
    order's gt, rested, projected duty within the ceiling, no closed-interval
    conflict. Ranked position ASC, tie-break entry created_at ASC."""
    planned = minutes_between(new_start, new_end)
    candidates = []
    for p in DB["pilots"].values():
        if p["status"] != "ACTIVE":
            continue
        entry = pilot_rotation_entry(p["id"])
        if entry is None or entry["status"] != "IN_ROTATION":
            continue
        if not pilot_has_current_endorsement(p["id"], order["gt"]):
            continue
        if not rest_ok(p):
            continue
        if not duty_ok(p["id"], planned):
            continue
        if pilot_interval_conflict(p["id"], new_start, new_end, exclude_assignment_id):
            continue
        candidates.append((entry["position"], entry["created_at"], entry["_seq"], p))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    return candidates[0][3]


def select_boat(new_start, new_end, exclude_assignment_id=None):
    """Boat selector: no half-open+buffer conflict; ranked created_at ASC,
    tie-break name ASC."""
    candidates = []
    for b in DB["pilot_boats"].values():
        if boat_interval_conflict(b["id"], new_start, new_end, exclude_assignment_id):
            continue
        candidates.append((b["created_at"], b["name"], b["_seq"], b))
    if not candidates:
        return None
    candidates.sort(key=lambda t: (t[0], t[1], t[2]))
    return candidates[0][3]


def boat_status(boat):
    """Computed: ON_RUN while any referencing assignment is EN_ROUTE/ABOARD."""
    for a in DB["assignments"].values():
        if a["boat_id"] == boat["id"] and a["service_status"] in ("EN_ROUTE", "ABOARD"):
            return "ON_RUN"
    return "AVAILABLE"


# ---------------------------------------------------------------------------
# Rotation board mutation.
# ---------------------------------------------------------------------------

def board_max_position():
    positions = [r["position"] for r in DB["rotation_entries"].values()]
    return max(positions) if positions else 0


def demote_entry(entry):
    """Dispatch/reassign demotion: record the current slot, move to bottom."""
    from db import touch

    entry["previous_position"] = entry["position"]
    entry["position"] = board_max_position() + 1
    touch(entry)


def restore_entry(entry):
    """Cancel compensation: revert to the recorded pre-dispatch slot."""
    from db import touch

    if entry["previous_position"] is not None:
        entry["position"] = entry["previous_position"]
        entry["previous_position"] = None
        touch(entry)


# ---------------------------------------------------------------------------
# Entity factory helper.
# ---------------------------------------------------------------------------

def base_entity():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


# ---------------------------------------------------------------------------
# Serializers (common fields: id, created_at, updated_at, version; PRD 2.5).
# ---------------------------------------------------------------------------

def pilot_view(p):
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "license_number": p["license_number"],
        "share_units": p["share_units"],
        "status": p["status"],
        "rest_until": fmt_dt(p["rest_until"]),
        "duty_minutes_rolling_7d": rolling_duty_minutes(p["id"]),
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def endorsement_view(e):
    return {
        "id": e["id"],
        "pilot_id": e["pilot_id"],
        "endorsement_class": e["endorsement_class"],
        "tonnage_cap_gt": e["tonnage_cap_gt"],
        "expires_at": fmt_dt(e["expires_at"]),
        "status": e["status"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def rotation_entry_view(r):
    return {
        "id": r["id"],
        "pilot_id": r["pilot_id"],
        "position": r["position"],
        "previous_position": r["previous_position"],
        "status": r["status"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def order_view(o):
    return {
        "id": o["id"],
        "agent_id": o["agent_id"],
        "vessel_name": o["vessel_name"],
        "gt": o["gt"],
        "draft_dm": o["draft_dm"],
        "order_type": o["order_type"],
        "eta": fmt_dt(o["eta"]),
        "tariff_schedule_id": o["tariff_schedule_id"],
        "provisional_fee_cents": o["provisional_fee_cents"],
        "status": o["status"],
        "created_at": fmt_dt(o["created_at"]),
        "updated_at": fmt_dt(o["updated_at"]),
        "version": o["version"],
    }


def boat_view(b):
    return {
        "id": b["id"],
        "name": b["name"],
        "capacity_persons": b["capacity_persons"],
        "status": boat_status(b),
        "created_at": fmt_dt(b["created_at"]),
        "updated_at": fmt_dt(b["updated_at"]),
        "version": b["version"],
    }


def assignment_view(a):
    return {
        "id": a["id"],
        "order_id": a["order_id"],
        "pilot_id": a["pilot_id"],
        "boat_id": a["boat_id"],
        "apprentice_id": a["apprentice_id"],
        "scheduled_start": fmt_dt(a["scheduled_start"]),
        "scheduled_end": fmt_dt(a["scheduled_end"]),
        "actual_start": fmt_dt(a["actual_start"]),
        "actual_end": fmt_dt(a["actual_end"]),
        "detention_minutes": a["detention_minutes"],
        "delay_minutes": a["delay_minutes"],
        "service_status": a["service_status"],
        "billing_status": a["billing_status"],
        "recall_count": a["recall_count"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def invoice_view(i):
    return {
        "id": i["id"],
        "assignment_id": i["assignment_id"],
        "base_fee_cents": i["base_fee_cents"],
        "detention_fee_cents": i["detention_fee_cents"],
        "delay_fee_cents": i["delay_fee_cents"],
        "total_cents": i["total_cents"],
        "status": i["status"],
        "finalized_at": fmt_dt(i["finalized_at"]),
        "created_at": fmt_dt(i["created_at"]),
        "updated_at": fmt_dt(i["updated_at"]),
        "version": i["version"],
    }


def incident_view(i):
    return {
        "id": i["id"],
        "assignment_id": i["assignment_id"],
        "pilot_id": i["pilot_id"],
        "incident_type": i["incident_type"],
        "description": i["description"],
        "corrective_note": i["corrective_note"],
        "status": i["status"],
        "created_at": fmt_dt(i["created_at"]),
        "updated_at": fmt_dt(i["updated_at"]),
        "version": i["version"],
    }


def apprentice_view(a):
    return {
        "id": a["id"],
        "full_name": a["full_name"],
        "track": a["track"],
        "trips_completed": a["trips_completed"],
        "evaluations_count": a["evaluations_count"],
        "evaluation_avg": float(a["evaluation_avg"]),
        "status": a["status"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def tariff_view(t):
    return {
        "id": t["id"],
        "effective_from": fmt_dt(t["effective_from"]),
        "tiers": t["tiers"],
        "draft_surcharge_threshold_dm": t["draft_surcharge_threshold_dm"],
        "draft_surcharge_pct": t["draft_surcharge_pct"],
        "detention_free_minutes": t["detention_free_minutes"],
        "detention_rate_cents_per_minute": t["detention_rate_cents_per_minute"],
        "delay_rate_cents_per_minute": t["delay_rate_cents_per_minute"],
        "status": schedule_status(t),
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def run_view(r):
    return {
        "id": r["id"],
        "period_start": fmt_dt(r["period_start"]),
        "period_end": fmt_dt(r["period_end"]),
        "gross_pool_cents": r["gross_pool_cents"],
        "levy_cents": r["levy_cents"],
        "net_pool_cents": r["net_pool_cents"],
        "shares": r["shares"],
        "invoice_ids": r["invoice_ids"],
        "status": r["status"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }
