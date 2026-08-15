"""Domain services: derived fields, cascades, calculations.

Covers: fleet posture, bus availability/holds, pm_due_status, work-order cost,
core exchange, warranty claim amounts, campaign progress, replacement scoring,
shift coverage, and the epoch sweep.
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import db, meta, mark_dirty, clock_date, clock_now, fmt_date

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SPARE_GREEN_MIN = Decimal("0.20")
SPARE_YELLOW_MIN = Decimal("0.15")
PULL_OUT_FRACTION = Decimal("0.80")

FALLBACK_AVG_DAILY_MILES = 200
MPG_ANOMALY_PCT = 85
BASELINE_LOG_COUNT = 3

BASE_HOURLY_RATE_CENTS = 6500
SHIFT_DIFFERENTIALS = {
    "AM": Decimal("1.00"),
    "PM": Decimal("1.10"),
    "NIGHT": Decimal("1.25"),
}

CORE_RETURN_WINDOW_DAYS = 30
CORE_LATE_GRACE_DAYS = 15
LATE_TIER_PCT = Decimal("0.50")

OVERHAUL_CAP_PCT = Decimal("0.40")

W_AGE = Decimal("0.30")
W_MILES = Decimal("0.30")
W_COST = Decimal("0.25")
W_OVERHAUL = Decimal("0.15")
AGE_NORM_YEARS = 12
MILES_NORM = 500000
PM_OVERDUE_MULTIPLIER = Decimal("1.25")
REPLACE_THRESHOLD = Decimal("0.70")
OVERHAUL_THRESHOLD = Decimal("0.45")

CERT_TYPES = {
    "ENGINE", "TRANSMISSION", "BRAKES", "ELECTRICAL", "HVAC",
    "EMISSIONS", "PM_INSPECTION", "QA_AUTHORITY",
}

WO_TYPES = {"PM_A", "PM_B", "PM_C", "CAMPAIGN", "CORRECTIVE", "EMISSIONS", "OVERHAUL"}
WO_PRIORITIES = {"EMERGENCY", "URGENT", "ROUTINE", "ELECTIVE"}
WO_TERMINAL = {"CLOSED", "CANCELLED"}
WO_IN_PROGRESS_FAMILY = {"IN_PROGRESS", "AWAITING_PARTS", "PENDING_QA", "REOPENED"}

DEFECT_SEVERITIES = {"SAFETY_CRITICAL", "MAJOR", "MINOR"}
DEFECT_CODES = {"ENGINE", "TRANSMISSION", "BRAKES", "ELECTRICAL", "HVAC",
                "FUEL_SYSTEM", "TIRE", "OTHER"}
DEFECT_TERMINAL = {"RESOLVED", "WITHDRAWN"}

LINE_ISSUE_TERMINAL = {"CONSUMED", "RETURNED", "RELEASED"}
CORE_TERMINAL = {"CORE_CREDITED", "CORE_REJECTED"}

CLAIM_TYPES = {"BASE_OEM", "EXTENDED", "PARTS_ONLY", "GOODWILL"}
CLAIM_TERMINAL = {"RECOVERED", "WITHDRAWN"}

CAMPAIGN_TERMINAL = {"COMPLETED", "CLOSED"}

SHIFT_TYPES = {"AM", "PM", "NIGHT"}
SHIFT_ROLES = {"LEAD", "TECH", "QA"}
ASSIGNMENT_TERMINAL = {"COMPLETED", "NO_SHOW", "REMOVED"}

# defect_code -> required cert for road-call dispatch (None = no cert needed)
DEFECT_CERT_MAP = {
    "ENGINE": "ENGINE",
    "TRANSMISSION": "TRANSMISSION",
    "BRAKES": "BRAKES",
    "ELECTRICAL": "ELECTRICAL",
    "HVAC": "HVAC",
    "FUEL_SYSTEM": "ENGINE",
    "TIRE": None,
    "OTHER": None,
}

# wo_type -> required cert at START (None = no cert needed; CAMPAIGN is dynamic)
WO_CERT_MAP = {
    "PM_A": "PM_INSPECTION",
    "PM_B": "PM_INSPECTION",
    "PM_C": "PM_INSPECTION",
    "EMISSIONS": "EMISSIONS",
    "OVERHAUL": "ENGINE",
    "CORRECTIVE": None,
}

# shift_type -> half-open interval in minutes from midnight of shift_date
SHIFT_INTERVALS = {
    "AM": (6 * 60, 14 * 60),
    "PM": (14 * 60, 22 * 60),
    "NIGHT": (22 * 60, 30 * 60),  # 22:00 -> 06:00 next day
}

PM_LEVELS = ("A", "B", "C")
PM_SEVERITY_ORDER = {"CURRENT": 0, "DUE_SOON": 1, "DUE": 2, "OVERDUE": 3}


def _dec(val):
    return Decimal(str(val))


def _rhup(dec_val, places=0):
    """Round half-up to the given number of decimal places, return int/Decimal."""
    q = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    return dec_val.quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Cert helpers
# ---------------------------------------------------------------------------
def mechanic_cert_state(mechanic_id, cert_type):
    """Returns 'ok' | 'absent' | 'expired' for the mechanic's best cert of type."""
    if cert_type is None:
        return "ok"
    best = None
    for cert in db["certifications"].values():
        if cert["mechanic_id"] == mechanic_id and cert["cert_type"] == cert_type:
            st = cert["status"]
            if st in ("VALID", "EXPIRING_SOON"):
                return "ok"
            best = "expired"
    return best or "absent"


