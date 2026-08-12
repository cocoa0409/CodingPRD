"""Business calculations: index bands, supported indexes, recomputes,
notification create/resolve rules, and time-derived re-evaluation."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, base_entity, touch, fmt_ts, fmt_clock, month_index


def D(x):
    """Exact decimal from an int/float/str input."""
    return Decimal(str(x))

INDEX_RANK = {"NONE": 0, "A": 1, "B": 2, "C": 3, "D": 4, "E": 5}
RANK_INDEX = {v: k for k, v in INDEX_RANK.items()}
INDEXES = ["A", "B", "C", "D", "E"]
INDEXES_DESC = ["E", "D", "C", "B", "A"]

ALERT_RANK = {"ALERT_1": 1, "ALERT_2": 2, "ALERT_3": 3}
ALERT_LEVELS = ["ALERT_1", "ALERT_2", "ALERT_3"]
ALERT_INDEX_REQ = {"ALERT_1": "A", "ALERT_2": "B", "ALERT_3": "C"}

VEH_REQ = {"A": 1, "B": 2, "C": 2, "D": 3, "E": 3}
WATER_REQ = {"A": 100, "B": 1500, "C": 3000, "D": 4000, "E": 6000}
STAFF_REQ = {"A": 2, "B": 3, "C": 3, "D": 4, "E": 5}

DRILL_FIRST_MAX_SECONDS = 180
DRILL_ALL_MAX_SECONDS = 240

TRAINING_CURRENCY_MONTHS = 12
CURE_DAYS = 30

WATER_COST_CENTS_PER_GAL = 137
DRY_CHEM_COST_CENTS_PER_LB = 89

QUALIFYING_MIN_DAILY_DEPARTURES = 5.0
DRY_CHEM_WATER_EQUIV_GAL_PER_LB = 1.2
MAX_SUBSTITUTION_PCT = 0.5


# ---------------------------------------------------------------- aircraft
def index_band_for_aircraft(length_ft):
    L = D(length_ft)
    if L < 90:
        return "A"
    if L < 126:
        return "B"
    if L < 159:
        return "C"
    if L < 200:
        return "D"
    return "E"


def refresh_aircraft(a):
    a["qualifies_for_index"] = bool(a["in_scheduled_service"]) and \
        D(a["avg_daily_departures"]) >= D(str(QUALIFYING_MIN_DAILY_DEPARTURES))
    a["index_band"] = index_band_for_aircraft(a["length_ft"])


def qualifying_aircraft():
    return [a for a in store.aircraft.values() if a["qualifies_for_index"]]


def largest_qualifying_aircraft():
    """Greatest length_ft; tie-break greatest avg_daily_departures, then created_at ASC
    (earliest created wins the tie)."""
    qual = qualifying_aircraft()
    if not qual:
        return None
    ordered = sorted(qual, key=lambda a: (a["created_at"], a["_seq"]))
    best = None
    for a in ordered:
        if best is None:
            best = a
            continue
        la = D(a["length_ft"])
        lb = D(best["length_ft"])
        if la > lb:
            best = a
        elif la == lb:
            da = D(a["avg_daily_departures"])
            db_ = D(best["avg_daily_departures"])
            if da > db_:
                best = a
            # equal length and departures: earlier created (already best) wins
    return best


def compute_required_index_by_aircraft():
    best = largest_qualifying_aircraft()
    return best["index_band"] if best is not None else "A"


# ---------------------------------------------------------------- vehicles
def latest_check(vehicle_id):
    checks = [c for c in store.readiness_checks.values() if c["vehicle_id"] == vehicle_id]
    if not checks:
        return None
    checks.sort(key=lambda c: (c["_checked_dt"], c["_seq"]), reverse=True)
    return checks[0]


def measured_fleet():
    return [v for v in store.vehicles.values()
            if v["status"] == "IN_SERVICE" and v["latest_readiness_result"] == "PASS"]


def rated_fleet():
    return [v for v in store.vehicles.values() if v["status"] == "IN_SERVICE"]


def fleet_sums(fleet, rated):
    water = Decimal("0")
    chem = Decimal("0")
    for v in fleet:
        if rated:
            water += D(v["water_capacity_gal"])
            chem += D(v["dry_chem_capacity_lb"])
        else:
            c = latest_check(v["id"])
            if c is not None:
                water += D(c["water_available_gal"])
                chem += D(c["dry_chem_available_lb"])
    return water, chem


def effective_water(water_sum, chem_sum, index):
    chem_equiv = chem_sum * D(str(DRY_CHEM_WATER_EQUIV_GAL_PER_LB))
    cap = D(str(MAX_SUBSTITUTION_PCT)) * D(WATER_REQ[index])
    return water_sum + min(chem_equiv, cap)


def compute_supported_index_by_equipment(rated=False):
    fleet = rated_fleet() if rated else measured_fleet()
    water_sum, chem_sum = fleet_sums(fleet, rated)
    for idx in INDEXES_DESC:
        eff = effective_water(water_sum, chem_sum, idx)
        if len(fleet) >= VEH_REQ[idx] and eff >= D(WATER_REQ[idx]):
            return idx
    return "NONE"


# ---------------------------------------------------------------- roster
def refresh_firefighter(f):
    passes = [r for r in store.training_records.values()
              if r["firefighter_id"] == f["id"] and r["result"] == "PASS"]
    last = None
    if passes:
        passes.sort(key=lambda r: (r["_completed_date"], r["_seq"]), reverse=True)
        last = passes[0]["completed_on"]
    current = False
    if last is not None:
        current = (month_index(store.clock.date()) - month_index(passes[0]["_completed_date"])) \
            <= TRAINING_CURRENCY_MONTHS
    deployable = (f["status"] == "ACTIVE") and current
    if (f["last_live_fire_completed_on"] != last
            or f["is_training_current"] != current
            or f["is_deployable"] != deployable):
        f["last_live_fire_completed_on"] = last
        f["is_training_current"] = current
        f["is_deployable"] = deployable
        touch(f)


def deployment_ready():
    return [f for f in store.firefighters.values()
            if f["status"] == "ACTIVE" and f["is_training_current"]]


def roster_active():
    return [f for f in store.firefighters.values() if f["status"] == "ACTIVE"]


def compute_supported_index_by_staffing(roster=False):
    n = len(roster_active()) if roster else len(deployment_ready())
    for idx in INDEXES_DESC:
        if n >= STAFF_REQ[idx]:
            return idx
    return "NONE"


# ---------------------------------------------------------------- notifications
def open_notification():
    cands = [n for n in store.notifications.values()
             if n["status"] in ("PENDING", "ACKNOWLEDGED", "OVERDUE")]
    if not cands:
        return None
    cands.sort(key=lambda n: (n["created_at"], n["_seq"]))
    return cands[0]


def create_notification(prior_index, downgraded_index, cause):
    n = base_entity()
    cure = store.clock + timedelta(days=CURE_DAYS)
    n.update({
        "prior_index": prior_index,
        "downgraded_index": downgraded_index,
        "cause": cause,
        "notified_at": fmt_clock(store.clock),
        "cure_deadline": fmt_clock(cure),
        "status": "PENDING",
        "_cure_dt": cure,
    })
    store.notifications[n["id"]] = n
    return n


# ---------------------------------------------------------------- profile recompute
def compute_compliance(effective, certificated, required):
    if INDEX_RANK[effective] < INDEX_RANK[required]:
        return "NONCOMPLIANT"
    if effective == certificated and INDEX_RANK[certificated] >= INDEX_RANK[required]:
        return "COMPLIANT"
    return "DOWNGRADED"


def recompute_profile(bump="always", prev_cert=None, suppress_notification=False):
    """Recompute derived profile fields; apply notification create/resolve rules.

    bump: "always" -> version+1 unconditionally; "if_changed" -> only when a
    derived field changed; "never" -> no bump (initial profile creation).
    """
    p = store.profile
    if p is None:
        return
    old_effective = p.get("effective_index")
    old_cert = prev_cert if prev_cert is not None else p["certificated_index"]
    cert = p["certificated_index"]

    new_required = compute_required_index_by_aircraft()
    new_equip = compute_supported_index_by_equipment()
    new_staff = compute_supported_index_by_staffing()
    new_effective = RANK_INDEX[min(INDEX_RANK[cert], INDEX_RANK[new_equip],
                                   INDEX_RANK[new_staff])]
    new_compliance = compute_compliance(new_effective, cert, new_required)

    changed = (
        new_required != p.get("required_index_by_aircraft")
        or new_equip != p.get("supported_index_by_equipment")
        or new_staff != p.get("supported_index_by_staffing")
        or new_effective != old_effective
        or new_compliance != p.get("index_compliance_status")
        or cert != old_cert
    )
    p["required_index_by_aircraft"] = new_required
    p["supported_index_by_equipment"] = new_equip
    p["supported_index_by_staffing"] = new_staff
    p["effective_index"] = new_effective
    p["index_compliance_status"] = new_compliance
    if bump == "always" or (bump == "if_changed" and changed):
        touch(p)

    if not suppress_notification:
        # CREATE: effective drops from >= certificated to strictly below it,
        # and no open notification exists. Initial recompute (old None) never fires.
        if old_effective is not None and old_cert is not None:
            dropped = (INDEX_RANK[old_effective] >= INDEX_RANK[old_cert]
                       and INDEX_RANK[new_effective] < INDEX_RANK[cert])
            if dropped and open_notification() is None:
                cause = ("EQUIPMENT" if INDEX_RANK[new_equip] < INDEX_RANK[cert]
                         else "STAFFING")
                create_notification(old_effective, new_effective, cause)
        # RESOLVE: effective returns to certificated with an open notification.
        if new_effective == cert:
            n = open_notification()
            if n is not None:
                n["status"] = "RESOLVED"
                touch(n)


# ---------------------------------------------------------------- time-derived
def apply_time_derived():
    """Re-evaluate training currency, agreement expiry, notification overdue,
    and the full effective-index recompute. Invoked on logical-clock advance
    and at the start of every request (a no-op when the clock has not moved)."""
    today = store.clock.date()
    for f in list(store.firefighters.values()):
        refresh_firefighter(f)
    for a in list(store.agreements.values()):
        if a["status"] in ("DRAFT", "ACTIVE") and a["_end_date"] < today:
            a["status"] = "EXPIRED"
            touch(a)
    for n in list(store.notifications.values()):
        if n["status"] in ("PENDING", "ACKNOWLEDGED") and store.clock > n["_cure_dt"]:
            n["status"] = "OVERDUE"
            touch(n)
    recompute_profile(bump="if_changed")


# ---------------------------------------------------------------- misc calculations
def drill_outcome(first_vehicle_arrival_seconds, all_vehicles_arrival_seconds):
    if (first_vehicle_arrival_seconds <= DRILL_FIRST_MAX_SECONDS
            and all_vehicles_arrival_seconds <= DRILL_ALL_MAX_SECONDS):
        return "PASS"
    return "FAIL"


def agent_expense_total_cents(lines):
    """Round half-up per line, then sum (pinned rounding order)."""
    total = 0
    for ln in lines:
        cents = (D(ln["water_gal_used"]) * WATER_COST_CENTS_PER_GAL
                 + D(ln["dry_chem_lb_used"]) * DRY_CHEM_COST_CENTS_PER_LB)
        total += int(cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return total
