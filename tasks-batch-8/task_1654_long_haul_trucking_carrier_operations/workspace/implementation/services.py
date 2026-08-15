"""Business logic: calculations, state-machine cascades. All money integer cents;
all division carried as exact rational (Fraction) until a rule's rounding step."""
from datetime import timedelta
from fractions import Fraction

from common import ApiError
from store import store, now, touch, init_common, init_telemetry

# ---- calculation constants (scaffold section 1.3) ----
DEADHEAD_ESTIMATE_MILES = 100
VARIABLE_COST_CPM = 145
FLEET_AVG_PAY_CPM = 62
FSC_BASELINE_CENTS = 300
DRIVE_LIMIT_MIN = 660
WINDOW_LIMIT_MIN = 840
CYCLE_LIMIT_MIN = 4200
CYCLE_WINDOW_MIN = 10080
LONG_OFF_MIN = 600
RESTART_MIN = 2040
BREAK_MIN = 30
BREAK_DRIVE_MIN = 480
AVG_SPEED_MPH = 50
MAX_DAYS_OUT = 14
FREE_MINUTES = 120
DETENTION_INCREMENT_MIN = 15
DETENTION_INCREMENT_CENTS = 1500
SAFETY_ASSIGNMENT_MIN = 60
FULL_WEIGHT_HOURS = 8760
HALF_WEIGHT_HOURS = 17520
INTERSTATE_DEADHEAD_MILES = 250
MIN_WEEKLY_CENTS = 120000
DRIVER_ACCESSORIAL_SHARE_BP = 2500

OFF_TYPES = ("OFF_DUTY", "SLEEPER")

CHECK_CALL_RANK = {"ARRIVED_PICKUP": 1, "DEPARTED_PICKUP": 2,
                   "ARRIVED_DELIVERY": 3, "DELIVERED": 4}


def rhu(fr):
    """Round half up to whole units of a non-negative Fraction."""
    return (2 * fr.numerator + fr.denominator) // (2 * fr.denominator)