def require_cert(mechanic_id, cert_type):
    state = mechanic_cert_state(mechanic_id, cert_type)
    if state == "absent":
        from errors import err
        raise err("ERR_CERT_REQUIRED",
                  f"Mechanic {mechanic_id} lacks required certification {cert_type}")
    if state == "expired":
        from errors import err
        raise err("ERR_CERT_EXPIRED",
                  f"Mechanic {mechanic_id} certification {cert_type} is EXPIRED")


# ---------------------------------------------------------------------------
# Bus availability & holds
# ---------------------------------------------------------------------------
def compute_hold_reasons(bus):
    """Derive hold reasons from defect states + the emissions hold flag."""
    reasons = set()
    bus_id = bus["id"]
    for d in db["defects"].values():
        if d["bus_id"] != bus_id:
            continue
        if d["status"] in ("RESOLVED", "WITHDRAWN"):
            continue
        if d["severity"] == "SAFETY_CRITICAL":
            reasons.add("SAFETY")
        if d["status"] in ("ROAD_CALL_DISPATCHED", "ON_SCENE"):
            reasons.add("ROAD_CALL")
        if d.get("resolution") == "TOWED_IN":
            reasons.add("TOWED")
    if bus.get("emissions_hold"):
        reasons.add("EMISSIONS")
    return reasons


def recompute_bus_availability(bus):
    """Recompute hold_reasons + availability_status; mark dirty on change."""
    old_avail = bus.get("availability_status")
    old_holds = list(bus.get("hold_reasons") or [])
    holds = compute_hold_reasons(bus)
    if bus["service_status"] == "RETIRED":
        avail = "OUT_OF_SERVICE"
        holds = set()
    elif any(wo for wo in db["work_orders"].values()
             if wo["bus_id"] == bus["id"] and wo["status"] in WO_IN_PROGRESS_FAMILY):
        avail = "IN_SHOP"
    elif holds:
        avail = "HELD"
    else:
        avail = "AVAILABLE"
    bus["hold_reasons"] = sorted(holds)
    bus["availability_status"] = avail
    if avail != old_avail or bus["hold_reasons"] != old_holds:
        mark_dirty("buses", bus["id"])
    return avail


def bus_emissions_compliance(bus):
    if "EMISSIONS" in (bus.get("hold_reasons") or []):
        return "NON_COMPLIANT"
    expiry = bus.get("emissions_cert_expiry_date")
    if expiry and expiry < fmt_date(clock_date()):
        return "CERT_EXPIRED"
    return "COMPLIANT"


