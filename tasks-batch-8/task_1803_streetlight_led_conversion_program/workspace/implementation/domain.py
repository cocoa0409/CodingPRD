"""Domain logic: lookups, computed rollups, serializers, calculations (PRD 3),
budget ledger postings (PRD 2.5), and cascade helpers."""
import calendar
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import new_record, public, store, touch
from errors import raise_error
from util import CLOCK, fmt_dt, parse_date, period_bounds, rhu_int

# ---------------------------------------------------------------------------
# Constants (PRD 2.6, 3.3, 3.4, 3.6, 3.7, 3.8)
# ---------------------------------------------------------------------------

CCT_CAP_KELVIN = {"RESIDENTIAL": 3000, "ARTERIAL": 4000, "DOWNTOWN": 2700, "RURAL": 2200}
FULL_CUTOFF_ZONES = {"RESIDENTIAL", "RURAL"}

STOP_MINUTES = {"STANDARD": 45, "HEAVY": 75, "COMPLEX": 120}
SHIFT_MINUTES = 480
MOBILIZATION_TRAFFIC_MINUTES = 60
MOBILIZATION_BASE_MINUTES = 30

WEEKLY_OVERTIME_MINUTES = 2400
OVERTIME_MULTIPLIER = Decimal("1.5")
REPLACEMENT_STOP_MINUTES = 75

PRICE_PER_LB_CENTS = {"COBRA_HEAD": 85, "FLOOD": 95, "POST_TOP": 70, "DECORATIVE": 110}
MERCURY_DEDUCTION_CENTS = 300
CONTAMINATION_RATE = Decimal("0.15")
TRANSPORT_FEE_CENTS = 4500

SLA_HOURS = {"CRITICAL": 24, "HIGH": 48, "STANDARD": 96}
REOPEN_WINDOW_HOURS = 72

BURN_HOURS = {
    "01": 420, "02": 380, "03": 360, "04": 320, "05": 290, "06": 270,
    "07": 280, "08": 310, "09": 340, "10": 380, "11": 410, "12": 430,
}

TIERS = ("T1", "T2", "T3", "T4", "T5")


# ---------------------------------------------------------------------------
# Lookups and graph walking
# ---------------------------------------------------------------------------

def program_of_district(district):
    return store.programs.get(district["program_id"])


def program_of_pole(pole):
    district = store.districts.get(pole["district_id"])
    return program_of_district(district) if district else None


def program_of_route(route):
    district = store.districts.get(route["district_id"])
    return program_of_district(district) if district else None


def program_of_stop(stop):
    route = store.routes.get(stop["route_id"])
    return program_of_route(route) if route else None


def program_of_work_order(wo):
    pole = store.poles.get(wo["pole_id"])
    return program_of_pole(pole) if pole else None


def program_of_audit(audit):
    pole = store.poles.get(audit["pole_id"])
    return program_of_pole(pole) if pole else None


def program_of_account(account):
    district = store.districts.get(account["district_id"])
    return program_of_district(district) if district else None


def program_of_ticket(ticket):
    pole = store.poles.get(ticket["pole_id"])
    return program_of_pole(pole) if pole else None


def program_of_exception(exc):
    pole = store.poles.get(exc["pole_id"])
    return program_of_pole(pole) if pole else None


def require_active(program):
    """Stage 8: child-resource mutations require an ACTIVE program."""
    if program is None or program["status"] != "ACTIVE":
        raise_error("ERR_PROGRAM_NOT_ACTIVE", "program is not ACTIVE")


def poles_of_program(program_id):
    return [p for p in store.poles.values()
            if (store.districts.get(p["district_id"]) or {}).get("program_id") == program_id]


def accounts_of_program(program_id):
    return [a for a in store.accounts.values()
            if (store.districts.get(a["district_id"]) or {}).get("program_id") == program_id]


def routes_of_program(program_id):
    return [r for r in store.routes.values()
            if (store.districts.get(r["district_id"]) or {}).get("program_id") == program_id]


# ---------------------------------------------------------------------------
# Wattage tiers (PRD 2.6) — lower bounds inclusive
# ---------------------------------------------------------------------------

def tier_of(wattage: int) -> str:
    if wattage < 100:
        return "T1"
    if wattage < 200:
        return "T2"
    if wattage < 300:
        return "T3"
    if wattage < 450:
        return "T4"
    return "T5"


def pole_billing_wattage(pole) -> int:
    return pole["led_wattage"] if pole["led_in_service_date"] is not None else pole["effective_wattage"]


# ---------------------------------------------------------------------------
# Route computed counters (PRD 3.3)
# ---------------------------------------------------------------------------