def ceil_frac(fr):
    return -(-fr.numerator // fr.denominator)


def minutes_between(a, b):
    """Exact (b - a) in minutes as a Fraction."""
    us = (b - a) // timedelta(microseconds=1)
    return Fraction(us, 60_000_000)


def as_int(fr):
    if isinstance(fr, Fraction):
        return fr.numerator // fr.denominator
    return int(fr)


# ---------------------------------------------------------------------------
# Fuel rates
# ---------------------------------------------------------------------------

def current_fuel_rate(state_code, at=None):
    """The row for state_code whose closed effective window contains `at`."""
    at = at if at is not None else now()
    for r in store.fuel_rates.values():
        if r["state_code"] != state_code:
            continue
        if r["effective_from"] <= at and (r["effective_to"] is None or at <= r["effective_to"]):
            return r
    return None


# ---------------------------------------------------------------------------
# fuel_surcharge_calc
# ---------------------------------------------------------------------------

def compute_fsc(lane):
    nat = current_fuel_rate("US-NATIONAL")
    if nat is None:
        raise ApiError("ERR_FUEL_RATE_UNAVAILABLE", 422,
                       "No currently effective US-NATIONAL StateFuelRate row")
    diff = max(0, nat["avg_pump_price_cents"] - FSC_BASELINE_CENTS)
    # round_half_up(lane.loaded_miles * diff / 6.5) == miles * diff * 2 / 13
    return rhu(Fraction(lane["loaded_miles"] * diff * 2, 13))


# ---------------------------------------------------------------------------
# lane_margin_screen (provisional and final variants)
# ---------------------------------------------------------------------------

def provisional_margin(load, lane, fsc):
    total_miles = lane["loaded_miles"] + DEADHEAD_ESTIMATE_MILES
    revenue = load["rate_cents"] + fsc
    cost = total_miles * (VARIABLE_COST_CPM + FLEET_AVG_PAY_CPM)
    margin = revenue - cost
    rpm = rhu(Fraction(revenue, total_miles))
    return margin, rpm


def final_margin(load, trip, newly_billed_total):
    revenue = (load["rate_cents"] + load["fuel_surcharge_cents"] + newly_billed_total)
    cost = trip["actual_miles"] * VARIABLE_COST_CPM + trip["final_pay_cents"]
    return revenue - cost


# ---------------------------------------------------------------------------
# driver_trip_pay
# ---------------------------------------------------------------------------

def provisional_pay(driver, load, lane, deadhead):
    if driver["pay_model"] == "MILEAGE":
        return (lane["loaded_miles"] + deadhead) * driver["pay_rate_cents_per_mile"]
    return rhu(Fraction(load["rate_cents"] * driver["pay_percentage_bp"], 10000))


def completion_pay(driver, load, lane, actual_miles, deadhead):
    if driver["pay_model"] == "MILEAGE":
        pay_miles = max(actual_miles, lane["loaded_miles"] + deadhead)
        return pay_miles, pay_miles * driver["pay_rate_cents_per_mile"]
    pay_miles = max(actual_miles, lane["loaded_miles"] + deadhead)
    final = rhu(Fraction((load["rate_cents"] + load["fuel_surcharge_cents"])
                         * driver["pay_percentage_bp"], 10000))
    return pay_miles, final


# ---------------------------------------------------------------------------
# driver_safety_score
# ---------------------------------------------------------------------------

def compute_safety_score(driver_id, at=None):
    at = at if at is not None else now()
    total = Fraction(0)
    for ev in store.safety_events.values():
        if ev["driver_id"] != driver_id or ev["voided"]:
            continue
        age_hours = minutes_between(ev["occurred_at"], at) / 60
        if age_hours <= FULL_WEIGHT_HOURS:
            w = Fraction(1)
        elif age_hours <= HALF_WEIGHT_HOURS:
            w = Fraction(1, 2)
        else:
            w = Fraction(0)
        total += ev["severity_points"] * w
    return max(0, 100 - rhu(total))


def recompute_driver_score(driver):
    driver["safety_score"] = compute_safety_score(driver["id"])
    touch(driver)


# ---------------------------------------------------------------------------
# hos_clock_projection
# ---------------------------------------------------------------------------

def driver_duty_events(driver_id):
    evs = [e for e in store.duty_events.values() if e["driver_id"] == driver_id]
    return sorted(evs, key=lambda e: (e["occurred_at"], e["_seq"]))


def hos_projection(driver_id, at=None):
    """Returns (drive_11h_remaining, window_14h_remaining, cycle_70h_remaining,
    break_blocked) as exact Fraction minutes (break flag a bool)."""
    T = at if at is not None else now()
    events = driver_duty_events(driver_id)
    if not events:
        return (Fraction(DRIVE_LIMIT_MIN), Fraction(WINDOW_LIMIT_MIN),
                Fraction(CYCLE_LIMIT_MIN), False)
    # Half-open intervals typed by the earlier event; last ends at T.
    ivs = []
    for i, e in enumerate(events):
        end = events[i + 1]["occurred_at"] if i + 1 < len(events) else T
        ivs.append((e["occurred_at"], end, e["event_type"]))
    # Maximal contiguous OFF_DUTY/SLEEPER runs: (start, end, total_minutes)
    runs = []
    cur = None
    for (s, e, ty) in ivs:
        if ty in OFF_TYPES:
            if cur is None:
                cur = [s, e, Fraction(0)]
            cur[1] = e
            cur[2] += minutes_between(s, e)
        else:
            if cur is not None:
                runs.append(tuple(cur))
                cur = None
    if cur is not None:
        runs.append(tuple(cur))

    last_off = ivs[-1][2] in OFF_TYPES
    ended_runs = runs[:-1] if last_off else runs

    # 11h / 14h clocks
    inside_long_off = last_off and runs and runs[-1][2] >= LONG_OFF_MIN
    if inside_long_off:
        drive_rem = Fraction(DRIVE_LIMIT_MIN)
        window_rem = Fraction(WINDOW_LIMIT_MIN)
    else:
        ended_lo = [r for r in ended_runs if r[2] >= LONG_OFF_MIN]
        anchor = ended_lo[-1][1] if ended_lo else events[0]["occurred_at"]
        driving = sum((minutes_between(s, e) for (s, e, ty) in ivs
                       if ty == "DRIVING" and s >= anchor), Fraction(0))
        drive_rem = Fraction(DRIVE_LIMIT_MIN) - driving
        window_rem = max(Fraction(0), Fraction(WINDOW_LIMIT_MIN)
                         - minutes_between(anchor, T))

    # 70h cycle clock with 34h restart
    restarts = [r for r in runs if r[2] >= RESTART_MIN]
    restart_end = restarts[-1][1] if restarts else None
    window_start = T - timedelta(minutes=CYCLE_WINDOW_MIN)
    cycle_start = max(window_start, restart_end) if restart_end else window_start
    cyc = Fraction(0)
    for (s, e, ty) in ivs:
        if ty in ("DRIVING", "ON_DUTY"):
            lo, hi = max(s, cycle_start), min(e, T)
            if hi > lo:
                cyc += minutes_between(lo, hi)
    cycle_rem = Fraction(CYCLE_LIMIT_MIN) - cyc

    # 30-minute break flag: driving since end of last qualifying (>=30m) off run
    if last_off and runs and runs[-1][2] >= BREAK_MIN:
        drive_since = Fraction(0)
    else:
        ended_q = [r for r in ended_runs if r[2] >= BREAK_MIN]
        banchor = ended_q[-1][1] if ended_q else events[0]["occurred_at"]
        drive_since = sum((minutes_between(s, e) for (s, e, ty) in ivs
                           if ty == "DRIVING" and s >= banchor), Fraction(0))
    break_blocked = drive_since >= BREAK_DRIVE_MIN
    return drive_rem, window_rem, cycle_rem, break_blocked


# ---------------------------------------------------------------------------
# hos_feasibility_check + home time
# ---------------------------------------------------------------------------

def required_drive_minutes(lane, deadhead):
    return ceil_frac(Fraction((lane["loaded_miles"] + deadhead) * 60,
                              AVG_SPEED_MPH))


def hos_feasible(driver_id, lane, deadhead, delivery_appt_at):
    """Returns True iff all four clauses hold at logical now."""
    T = now()
    drive_rem, _window_rem, cycle_rem, _bb = hos_projection(driver_id, T)
    required = required_drive_minutes(lane, deadhead)
    runway = minutes_between(T, delivery_appt_at)
    whole_days = runway // 1440
    if drive_rem < min(required, DRIVE_LIMIT_MIN):
        return False
    if cycle_rem < required:
        return False
    if DRIVE_LIMIT_MIN * (1 + whole_days) < required:
        return False
    if required + 600 * ((required - 1) // DRIVE_LIMIT_MIN) > runway:
        return False
    return True


def home_time_ok(driver, delivery_appt_at):
    days_out = minutes_between(driver["last_home_at"], delivery_appt_at) // 1440
    return days_out <= MAX_DAYS_OUT


# ---------------------------------------------------------------------------
# detention_billing
# ---------------------------------------------------------------------------

def accessorial_amount(charge_type, quantity):
    if charge_type in ("DETENTION_PICKUP", "DETENTION_DELIVERY"):
        return ((quantity + DETENTION_INCREMENT_MIN - 1) // DETENTION_INCREMENT_MIN
                ) * DETENTION_INCREMENT_CENTS
    if charge_type == "LAYOVER":
        return quantity * 30000
    if charge_type == "STOP_OFF":
        return quantity * 10000
    return quantity  # LUMPER receipt passthrough


def auto_create_detention(trip, load):
    """Load IN_TRANSIT -> DELIVERED trigger: per-leg detention materialization."""
    ccs = [c for c in store.check_calls.values() if c["trip_id"] == trip["id"]]
    by_kind = {}
    for c in ccs:
        by_kind[c["kind"]] = c
    legs = [("DETENTION_PICKUP", "ARRIVED_PICKUP", "DEPARTED_PICKUP",
             load["pickup_appt_at"]),
            ("DETENTION_DELIVERY", "ARRIVED_DELIVERY", "DELIVERED",
             load["delivery_appt_at"])]
    for charge_type, arrive_kind, end_kind, appt in legs:
        if arrive_kind not in by_kind or end_kind not in by_kind:
            continue  # missing anchor or leg end -> nothing auto-created
        anchor = max(by_kind[arrive_kind]["occurred_at"], appt)
        elapsed = minutes_between(anchor, by_kind[end_kind]["occurred_at"])
        billable = max(Fraction(0), elapsed - FREE_MINUTES)
        if billable <= 0:
            continue
        qty = as_int(billable)
        ch = init_common({
            "load_id": load["id"],
            "trip_id": trip["id"],
            "type": charge_type,
            "quantity": qty,
            "amount_cents": accessorial_amount(charge_type, qty),
            "source": "AUTO_DETENTION",
            "status": "PENDING",
        })
        store.accessorials[ch["id"]] = ch


# ---------------------------------------------------------------------------
# eta_projection
# ---------------------------------------------------------------------------

def eta_projection(trip, load, lane):
    T = now()
    ccs = sorted((c for c in store.check_calls.values()
                  if c["trip_id"] == trip["id"]),
                 key=lambda c: (c["occurred_at"], c["_seq"]))
    planned_total = lane["loaded_miles"] + trip["planned_deadhead_miles"]
    if not ccs:
        remaining = planned_total
        base = trip["planned_start_at"]
    else:
        last = ccs[-1]
        covered = last["odometer_miles"] - (trip["start_odometer_miles"] or 0)
        remaining = max(0, planned_total - covered)
        base = max(T, last["occurred_at"])
    drive = ceil_frac(Fraction(remaining * 60, AVG_SPEED_MPH))
    brk = 30 * max(0, (drive - 1) // BREAK_DRIVE_MIN)
    rest = 600 * max(0, (drive - 1) // DRIVE_LIMIT_MIN)
    eta_at = base + timedelta(minutes=drive + brk + rest)
    late = eta_at > load["delivery_appt_at"]
    return {"eta_at": eta_at, "late": late, "remaining_miles": remaining,
            "drive_minutes": drive, "break_minutes": brk, "rest_minutes": rest}


# ---------------------------------------------------------------------------
# fuel_purchase_costing / fuel_plan_selection
# ---------------------------------------------------------------------------

def fuel_plan(trip, tractor):
    route = trip["route_states"] or []
    if not route:
        raise ApiError("ERR_FUEL_PLAN_INFEASIBLE", 422,
                       "Trip has an empty route_states list")
    range_miles = (tractor["current_fuel_gallons"] * 13) // 2  # floor(gal * 6.5)
    candidates = []
    cum = 0
    for idx, seg in enumerate(route):
        if cum <= range_miles:
            rate = current_fuel_rate(seg["state_code"])
            if rate is not None:
                candidates.append({
                    "state_code": seg["state_code"],
                    "effective_price_cents": rate["avg_pump_price_cents"]
                                             - rate["tax_cents_per_gallon"],
                    "tax_cents_per_gallon": rate["tax_cents_per_gallon"],
                    "cumulative_miles_to_enter": cum,
                    "route_order": idx,
                })
        cum += seg["miles"]
    if not candidates:
        raise ApiError("ERR_FUEL_PLAN_INFEASIBLE", 422,
                       "No route state within range has a current fuel rate")
    candidates.sort(key=lambda c: (c["effective_price_cents"],
                                   -c["tax_cents_per_gallon"],
                                   c["route_order"]))
    return candidates


# ---------------------------------------------------------------------------
# backhaul_ranking
# ---------------------------------------------------------------------------

def backhaul_candidates(tractor, driver):
    T = now()
    rows = []
    for load in store.loads.values():
        if load["status"] not in ("SCREENED", "ACCEPTED"):
            continue
        lane = store.lanes[load["lane_id"]]
        deadhead_est = (0 if lane["origin_state"] == tractor["current_state_code"]
                        else INTERSTATE_DEADHEAD_MILES)
        rpm = rhu(Fraction(load["rate_cents"] + load["fuel_surcharge_cents"],
                           lane["loaded_miles"] + deadhead_est))
        if driver is not None and not hos_feasible(
                driver["id"], lane, deadhead_est, load["delivery_appt_at"]):
            continue
        rows.append((rpm, load, deadhead_est))
    rows.sort(key=lambda r: (-r[0], r[1]["pickup_appt_at"],
                             r[1]["created_at"], r[1]["_seq"]))
    return [r[1] for r in rows]


# ---------------------------------------------------------------------------
# cancellation_fee_tiers
# ---------------------------------------------------------------------------

def cancellation_fee(load):
    st = load["status"]
    if st in ("TENDERED", "SCREENED"):
        return 0
    if st == "ACCEPTED":
        return 15000
    # ASSIGNED or DISPATCHED (TONU)
    return max(25000, rhu(Fraction(load["rate_cents"] * 10, 100)))


# ---------------------------------------------------------------------------
# settlement_gross_pay
# ---------------------------------------------------------------------------

def compute_settlement_components(st):
    driver = store.drivers[st["driver_id"]]
    trips = [t for t in store.trips.values()
             if t["driver_id"] == st["driver_id"] and t["status"] == "COMPLETED"
             and st["period_start"] <= t["completed_at"] < st["period_end"]]
    trip_pay = sum(t["final_pay_cents"] for t in trips)
    load_ids = {t["load_id"] for t in trips}
    share = sum(
        rhu(Fraction(a["amount_cents"] * DRIVER_ACCESSORIAL_SHARE_BP, 10000))
        for a in store.accessorials.values()
        if a["load_id"] in load_ids and a["status"] == "BILLED")
    subtotal = trip_pay + share + st["manual_adjustment_cents"]
    eligible = driver["employment_status"] != "TERMINATED" and len(trips) >= 1
    top_up = max(0, MIN_WEEKLY_CENTS - subtotal) if eligible else 0
    st["trip_pay_cents"] = trip_pay
    st["accessorial_share_cents"] = share
    st["guarantee_top_up_cents"] = top_up
    st["gross_pay_cents"] = subtotal + top_up


# ---------------------------------------------------------------------------
# Cascades (state-machine side effects)
# ---------------------------------------------------------------------------

def cancel_trip_cascade(trip, reason, roll_back_load=True):
    """Trip -> CANCELLED; optionally roll its load back to ACCEPTED and always
    release the tractor."""
    trip["status"] = "CANCELLED"
    trip["cancel_reason"] = reason
    touch(trip)
    load = store.loads.get(trip["load_id"])
    if roll_back_load and load is not None and load["status"] in ("ASSIGNED", "DISPATCHED"):
        load["status"] = "ACCEPTED"
        load["reassignment_count"] += 1
        touch(load)
    tractor = store.tractors.get(trip["tractor_id"])
    if tractor is not None and tractor["status"] == "ASSIGNED":
        tractor["status"] = "AVAILABLE"
        touch(tractor)


def driver_employment_cascade(driver):
    """Suspend/terminate: every non-terminal trip of the driver -> CANCELLED
    with reason SAFETY, with per-trip load/tractor rollback."""
    for trip in list(store.trips.values()):
        if trip["driver_id"] == driver["id"] and trip["status"] in (
                "PLANNED", "DISPATCHED", "AT_PICKUP"):
            cancel_trip_cascade(trip, "SAFETY", roll_back_load=True)


def complete_trip(trip, check_call):
    """DELIVERED check call: trip completion cascade (Trip/Load/Tractor +
    detention auto-creation)."""
    load = store.loads[trip["load_id"]]
    lane = store.lanes[load["lane_id"]]
    driver = store.drivers[trip["driver_id"]]
    tractor = store.tractors[trip["tractor_id"]]

    trip["status"] = "COMPLETED"
    trip["completed_at"] = check_call["occurred_at"]
    trip["actual_miles"] = check_call["odometer_miles"] - trip["start_odometer_miles"]
    pay_miles, final_pay = completion_pay(driver, load, lane,
                                          trip["actual_miles"],
                                          trip["planned_deadhead_miles"])
    trip["pay_miles"] = pay_miles
    trip["final_pay_cents"] = final_pay
    touch(trip)

    tractor["status"] = "AVAILABLE"
    tractor["odometer_miles"] = check_call["odometer_miles"]
    tractor["current_state_code"] = check_call["state_code"]
    burn = ceil_frac(Fraction(max(0, trip["actual_miles"]) * 2, 13))
    tractor["current_fuel_gallons"] = max(0, tractor["current_fuel_gallons"] - burn)
    touch(tractor)

    load["status"] = "DELIVERED"
    touch(load)
    auto_create_detention(trip, load)


def completed_trip_of_load(load_id):
    """The COMPLETED trip of a load (latest if several)."""
    cands = [t for t in store.trips.values()
             if t["load_id"] == load_id and t["status"] == "COMPLETED"]
    if not cands:
        return None
    cands.sort(key=lambda t: (t["completed_at"], t["_seq"]))
    return cands[-1]


def recompute_load_accessorial_total(load):
    load["total_accessorial_cents"] = sum(
        a["amount_cents"] for a in store.accessorials.values()
        if a["load_id"] == load["id"] and a["status"] == "BILLED")


def issue_invoice_cascade(inv):
    load = store.loads[inv["load_id"]]
    newly_billed = 0
    for a in store.accessorials.values():
        if a["load_id"] == load["id"] and a["status"] == "APPROVED":
            a["status"] = "BILLED"
            touch(a)
            newly_billed += a["amount_cents"]
    inv["status"] = "ISSUED"
    inv["accessorial_total_cents"] = newly_billed
    inv["total_cents"] = inv["linehaul_cents"] + inv["fuel_surcharge_cents"] + newly_billed
    touch(inv)
    load["status"] = "INVOICED"
    recompute_load_accessorial_total(load)
    trip = completed_trip_of_load(load["id"])
    load["final_margin_cents"] = final_margin(load, trip, newly_billed)
    touch(load)


def void_invoice_cascade(inv):
    load = store.loads[inv["load_id"]]
    for a in store.accessorials.values():
        if a["load_id"] == load["id"] and a["status"] == "BILLED":
            a["status"] = "APPROVED"
            touch(a)
    inv["status"] = "VOID"
    touch(inv)
    load["status"] = "DELIVERED"
    load["final_margin_cents"] = None
    recompute_load_accessorial_total(load)
    touch(load)