# ---------------------------------------------------------------------------
# Fleet posture
# ---------------------------------------------------------------------------
def compute_posture():
    active = [b for b in db["buses"].values()
              if b["service_status"] in ("ACTIVE", "OVERHAUL_HOLD")]
    active_count = len(active)
    available_count = sum(1 for b in active if b["availability_status"] == "AVAILABLE")
    if active_count == 0:
        spare = Decimal("1.0")
        posture = "GREEN"
    else:
        spare = _rhup(Decimal(available_count) / Decimal(active_count), 4)
        if spare >= SPARE_GREEN_MIN:
            posture = "GREEN"
        elif spare >= SPARE_YELLOW_MIN:
            posture = "YELLOW"
        else:
            posture = "RED"
    pull_out_minimum = math.ceil(PULL_OUT_FRACTION * active_count) if active_count else 0
    pull_out_ready = available_count >= pull_out_minimum
    return {
        "active_buses": active_count,
        "available_buses": available_count,
        "spare_ratio": float(spare),
        "posture": posture,
        "pull_out_minimum": pull_out_minimum,
        "pull_out_ready": pull_out_ready,
    }


def current_posture():
    if meta["posture"] is None:
        meta["posture"] = compute_posture()
    return meta["posture"]


def recompute_posture():
    """Recompute posture; fire RED freeze / recovery cascades on tier change."""
    old = current_posture()["posture"]
    new = compute_posture()
    meta["posture"] = new
    if old != "RED" and new["posture"] == "RED":
        for wo in db["work_orders"].values():
            if wo["status"] == "SCHEDULED" and wo["priority"] in ("ROUTINE", "ELECTIVE"):
                wo["status"] = "BLOCKED"
                mark_dirty("work_orders", wo["id"])
    elif old == "RED" and new["posture"] != "RED":
        for wo in db["work_orders"].values():
            if wo["status"] == "BLOCKED":
                wo["status"] = "SCHEDULED"
                mark_dirty("work_orders", wo["id"])
    return new


# ---------------------------------------------------------------------------
# PM due status
# ---------------------------------------------------------------------------
def active_policy():
    for p in db["pm_policies"].values():
        if p["status"] == "ACTIVE":
            return p
    return None


def _pm_level_status(interval_miles, miles_since, days_since, tolerance, calendar_days):
    miles_remaining = interval_miles - miles_since
    if miles_remaining > tolerance:
        mileage_status = "CURRENT"
    elif miles_remaining >= 1:
        mileage_status = "DUE_SOON"
    elif miles_remaining == 0:
        mileage_status = "DUE"
    else:
        mileage_status = "OVERDUE"
    days_remaining = calendar_days - days_since
    if days_remaining > 14:
        calendar_status = "CURRENT"
    elif days_remaining >= 1:
        calendar_status = "DUE_SOON"
    elif days_remaining == 0:
        calendar_status = "DUE"
    else:
        calendar_status = "OVERDUE"
    return (mileage_status if PM_SEVERITY_ORDER[mileage_status]
            >= PM_SEVERITY_ORDER[calendar_status] else calendar_status)


def compute_pm_due(bus, policy=None):
    """Returns (pm_due_status, next_pm_level). Pure function of bus + policy +
    clock date."""
    if policy is None:
        policy = active_policy()
    if policy is None:
        return "CURRENT", "A"
    today = clock_date()
    intervals = {
        "A": policy["level_a_interval_miles"],
        "B": policy["level_b_interval_miles"],
        "C": policy["level_c_interval_miles"],
    }
    worst = "CURRENT"
    worst_level = None
    for level in PM_LEVELS:
        miles_since = bus["odometer_miles"] - bus[f"last_pm_{level.lower()}_miles"]
        last_date = bus[f"last_pm_{level.lower()}_date"]
        if isinstance(last_date, str):
            from datetime import datetime as _dt
            last_date = _dt.strptime(last_date, "%Y-%m-%d").date()
        days_since = (today - last_date).days
        st = _pm_level_status(intervals[level], miles_since, days_since,
                              policy["tolerance_miles"],
                              policy["calendar_interval_days"])
        if PM_SEVERITY_ORDER[st] > PM_SEVERITY_ORDER[worst]:
            worst = st
        if st != "CURRENT":
            worst_level = level  # C > B > A because iteration is A, B, C
    return worst, (worst_level or "A")


