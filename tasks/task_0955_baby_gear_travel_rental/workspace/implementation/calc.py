"""Calculation rules (scaffold section 1.3). Rounding order is pinned exactly
as specified: round at the point each factor is applied, then integer-sum."""
from datetime import timedelta

from db import store
from util import D, ceil_div_pos, midnight, rhu

# ---- provisional_quote constants ----
DELIVERY_TIER1_LIMIT = 10000   # subtotal < 10000 -> 2500
DELIVERY_TIER2_LIMIT = 30000   # 10000..29999 -> 1500; >= 30000 -> 0
DELIVERY_FEE_T1 = 2500
DELIVERY_FEE_T2 = 1500
DELIVERY_FEE_T3 = 0
SETUP_FEE_CENTS = 1500
TIER1_DAYS = 6
TIER2_DAYS = 13

# ---- late_fee constants ----
GRACE_MINUTES = 240
HOURLY_LATE_FACTOR = "0.15"
LATE_FEE_CAP_DAYS = 2

# ---- extension_charge constants ----
EXT_TIER1_DAYS = 2

# ---- deposit_hold constants ----
RISK_MULTIPLIER_THRESHOLD = 70

# ---- customer_risk_score constants ----
LATE_WEIGHT = 15
DAMAGE_WEIGHT = 25
SUSPEND_THRESHOLD = 90
SCORE_CAP = 100

ELIGIBLE_STATUSES = ("AVAILABLE", "RESERVED", "RENTED_OUT")
GRADE_RANK = {"A": 0, "B": 1, "C": 2}
SEVERITY_FACTOR = {"COSMETIC": "0.25", "MINOR": "0.60", "MAJOR": "1.00"}
GRADE_FACTOR = {"A": "1.0", "B": "0.8", "C": "0.6"}


def billable_days(start_d, end_d):
    """end_date exclusive; minimum one billable day."""
    return max(1, (end_d - start_d).days)


def tiered_line_charge(rate, days):
    """Marginal tiers: days 1-6 at 100%, days 7-13 at 85% (per-day rate rounded
    half-up), days >= 14 at 70% (per-day rate rounded half-up)."""
    t1 = rate * min(days, TIER1_DAYS)
    t2 = rhu(D(rate) * D("0.85")) * max(0, min(days, TIER2_DAYS) - TIER1_DAYS)
    t3 = rhu(D(rate) * D("0.70")) * max(0, days - TIER2_DAYS)
    return t1 + t2 + t3


def insurance_premium(plan, gear_subtotal, days):
    if plan is None:
        return 0
    if plan["pricing_model"] == "PER_DAY":
        return rhu(plan["rate_value"]) * days
    return rhu(D(gear_subtotal) * D(plan["rate_value"]))


def compute_quote(res, lines):
    """Pinned evaluation order: gear subtotal -> delivery fee on the SUBTOTAL
    alone -> flat setup fee -> insurance premium -> quoted total."""
    days = billable_days(res["start_date"], res["end_date"])
    gear = 0
    for line in lines:
        item = store.catalog_items[line["catalog_item_id"]]
        charge = tiered_line_charge(item["daily_rate_cents"], days)
        line["line_charge_cents"] = charge
        gear += charge
    if gear < DELIVERY_TIER1_LIMIT:
        delivery = DELIVERY_FEE_T1
    elif gear < DELIVERY_TIER2_LIMIT:
        delivery = DELIVERY_FEE_T2
    else:
        delivery = DELIVERY_FEE_T3
    plan = store.plans.get(res["insurance_plan_id"]) if res["insurance_plan_id"] else None
    premium = insurance_premium(plan, gear, days)
    res["gear_subtotal_cents"] = gear
    res["quoted_total_cents"] = gear + delivery + SETUP_FEE_CENTS + premium


def committed_interval(item, res):
    """[start_dateT00:00Z, end_dateT00:00Z + cleaning_turnaround_hours)."""
    ci_start = midnight(res["start_date"])
    ci_end = midnight(res["end_date"]) + timedelta(hours=item["cleaning_turnaround_hours"])
    return ci_start, ci_end


def _overlaps(s1, e1, s2, e2):
    """Half-open overlap: a window ending exactly where another begins does not overlap."""
    return s1 < e2 and s2 < e1


def unit_has_committed_overlap(unit, s_dt, e_dt, exclude_reservation_id=None):
    """Any CONFIRMED/DELIVERED reservation holding a line assigned to this unit
    whose committed interval (buffered, half-open) overlaps [s_dt, e_dt)."""
    item = store.catalog_items[unit["catalog_item_id"]]
    for line in store.lines.values():
        if line["assigned_unit_id"] != unit["id"]:
            continue
        res = store.reservations.get(line["reservation_id"])
        if res is None or res["status"] not in ("CONFIRMED", "DELIVERED"):
            continue
        if exclude_reservation_id and res["id"] == exclude_reservation_id:
            continue
        ci_start, ci_end = committed_interval(item, res)
        if _overlaps(s_dt, e_dt, ci_start, ci_end):
            return True
    return False


def unit_eligible(unit, s_dt, e_dt, taken=None, exclude_reservation_id=None):
    if unit["status"] not in ELIGIBLE_STATUSES:
        return False
    if taken and unit["id"] in taken:
        return False
    bu = unit["blocked_until"]
    if bu is not None and bu > s_dt:
        return False
    return not unit_has_committed_overlap(unit, s_dt, e_dt, exclude_reservation_id)


