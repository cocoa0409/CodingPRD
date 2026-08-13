"""Business logic: calculations, cascades, and shared helpers.

Every rule here is pinned by PRD section 3 / SCAFFOLD calculations table:
per-day rounding for rental allocation, per-line rounding for damage
chargebacks, final-only rounding for residual value, round-half-up
everywhere, utilization clamped to 10000 bp.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

from db import (UTC, fmt_ts, new_common, new_sub, next_seq, new_id, now, store,
                touch)

WEAR_RATE_CENTS_PER_HOUR = 900
FIXED_OWNERSHIP_CENTS_PER_DAY = 4200
EXTERNAL_RENTAL_ADMIN_CENTS_PER_DAY = 1500
EXPECTED_HOURS_PER_DAY = 8
ABUSE_MULTIPLIER_BP = 15000
CHARGE_CAP_CENTS = 5000000
TURNAROUND_HOURS = 4
IDLE_WINDOW_DAYS = 5

NON_TERMINAL_ASSIGNMENT = ("RESERVED", "ACTIVE", "SUSPENDED")
OPEN_WORK_ORDER = ("OPEN", "DISPATCHED", "IN_PROGRESS")
OPEN_TRANSPORT = ("PLANNED", "EN_ROUTE")
OPEN_DAMAGE = ("FILED", "ASSESSED", "DISPUTED")


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def hours_since_service(e):
    return e["engine_hours_milli"] - e["hours_at_last_service_milli"]


def service_threshold_milli(cls):
    return cls["service_interval_hours"] * 1000


def update_idle_marker(e):
    """Tracks when the unit last entered the combined (IDLE, SERVICE_OK)
    state; None whenever it is not in that state."""
    if e["availability_status"] == "IDLE" and e["maintenance_status"] == "SERVICE_OK":
        if e.get("_idle_ok_since") is None:
            e["_idle_ok_since"] = now()
    else:
        e["_idle_ok_since"] = None


def mechanic_recompute(m):
    if m["active_work_order_count"] >= 2:
        new = "ON_JOB"
    elif m["status"] == "ON_JOB":
        new = "AVAILABLE"
    else:
        new = m["status"]
    if new != m["status"]:
        m["status"] = new


def recompute_active_count(project):
    cnt = sum(1 for a in store.assignments.values()
              if a["project_id"] == project["id"] and a["status"] == "ACTIVE")
    if cnt != project["active_assignment_count"]:
        project["active_assignment_count"] = cnt
        return True
    return False


def make_work_order(equip, kind, notes="", auto=False):
    wo = new_common()
    wo.update({
        "equipment_id": equip["id"],
        "kind": kind,
        "status": "OPEN",
        "trigger_hours_milli": equip["engine_hours_milli"],
        "mechanic_id": None,
        "dispatched_at": None,
        "completed_at": None,
        "notes": notes,
        "_auto": auto,
    })
    store.work_orders[wo["id"]] = wo
    return wo


# ---------------------------------------------------------------------------
# service threshold (telematics ingest / void)
# ---------------------------------------------------------------------------

def eval_threshold_after_accept(e):
    """Returns True if equipment state changed (maintenance flip)."""
    cls = store.classes[e["class_id"]]
    if (hours_since_service(e) >= service_threshold_milli(cls)
            and e["maintenance_status"] == "SERVICE_OK"):
        e["maintenance_status"] = "SERVICE_DUE"
        exists = any(w for w in store.work_orders.values()
                     if w["equipment_id"] == e["id"] and w["kind"] == "PREVENTIVE"
                     and w["status"] in OPEN_WORK_ORDER)
        if not exists:
            make_work_order(e, "PREVENTIVE", auto=True)
        update_idle_marker(e)
        return True
    return False


def eval_threshold_after_void(e):
    """Un-crossing: returns True if equipment state changed."""
    cls = store.classes[e["class_id"]]
    if (hours_since_service(e) < service_threshold_milli(cls)
            and e["maintenance_status"] == "SERVICE_DUE"):
        auto_open = [w for w in store.work_orders.values()
                     if w["equipment_id"] == e["id"] and w["kind"] == "PREVENTIVE"
                     and w["status"] == "OPEN" and w.get("_auto")]
        if auto_open:
            e["maintenance_status"] = "SERVICE_OK"
            for w in auto_open:
                w["status"] = "CANCELLED"
                touch(w)
            update_idle_marker(e)
            return True
    return False


# ---------------------------------------------------------------------------
# assignment close: rental_allocation + own_vs_rent + utilization_rate
# ---------------------------------------------------------------------------

def _active_intervals(a, close_dt):
    """Intervals during which the assignment was ACTIVE."""
    intervals = []
    cur = a.get("_activated_dt")
    for s in a["_suspensions"]:
        if cur is not None:
            intervals.append((cur, s["start"]))
            cur = None
        if s["end"] is not None:
            cur = s["end"]
    if cur is not None:
        intervals.append((cur, close_dt))
    return intervals


def compute_close(a, e, cls, close_dt):
    close_date = close_dt.date()
    start = date.fromisoformat(a["start_date"])
    end = date.fromisoformat(a["end_date"])
    window_end = min(end, close_date)
    intervals = _active_intervals(a, close_dt)

    accepted = {}
    for r in store.readings.values():
        if r["equipment_id"] == e["id"] and r["status"] == "ACCEPTED":
            accepted[r["recorded_date"]] = r

    billable = 0
    idle = 0
    milli = 0
    allocated = 0
    d = start
    guard = 0
    while d < window_end and guard < 40000:
        guard += 1
        ds = datetime(d.year, d.month, d.day, tzinfo=UTC)
        de = ds + timedelta(days=1)
        if any(iv[0] < de and ds < iv[1] for iv in intervals):
            billable += 1
            r = accepted.get(d.isoformat())
            base = cls["daily_rate_cents"]
            if d.weekday() >= 5:  # Saturday / Sunday, service-local calendar
                base = int((Decimal(base) * cls["weekend_multiplier_bp"] / 10000)
                           .quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
            if r is not None:
                milli += r["engine_hours_delta_milli"]
                if r["engine_hours_delta_milli"] == 0:
                    idle += 1
                    base = int((Decimal(base) * cls["idle_day_multiplier_bp"] / 10000)
                               .quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
            allocated += base
        d += timedelta(days=1)

    own = (allocated
           + int((Decimal(milli) * WEAR_RATE_CENTS_PER_HOUR / 1000)
                 .quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
           + billable * FIXED_OWNERSHIP_CENTS_PER_DAY)
    rent = billable * (cls["external_daily_rate_cents"] + EXTERNAL_RENTAL_ADMIN_CENTS_PER_DAY)
    cheaper = "OWN" if own < rent else ("RENT" if rent < own else "TIE")

    elapsed_days = (close_date - start).days
    if elapsed_days <= 0:
        util_elapsed = 0
    else:
        util_elapsed = int((Decimal(milli) * 10000 / (elapsed_days * EXPECTED_HOURS_PER_DAY * 1000))
                           .quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
        util_elapsed = min(util_elapsed, 10000)
    if billable == 0:
        util_billing = 0
    else:
        util_billing = int((Decimal(milli) * 10000 / (billable * EXPECTED_HOURS_PER_DAY * 1000))
                           .quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
        util_billing = min(util_billing, 10000)

    return {"billable_days": billable, "idle_days": idle, "milli": milli,
            "allocated": allocated, "own": own, "rent": rent, "cheaper": cheaper,
            "util_elapsed": util_elapsed, "util_billing": util_billing}


# ---------------------------------------------------------------------------
# damage chargeback (per-line rounding, then sum, then cap)
# ---------------------------------------------------------------------------

def damage_charge(line_items, abuse_flag):
    mult = ABUSE_MULTIPLIER_BP if abuse_flag else 10000
    subtotal = 0
    for it in line_items:
        subtotal += int((Decimal(it["amount_cents"]) * mult / 10000)
                        .quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
    return min(subtotal, CHARGE_CAP_CENTS)


# ---------------------------------------------------------------------------
# residual value (dispose)
# ---------------------------------------------------------------------------

def whole_months(d1, d2):
    months = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if d2.day < d1.day:
        months -= 1
    return max(0, months)


def residual_value(e, cls, disposal_method, disposed_dt):
    cost = e["acquisition_cost_cents"]
    salvage = cls["salvage_value_cents"]
    base = Decimal(cost - salvage)
    if disposal_method == "SALE":
        acq = date.fromisoformat(e["acquisition_date"])
        age = whole_months(acq, disposed_dt.date())
        life = e["useful_life_months"]
        depreciation = base * min(age, life) / life
    else:  # SCRAP -> HOUR_BASED
        hours_used = Decimal(e["engine_hours_milli"]) / 1000
        life_hours = cls["expected_life_hours"]
        depreciation = base * min(hours_used, Decimal(life_hours)) / life_hours
    residual = cost - int(depreciation.quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
    return max(residual, salvage)


# ---------------------------------------------------------------------------
# redeployment score (computed read)
# ---------------------------------------------------------------------------

def redeployment_score(e, cls):
    candidates = []
    for p in store.projects.values():
        if p["status"] != "OPEN":
            continue
        if p["billed_total_cents"] + cls["daily_rate_cents"] > p["equipment_budget_cents"]:
            continue
        best = None
        for a in store.assignments.values():
            if (a["equipment_id"] == e["id"] and a["project_id"] == p["id"]
                    and a["status"] == "CLOSED"):
                if best is None or (a.get("_closed_dt") or datetime.min.replace(tzinfo=UTC),
                                    a["_seq"]) > (best.get("_closed_dt") or datetime.min.replace(tzinfo=UTC),
                                                  best["_seq"]):
                    best = a
        score = (best["utilization_billing_bp"] or 0) if best is not None else 0
        has_class_on_rent = any(
            a["project_id"] == p["id"] and a["status"] == "ACTIVE"
            and store.equipment[a["equipment_id"]]["class_id"] == cls["id"]
            for a in store.assignments.values())
        if not has_class_on_rent:
            score += 1000
        if p["equipment_budget_cents"] - p["billed_total_cents"] >= 30 * cls["daily_rate_cents"]:
            score += 100
        candidates.append({"project_id": p["id"], "project_code": p["project_code"],
                           "score_bp": score, "_created": p["created_at"]})
    candidates.sort(key=lambda c: (-c["score_bp"], c["_created"], c["project_code"]))
    for c in candidates:
        del c["_created"]
    recommended = candidates[0]["project_id"] if candidates else None
    return candidates, recommended


def idle_streak_days(e):
    if (e["availability_status"] == "IDLE" and e["maintenance_status"] == "SERVICE_OK"
            and e.get("_idle_ok_since") is not None):
        days = (now().date() - e["_idle_ok_since"].date()).days
        return max(0, days)
    return 0


# ---------------------------------------------------------------------------
# fuel burn (computed read)
# ---------------------------------------------------------------------------

def fuel_summary(equipment_id, from_date, to_date):
    total_fuel = 0
    total_hours = 0
    for r in store.readings.values():
        if (r["equipment_id"] == equipment_id and r["status"] == "ACCEPTED"
                and from_date <= r["recorded_date"] <= to_date):
            total_fuel += r["fuel_used_milliliters"]
            total_hours += r["engine_hours_delta_milli"]
    if total_hours == 0:
        burn = None
    else:
        burn = int((Decimal(total_fuel) * 1000 / total_hours)
                   .quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
    return {"total_fuel_ml": total_fuel, "total_hours_milli": total_hours,
            "burn_ml_per_hour": burn}


# ---------------------------------------------------------------------------
# transport buffered-interval conflict
# ---------------------------------------------------------------------------

def lowboy_conflict(lowboy_id, depart_dt, arrive_dt):
    buffer = timedelta(hours=TURNAROUND_HOURS)
    for t in store.transport_jobs.values():
        if t["lowboy_id"] != lowboy_id or t["status"] not in OPEN_TRANSPORT:
            continue
        o_dep = t["_depart_dt"]
        o_buf_end = t["_arrive_dt"] + buffer
        if depart_dt < o_buf_end and o_dep < arrive_dt + buffer:
            return True
    return False