def recompute_pm_due(bus, policy=None):
    status, level = compute_pm_due(bus, policy)
    if bus.get("pm_due_status") != status or bus.get("_next_pm_level") != level:
        bus["pm_due_status"] = status
        bus["_next_pm_level"] = level
        mark_dirty("buses", bus["id"])


def recompute_pm_due_all(policy=None):
    for bus in db["buses"].values():
        if bus["service_status"] == "ACTIVE":
            recompute_pm_due(bus, policy)


# ---------------------------------------------------------------------------
# Work order cost (ACTUAL variant; ESTIMATE is descriptive)
# ---------------------------------------------------------------------------
def labor_amount_cents(hours, shift_type):
    amt = _dec(hours) * BASE_HOURLY_RATE_CENTS * SHIFT_DIFFERENTIALS[shift_type]
    return int(_rhup(amt, 0))


def wo_lines(wo_id):
    return [l for l in db["part_lines"].values() if l["work_order_id"] == wo_id]


def line_total_cents(line):
    if line["issue_status"] in ("ISSUED", "CONSUMED"):
        return line["qty_issued"] * line["unit_cost_cents"]
    return 0


def wo_costs(wo):
    labor_total = sum(e["amount_cents"] for e in wo.get("labor_entries", []))
    parts_total = sum(line_total_cents(l) for l in wo_lines(wo["id"]))
    parts_net = parts_total - wo.get("core_credits_cents", 0)
    return {
        "labor_total_cents": labor_total,
        "parts_total_cents": parts_total,
        "parts_net_cents": parts_net,
        "total_cost_cents": labor_total + parts_net,
    }


def recompute_wo_costs(wo):
    costs = wo_costs(wo)
    changed = False
    for k, v in costs.items():
        if wo.get(k) != v:
            wo[k] = v
            changed = True
    if changed:
        mark_dirty("work_orders", wo["id"])


# ---------------------------------------------------------------------------
# Part stock
# ---------------------------------------------------------------------------
def part_available(part):
    return part["quantity_on_hand"] - part["quantity_reserved"]


def derive_stock_status(part):
    avail = part_available(part)
    if avail < 0:
        return "BACKORDERED"
    if avail <= part["reorder_point"]:
        return "LOW_STOCK"
    return "NORMAL"


def recompute_stock_status(part):
    old = part.get("stock_status")
    new = derive_stock_status(part)
    if new != old:
        part["stock_status"] = new
        mark_dirty("parts", part["id"])
        if new == "BACKORDERED":
            # conditional cascade: ACTIVE campaigns requiring this part suspend
            for camp in db["campaigns"].values():
                if (camp.get("required_part_id") == part["id"]
                        and camp["status"] == "ACTIVE"):
                    camp["status"] = "SUSPENDED"
                    mark_dirty("campaigns", camp["id"])


# ---------------------------------------------------------------------------
# Campaign progress
# ---------------------------------------------------------------------------
def campaign_progress(camp):
    scope = camp.get("scope_bus_ids") or []
    if not scope:
        return 0, 0.0
    closed_bus_ids = set()
    for wo in db["work_orders"].values():
        if (wo.get("campaign_id") == camp["id"] and wo["status"] == "CLOSED"
                and wo["bus_id"] in scope):
            closed_bus_ids.add(wo["bus_id"])
    count = len(closed_bus_ids)
    pct = _rhup(Decimal(100 * count) / Decimal(len(scope)), 2)
    return count, float(pct)


# ---------------------------------------------------------------------------
# Warranty claim amounts
# ---------------------------------------------------------------------------
def base_warranty_ok(bus, wo):
    return (wo["odometer_at_open"] <= bus["base_warranty_expiry_miles"]
            and wo["opened_date"] <= bus["base_warranty_expiry_date"])


def extended_warranty_ok(bus, wo):
    ext_miles = bus.get("extended_warranty_limit_miles")
    ext_months = bus.get("extended_warranty_limit_months")
    if ext_miles is None or ext_months is None:
        return False
    if base_warranty_ok(bus, wo):
        return False
    if wo["odometer_at_open"] > ext_miles:
        return False
    from datetime import datetime as _dt
    opened = _dt.strptime(wo["opened_date"], "%Y-%m-%d").date()
    in_service = _dt.strptime(bus["in_service_date"], "%Y-%m-%d").date()
    days = (opened - in_service).days
    return days <= ext_months * 30