def rank_units(units):
    """Selector ranking: condition_grade A > B > C, ties by created_at ASC."""
    return sorted(units, key=lambda u: (GRADE_RANK[u["condition_grade"]], u["_ord"]))


def item_under_active_mandatory_recall(item_id):
    return any(r["catalog_item_id"] == item_id and r["status"] == "ACTIVE"
               and r["severity"] == "MANDATORY" for r in store.recalls.values())


def deposit_hold(customer, lines):
    """Per-unit round_half_up(deposit x multiplier), THEN sum (order pinned)."""
    mult = D("1.5") if customer["risk_score"] >= RISK_MULTIPLIER_THRESHOLD else D("1.0")
    total = 0
    for line in lines:
        item = store.catalog_items[line["catalog_item_id"]]
        total += rhu(D(item["deposit_amount_cents"]) * mult)
    return total


def late_fee(res, lines):
    """Returns (late_fee_cents, late_minutes). Exactly GRACE_MINUTES late is
    free; one minute over bills a full first hour."""
    due_at = midnight(res["end_date"])
    returned_at = res["returned_at"]
    late_minutes = max(0, int((returned_at - due_at).total_seconds() // 60))
    total = 0
    if late_minutes > GRACE_MINUTES:
        billable_hours = ceil_div_pos(late_minutes - GRACE_MINUTES, 60)
        for line in lines:
            if line["status"] != "RETURNED":
                continue
            rate = line["unit_rate_cents"]
            hourly = max(1, rhu(D(rate) * D(HOURLY_LATE_FACTOR)))
            total += min(billable_hours * hourly, LATE_FEE_CAP_DAYS * rate)
    return total, late_minutes


def extension_charge(lines, ext_days):
    """Per allocated line: days 1-2 at 120% of unit_rate (rounded half-up per
    day-rate), days >= 3 at 150%; summed."""
    total = 0
    for line in lines:
        if line["status"] not in ("ALLOCATED", "OUT"):
            continue
        r = line["unit_rate_cents"]
        total += (rhu(D(r) * D("1.20")) * min(ext_days, EXT_TIER1_DAYS)
                  + rhu(D(r) * D("1.50")) * max(0, ext_days - EXT_TIER1_DAYS))
    return total


def damage_capture_amount(claim, line):
    res = store.reservations[line["reservation_id"]]
    unit = store.units.get(line["assigned_unit_id"])
    item = store.catalog_items[line["catalog_item_id"]]
    grade_factor = D(GRADE_FACTOR[unit["condition_grade"]]) if unit else D("1.0")
    if claim["severity"] == "TOTAL_LOSS":
        base = item["deposit_amount_cents"]   # replacement cost; repair_cost ignored
        sev = D("1.0")                        # TOTAL_LOSS is not severity-scaled
    else:
        base = claim["repair_cost_cents"]
        sev = D(SEVERITY_FACTOR[claim["severity"]])
    charged = rhu(D(base) * sev * grade_factor)
    plan = store.plans.get(res["insurance_plan_id"]) if res["insurance_plan_id"] else None
    if plan and claim["severity"] in plan["covered_severities"]:
        return min(charged, plan["deductible_cents"]) + max(0, charged - plan["coverage_cap_cents"])
    return charged


def cancellation_fee(quoted_total_cents):
    return rhu(D(quoted_total_cents) * D("0.10"))


def hotel_commission(res, lines):
    """Per-line round half-up, THEN sum (order pinned)."""
    if not res["hotel_partner_id"]:
        return 0
    partner = store.partners[res["hotel_partner_id"]]
    pct = D(partner["commission_pct"])
    return sum(rhu(D(line["line_charge_cents"]) * pct) for line in lines)


def risk_score(customer):
    return min(SCORE_CAP,
               LATE_WEIGHT * customer["late_return_count"]
               + DAMAGE_WEIGHT * customer["captured_damage_count"])


def availability_count(item_id, start_d, end_d):
    s_dt, e_dt = midnight(start_d), midnight(end_d)
    return sum(1 for u in store.units.values()
               if u["catalog_item_id"] == item_id and unit_eligible(u, s_dt, e_dt))


def stop_weight(res):
    """Sum of gear weight over the reservation's non-cancelled lines."""
    w = 0.0
    for line in store.lines.values():
        if line["reservation_id"] != res["id"] or line["status"] == "CANCELLED":
            continue
        w += float(store.catalog_items[line["catalog_item_id"]]["weight_kg"])
    return w


def recompute_route_weight(route):
    """Stops in {SCHEDULED, COMPLETED} contribute; FAILED/SKIPPED contribute 0."""
    total = 0.0
    for stop in store.stops.values():
        if stop["route_id"] == route["id"] and stop["status"] in ("SCHEDULED", "COMPLETED"):
            total += stop_weight(store.reservations[stop["reservation_id"]])
    route["planned_weight_kg"] = round(total, 6)


def resequence_stops(route_id):
    """Non-SKIPPED stops numbered from 1: time_window_start ASC, ties by
    created_at ASC (never by id)."""
    stops = [s for s in store.stops.values()
             if s["route_id"] == route_id and s["status"] != "SKIPPED"]
    stops.sort(key=lambda s: (s["time_window_start_dt"], s["_ord"]))
    for i, s in enumerate(stops, 1):
        s["sequence"] = i