def stops_of_route(route_id):
    return [s for s in store.stops.values() if s["route_id"] == route_id]


def route_stop_count(route) -> int:
    return sum(1 for s in stops_of_route(route["id"]) if s["status"] in ("PENDING", "BLOCKED", "COMPLETE"))


def route_blocked_count(route) -> int:
    return sum(1 for s in stops_of_route(route["id"]) if s["status"] == "BLOCKED")


def route_total_workload(route) -> int:
    return sum(s["stop_minutes"] for s in stops_of_route(route["id"]) if s["status"] != "SKIPPED")


def route_required_shifts(route) -> int:
    total = route_total_workload(route)
    if total <= 0:
        return 0
    mobilization = MOBILIZATION_TRAFFIC_MINUTES if route["traffic_control_required"] else MOBILIZATION_BASE_MINUTES
    net = SHIFT_MINUTES - mobilization
    return -(-total // net)


def evaluate_auto_suspension(route):
    """route_auto_suspension: IN_PROGRESS route with blocked*2 >= stop_count suspends."""
    if route["status"] != "IN_PROGRESS":
        return
    sc = route_stop_count(route)
    bc = route_blocked_count(route)
    if sc >= 1 and bc * 2 >= sc:
        route["status"] = "SUSPENDED"
        touch(route)


def evaluate_auto_close(route):
    """route_auto_close: every stop COMPLETE/SKIPPED, no work order in
    PENDING/DISPATCHED/FAILED/REWORK_PENDING, none AWAITING_QC -> CLOSED."""
    if route["status"] != "IN_PROGRESS":
        return
    stops = stops_of_route(route["id"])
    if not all(s["status"] in ("COMPLETE", "SKIPPED") for s in stops):
        return
    wos = [o for o in store.work_orders.values() if o["route_id"] == route["id"]]
    if any(o["execution_status"] in ("PENDING", "DISPATCHED", "FAILED", "REWORK_PENDING") for o in wos):
        return
    if any(o["qc_status"] == "AWAITING_QC" for o in wos):
        return
    route["status"] = "CLOSED"
    touch(route)


# ---------------------------------------------------------------------------
# Budget ledger (PRD 2.5). Postings mutate budget_balance_cents; the
# program's version bumps only where PRD/scaffold call it out.
# ---------------------------------------------------------------------------

def post_budget(program, delta_cents: int):
    program["budget_balance_cents"] += delta_cents
    program["updated_at"] = CLOCK.now_ts()


def bump_program(program):
    touch(program)


# ---------------------------------------------------------------------------
# Monthly unmetered charge (PRD 3.5) — dual variant
# ---------------------------------------------------------------------------

def find_rate_schedule(program_id, ownership_class, p_start: date):
    """The EFFECTIVE-or-SUPERSEDED schedule of (program, class) whose half-open
    window [effective_from, effective_until) covers p_start."""
    covering = []
    for s in store.rate_schedules.values():
        if s["program_id"] != program_id or s["ownership_class"] != ownership_class:
            continue
        if s["status"] not in ("EFFECTIVE", "SUPERSEDED"):
            continue
        ef = parse_date(s["effective_from"])
        eu = parse_date(s["effective_until"]) if s["effective_until"] else None
        if ef <= p_start and (eu is None or p_start < eu):
            covering.append(s)
    if not covering:
        return None
    covering.sort(key=lambda s: (s["status"] == "EFFECTIVE", s["effective_from"], s["_seq"]),
                  reverse=True)
    return covering[0]


def monthly_charge(pole, period: str):
    """Return dict(charge_cents, billing_wattage, tier, rate_schedule_id) or
    None when no covering schedule exists."""
    district = store.districts.get(pole["district_id"])
    program_id = district["program_id"]
    p_start, p_end, D = period_bounds(period)
    sched = find_rate_schedule(program_id, pole["ownership_type"], p_start)
    if sched is None:
        return None
    eff = pole["effective_wattage"]
    led = pole["led_wattage"]
    isd = parse_date(pole["led_in_service_date"]) if pole["led_in_service_date"] else None
    r_old = sched["tier_rates"][tier_of(eff)]
    r_new = sched["tier_rates"][tier_of(led)] if led is not None else None

    if pole["ownership_type"] == "MUNICIPAL":
        # Daily proration; the in-service day bills the NEW rate.
        if isd is None or isd > p_end:
            return {"charge_cents": r_old, "billing_wattage": eff, "tier": tier_of(eff),
                    "rate_schedule_id": sched["id"]}
        if isd <= p_start:
            return {"charge_cents": r_new, "billing_wattage": led, "tier": tier_of(led),
                    "rate_schedule_id": sched["id"]}
        d_old = (isd - p_start).days
        d_new = D - d_old
        charge = rhu_int(r_old * d_old, D) + rhu_int(r_new * d_new, D)
        return {"charge_cents": charge, "billing_wattage": led, "tier": tier_of(led),
                "rate_schedule_id": sched["id"]}
    # UTILITY_OWNED: whole-month deferral — the conversion month bills the OLD
    # rate wholesale; the new rate applies from the next period.
    if isd is None or isd > p_end:
        return {"charge_cents": r_old, "billing_wattage": eff, "tier": tier_of(eff),
                "rate_schedule_id": sched["id"]}
    if isd >= p_start:
        return {"charge_cents": r_old, "billing_wattage": eff, "tier": tier_of(eff),
                "rate_schedule_id": sched["id"]}
    return {"charge_cents": r_new, "billing_wattage": led, "tier": tier_of(led),
            "rate_schedule_id": sched["id"]}


def rerate_estimated_lines_for_pole(pole):
    """ESTIMATED REGULAR lines of the pole re-rate in place (PRD 3.4/3.5)."""
    lines = [l for l in store.billing_lines.values()
             if l["pole_id"] == pole["id"] and l["line_type"] == "REGULAR" and l["status"] == "ESTIMATED"]
    lines.sort(key=lambda l: (l["period"], l["_seq"]))
    for line in lines:
        calc = monthly_charge(pole, line["period"])
        if calc is None:
            continue
        if (line["charge_cents"] != calc["charge_cents"]
                or line["billing_wattage"] != calc["billing_wattage"]
                or line["tier"] != calc["tier"]
                or line["rate_schedule_id"] != calc["rate_schedule_id"]):
            line["charge_cents"] = calc["charge_cents"]
            line["billing_wattage"] = calc["billing_wattage"]
            line["tier"] = calc["tier"]
            line["rate_schedule_id"] = calc["rate_schedule_id"]
            touch(line)


def audit_retroactive_adjustment(pole):
    """PRD 3.2: walk the pole's lines period ASC, created_at ASC within a period.
    ESTIMATED REGULAR recompute in place; BILLED REGULAR supersede + signed-delta
    ADJUSTMENT when the recomputed charge differs."""
    lines = [l for l in store.billing_lines.values()
             if l["pole_id"] == pole["id"] and l["line_type"] == "REGULAR"
             and l["status"] in ("ESTIMATED", "BILLED")]
    lines.sort(key=lambda l: (l["period"], l["_seq"]))
    for line in lines:
        calc = monthly_charge(pole, line["period"])
        if calc is None:
            continue
        if line["status"] == "ESTIMATED":
            if (line["charge_cents"] != calc["charge_cents"]
                    or line["billing_wattage"] != calc["billing_wattage"]
                    or line["tier"] != calc["tier"]
                    or line["rate_schedule_id"] != calc["rate_schedule_id"]):
                line["charge_cents"] = calc["charge_cents"]
                line["billing_wattage"] = calc["billing_wattage"]
                line["tier"] = calc["tier"]
                line["rate_schedule_id"] = calc["rate_schedule_id"]
                touch(line)
        else:  # BILLED
            delta = calc["charge_cents"] - line["charge_cents"]
            if delta != 0:
                line["status"] = "SUPERSEDED"
                touch(line)
                new_record("billing_lines", {
                    "account_id": line["account_id"],
                    "pole_id": line["pole_id"],
                    "rate_schedule_id": calc["rate_schedule_id"],
                    "period": line["period"],
                    "line_type": "ADJUSTMENT",
                    "billing_wattage": calc["billing_wattage"],
                    "tier": calc["tier"],
                    "charge_cents": delta,
                    "supersedes_line_id": line["id"],
                    "status": "BILLED",
                })


# ---------------------------------------------------------------------------
# Account computed totals (PRD 3.5)
# ---------------------------------------------------------------------------

def account_current_period_estimated(account) -> int:
    return sum(l["charge_cents"] for l in store.billing_lines.values()
               if l["account_id"] == account["id"]
               and l["period"] == account["current_period"]
               and l["line_type"] == "REGULAR" and l["status"] == "ESTIMATED")


def account_ytd_billed(account) -> int:
    year = account["current_period"][:4]
    total = 0
    for l in store.billing_lines.values():
        if l["account_id"] != account["id"] or not l["period"].startswith(year):
            continue
        if l["line_type"] == "REGULAR" and l["status"] in ("BILLED", "SUPERSEDED"):
            total += l["charge_cents"]
        elif l["line_type"] == "ADJUSTMENT":
            total += l["charge_cents"]
    return total


# ---------------------------------------------------------------------------
# Work-order labor costing (PRD 3.4) — ISO-week overtime
# ---------------------------------------------------------------------------

def estimate_labor_cents(crew, stop_minutes: int) -> int:
    return rhu_int(crew["hourly_rate_cents"] * stop_minutes, 60)


def _wo_sort_key(wo):
    """completed_at ASC, then route.window_start_date ASC (nulls after dated),
    then stop.sequence_number ASC; replacements order among themselves by
    their ticket's creation; final tiebreak is insertion order."""
    route = store.routes.get(wo["route_id"]) if wo["route_id"] else None
    window = route["window_start_date"] if route else None
    stop = store.stops.get(wo["stop_id"]) if wo["stop_id"] else None
    seq = stop["sequence_number"] if stop else None
    ticket = store.tickets.get(wo["ticket_id"]) if wo["ticket_id"] else None
    ticket_seq = ticket["_seq"] if ticket else None
    return (
        wo["_completed_dt"],
        window is None,
        window or "",
        seq is None,
        seq if seq is not None else 0,
        ticket_seq if ticket_seq is not None else 0,
        wo["_seq"],
    )


def compute_labor_cost(wo, crew, completed_dt: datetime):
    """Return (labor_cost_cents, cumulative_week_minutes_before, overtime_minutes)."""
    d = completed_dt.date()
    monday = d - timedelta(days=d.weekday())
    week_start = datetime.combine(monday, time(0, 0, 0), tzinfo=timezone.utc)
    week_end = week_start + timedelta(days=7)
    peers = [o for o in store.work_orders.values()
             if o["crew_id"] == crew["id"]
             and o["execution_status"] == "COMPLETED"
             and o.get("_completed_dt") is not None
             and week_start <= o["_completed_dt"] < week_end]
    peers.sort(key=_wo_sort_key)
    prev = 0
    for o in peers:
        if o["id"] == wo["id"]:
            break
        prev += o["stop_minutes"]
    m = wo["stop_minutes"]
    rate = crew["hourly_rate_cents"]
    if prev >= WEEKLY_OVERTIME_MINUTES:
        normal, excess = 0, m
    elif prev + m > WEEKLY_OVERTIME_MINUTES:
        excess = prev + m - WEEKLY_OVERTIME_MINUTES
        normal = m - excess
    else:
        normal, excess = m, 0
    labor = rhu_int(rate * normal, 60) + int(
        (Decimal(rate) * OVERTIME_MULTIPLIER * excess / Decimal(60)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
    return labor, prev, excess


# ---------------------------------------------------------------------------
# Salvage settlement (PRD 3.7) — pinned evaluation order
# ---------------------------------------------------------------------------

def salvage_settlement_value(batch) -> int:
    items = [i for i in store.salvage_items.values() if i["batch_id"] == batch["id"]]
    subtotal = 0
    for cls in ("COBRA_HEAD", "FLOOD", "POST_TOP", "DECORATIVE"):
        class_items = [i for i in items if i["fixture_class"] == cls]
        class_weight = sum((Decimal(str(i["weight_lbs"])) for i in class_items), Decimal(0))
        class_value = (class_weight * PRICE_PER_LB_CENTS[cls]).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
        mercury_count = sum(1 for i in class_items if i["mercury_flag"])
        class_value = int(class_value) - MERCURY_DEDUCTION_CENTS * mercury_count
        subtotal += max(0, class_value)
    if batch["contaminated_flag"]:
        deduction = int((Decimal(subtotal) * CONTAMINATION_RATE).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))
        subtotal -= deduction
    return max(0, subtotal - TRANSPORT_FEE_CENTS)


# ---------------------------------------------------------------------------
# Savings verification (PRD 3.8)
# ---------------------------------------------------------------------------

def compute_report_kwh(program_id, period, method):
    """Return (baseline_kwh, actual_kwh, savings_kwh) as 3-dp Decimals.
    Per-pole quantities are rounded half-up to 3 decimals BEFORE summation."""
    p_start, p_end, D = period_bounds(period)
    B = BURN_HOURS[period[5:7]]
    baseline = Decimal(0)
    actual = Decimal(0)
    for pole in poles_of_program(program_id):
        if pole["led_in_service_date"] is None:
            continue
        isd = parse_date(pole["led_in_service_date"])
        if isd > p_end:
            continue
        if pole["status"] not in ("CONVERTED", "REWORK", "VERIFIED", "UNDER_REPAIR"):
            continue
        pre = pole["pre_conversion_wattage"]
        led = pole["led_wattage"]
        base_p = (Decimal(pre) * B / Decimal(1000)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        if method == "ENGINEERING_ESTIMATE":
            act_p = (Decimal(led) * B / Decimal(1000)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        else:  # METERED_ACTUAL
            if isd >= p_start:
                d_new = (p_end - isd).days + 1
            else:
                d_new = D
            d_old = D - d_new
            blended = (Decimal(pre) * B * d_old / D + Decimal(led) * B * d_new / D) / Decimal(1000)
            act_p = blended.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        baseline += base_p
        actual += act_p
    savings = (baseline - actual).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return baseline, actual, savings


def compute_raw_credit(savings_kwh: Decimal, rebate_cents_per_kwh: int) -> int:
    return int((savings_kwh * rebate_cents_per_kwh).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fill_report_computed(report, program):
    baseline, actual, savings = compute_report_kwh(
        report["program_id"], report["period"], report["method"])
    report["baseline_kwh"] = float(baseline)
    report["actual_kwh"] = float(actual)
    report["savings_kwh"] = float(savings)
    report["raw_credit_cents"] = compute_raw_credit(savings, program["rebate_cents_per_kwh"])


# ---------------------------------------------------------------------------
# Ticket SLA (PRD 3.6)
# ---------------------------------------------------------------------------

def compute_ticket_priority(ticket, pole, district) -> str:
    if ticket["hazard_flag"]:
        return "CRITICAL"
    tier = tier_of(pole_billing_wattage(pole))
    if district["zone"] == "ARTERIAL" and tier in ("T4", "T5"):
        return "CRITICAL"
    if district["zone"] == "ARTERIAL" or tier in ("T3", "T4", "T5"):
        return "HIGH"
    return "STANDARD"


def escalate_priority(priority: str) -> str:
    return {"STANDARD": "HIGH", "HIGH": "CRITICAL", "CRITICAL": "CRITICAL"}[priority]


# ---------------------------------------------------------------------------
# Serializers (computed fields resolved at read time)
# ---------------------------------------------------------------------------

def ser_program(p):
    out = public(p)
    out["current_billing_run_estimated_cents"] = sum(
        account_current_period_estimated(a) for a in accounts_of_program(p["id"]))
    out["converted_pole_count"] = sum(
        1 for pole in poles_of_program(p["id"]) if pole["led_in_service_date"] is not None)
    out["pending_salvage_item_count"] = sum(
        1 for i in store.salvage_items.values()
        if i["batch_id"] is None
        and ((store.districts.get((store.poles.get(i["pole_id"]) or {}).get("district_id")) or {})
             .get("program_id") == p["id"]))
    return out


def ser_district(d):
    return public(d)


def ser_pole(p):
    out = public(p)
    out["billing_wattage"] = pole_billing_wattage(p)
    out["wattage_tier"] = tier_of(out["billing_wattage"])
    return out


def ser_audit(a):
    return public(a)


def ser_crew(c):
    return public(c)


def ser_route(r):
    out = public(r)
    out["stop_count"] = route_stop_count(r)
    out["blocked_stop_count"] = route_blocked_count(r)
    out["total_workload_minutes"] = route_total_workload(r)
    out["required_shifts"] = route_required_shifts(r)
    return out


def ser_stop(s):
    return public(s)


def ser_work_order(o):
    return public(o)


def ser_rate_schedule(s):
    return public(s)


def ser_account(a):
    out = public(a)
    out["current_period_estimated_cents"] = account_current_period_estimated(a)
    out["ytd_billed_cents"] = account_ytd_billed(a)
    return out


def ser_billing_line(l):
    return public(l)


def ser_ticket(t):
    return public(t)


def batch_item_count(batch) -> int:
    return sum(1 for i in store.salvage_items.values() if i["batch_id"] == batch["id"])


def batch_total_weight(batch) -> float:
    total = sum((Decimal(str(i["weight_lbs"])) for i in store.salvage_items.values()
                 if i["batch_id"] == batch["id"]), Decimal(0))
    return float(total.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def ser_batch(b):
    out = public(b)
    out["item_count"] = batch_item_count(b)
    out["total_weight_lbs"] = batch_total_weight(b)
    return out


def ser_salvage_item(i):
    out = public(i)
    out["weight_lbs"] = float(Decimal(str(i["weight_lbs"])))
    return out


def ser_report(r):
    return public(r)


def ser_exception(e):
    return public(e)