def compute_claim_amounts(claim):
    """Compute (eligible_cents, claimed_cents) at SUBMIT from the frozen basis."""
    wo = db["work_orders"][claim["work_order_id"]]
    bus = db["buses"][wo["bus_id"]]
    costs = wo_costs(wo)
    labor = costs["labor_total_cents"]
    eligible_lines = 0
    for line in wo_lines(wo["id"]):
        part = db["parts"].get(line["part_id"])
        if part is not None and part.get("warranty_eligible"):
            eligible_lines += line_total_cents(line)
    credits = wo.get("core_credits_cents", 0)

    ctype = claim["claim_type"]
    if ctype == "GOODWILL":
        eligible = claim.get("manual_claimed_cents") or 0
        return eligible, eligible
    if ctype in ("BASE_OEM", "EXTENDED"):
        eligible = labor + eligible_lines - credits
    else:  # PARTS_ONLY
        eligible = eligible_lines - credits
    if ctype == "EXTENDED":
        if claim.get("proration_basis") == "MILES":
            ext_miles = bus.get("extended_warranty_limit_miles") or 0
            if ext_miles > 0:
                headroom = max(0, ext_miles - wo["odometer_at_open"])
                fraction = Decimal(headroom) / Decimal(ext_miles)
            else:
                fraction = Decimal(0)
        else:  # TIME
            ext_months = bus.get("extended_warranty_limit_months") or 0
            from datetime import datetime as _dt
            opened = _dt.strptime(wo["opened_date"], "%Y-%m-%d").date()
            in_service = _dt.strptime(bus["in_service_date"], "%Y-%m-%d").date()
            days = (opened - in_service).days
            window = ext_months * 30
            if window > 0:
                headroom = max(0, window - days)
                fraction = Decimal(headroom) / Decimal(window)
            else:
                fraction = Decimal(0)
        claimed = int(_rhup(Decimal(eligible) * fraction, 0))
    else:
        claimed = eligible
    return eligible, claimed


# ---------------------------------------------------------------------------
# Replacement scoring
# ---------------------------------------------------------------------------
def compute_replacement_scores():
    today = clock_date()
    scores = []
    for bus in db["buses"].values():
        if bus["service_status"] != "ACTIVE":
            continue
        from datetime import datetime as _dt
        in_service = _dt.strptime(bus["in_service_date"], "%Y-%m-%d").date()
        age_years = (today - in_service).days // 365
        age_norm = min(Decimal(age_years) / Decimal(AGE_NORM_YEARS), Decimal(1))
        miles_norm = min(Decimal(bus["odometer_miles"]) / Decimal(MILES_NORM),
                         Decimal(1))
        repl = bus["replacement_cost_cents"]
        if repl > 0:
            cost_ratio = min(Decimal(bus.get("total_maintenance_cost_cents", 0))
                             / Decimal(repl), Decimal(1))
        else:
            cost_ratio = Decimal(1)
        overdue = 1 if (bus["odometer_miles"] - bus.get("last_overhaul_miles", 0)
                        > bus["overhaul_interval_miles"]) else 0
        score = (W_AGE * age_norm + W_MILES * miles_norm + W_COST * cost_ratio
                 + W_OVERHAUL * overdue)
        if bus.get("pm_due_status") == "OVERDUE":
            score = min(score * PM_OVERDUE_MULTIPLIER, Decimal(1))
        score = _rhup(score, 4)
        if score >= REPLACE_THRESHOLD:
            rec = "REPLACE"
        elif score >= OVERHAUL_THRESHOLD:
            rec = "OVERHAUL"
        else:
            rec = "KEEP"
        scores.append({
            "bus_id": bus["id"],
            "score": float(score),
            "recommendation": rec,
            "age_years": age_years,
            "odometer_miles": bus["odometer_miles"],
            "cost_ratio": float(_rhup(cost_ratio, 4)),
            "overhaul_overdue": overdue,
            "_fleet_number": bus["fleet_number"],
            "_created_at": bus["created_at"],
            "_seq": bus["_seq"],
        })
    scores.sort(key=lambda s: (-s["score"], s["_fleet_number"], s["_created_at"],
                               s["_seq"]))
    for s in scores:
        s.pop("_fleet_number", None)
        s.pop("_created_at", None)
        s.pop("_seq", None)
    return scores


# ---------------------------------------------------------------------------
# Shift coverage
# ---------------------------------------------------------------------------
def shift_coverage(shift):
    required = shift.get("required_headcount") or {}
    coverage = {}
    for cert_type in required:
        count = 0
        for asg in db["assignments"].values():
            if asg["shift_id"] != shift["id"] or asg["status"] != "CONFIRMED":
                continue
            if mechanic_cert_state(asg["mechanic_id"], cert_type) == "ok":
                count += 1
        coverage[cert_type] = count
    full = all(coverage.get(c, 0) >= n for c, n in required.items())
    return coverage, ("FULL" if full else "SHORT")


def shift_absolute_interval(shift):
    """(start_min, end_min) absolute minutes from day 0 for overlap checks."""
    from datetime import datetime as _dt
    d = shift["shift_date"]
    if isinstance(d, str):
        d = _dt.strptime(d, "%Y-%m-%d").date()
    start, end = SHIFT_INTERVALS[shift["shift_type"]]
    base = d.toordinal() * 1440
    return base + start, base + end


def mechanic_on_shift(mechanic_id):
    """CONFIRMED assignment on a PUBLISHED shift covering the clock date."""
    today = clock_date()
    now = clock_now()
    for asg in db["assignments"].values():
        if asg["mechanic_id"] != mechanic_id or asg["status"] != "CONFIRMED":
            continue
        shift = db["shifts"].get(asg["shift_id"])
        if shift is None or shift["status"] != "PUBLISHED":
            continue
        from datetime import datetime as _dt
        sd = shift["shift_date"]
        if isinstance(sd, str):
            sd = _dt.strptime(sd, "%Y-%m-%d").date()
        if sd == today:
            return True
        # NIGHT shift spills into the next day until 06:00
        if shift["shift_type"] == "NIGHT" and (sd + timedelta(days=1)) == today:
            if (now.hour, now.minute) < (6, 0):
                return True
    return False


# ---------------------------------------------------------------------------
# Mileage / fuel anomaly
# ---------------------------------------------------------------------------
def baseline_logs(bus_id, exclude_log_id=None):
    logs = [l for l in db["logs"].values()
            if l["bus_id"] == bus_id and l["status"] != "VOIDED"
            and l["id"] != exclude_log_id]
    logs.sort(key=lambda l: (l["log_date"], l["created_at"], l["_seq"]))
    return logs[-BASELINE_LOG_COUNT:]


def check_fuel_anomaly(new_log):
    """Returns True if the new log is anomalous vs its baseline window."""
    baseline = baseline_logs(new_log["bus_id"], exclude_log_id=new_log["id"])
    if len(baseline) < BASELINE_LOG_COUNT:
        return False
    base_miles = sum(l["miles_driven"] for l in baseline)
    base_fuel = sum(l["fuel_gallons"] for l in baseline)
    lhs = new_log["miles_driven"] * base_fuel * 100
    rhs = MPG_ANOMALY_PCT * base_miles * new_log["fuel_gallons"]
    return lhs < rhs


def avg_daily_miles_for_bus(bus_id):
    baseline = baseline_logs(bus_id)
    if len(baseline) < BASELINE_LOG_COUNT:
        return FALLBACK_AVG_DAILY_MILES
    from datetime import datetime as _dt
    total_miles = sum(l["miles_driven"] for l in baseline)
    first = _dt.strptime(baseline[0]["log_date"], "%Y-%m-%d").date()
    last = _dt.strptime(baseline[-1]["log_date"], "%Y-%m-%d").date()
    days = max(1, (last - first).days)
    return int(_rhup(Decimal(total_miles) / Decimal(days), 0))
