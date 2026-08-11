"""Calculation rules (PRD §3, scaffold §1.3). All money math uses Decimal with
round-half-up applied exactly at the points the PRD pins."""
from datetime import timedelta
from decimal import Decimal

from db import store
from util import buffered_conflict, dec, md_of, md_ordinal, rhu

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_RATE = {
    "COOP_CLEANING": 8000,
    "FLOCK_HEALTH_CHECK": 6000,
    "PREDATOR_PROOFING": 12000,
    "SETUP_INSTALL": 25000,
}
ZONE_MULT = {
    "URBAN": Decimal("1.0"),
    "SUBURBAN": Decimal("1.15"),
    "RURAL": Decimal("1.30"),
}
STANDARD_DURATION = {
    "COOP_CLEANING": 60,
    "FLOCK_HEALTH_CHECK": 45,
    "PREDATOR_PROOFING": 90,
    "SETUP_INSTALL": 180,
}
OVERTIME_BLOCK_MINUTES = 15
OVERTIME_BLOCK_FEE_CENTS = 700
DAILY_RATE_CENTS = 5000
TAX_RATE = Decimal("0.0825")
DUE_DAYS = 14
CREDIT_LIMIT_CENTS = 20000
TRAVEL_BUFFER_MINUTES = 30
STOP_DURATION_MINUTES = 60
FREE_NOTICE_HOURS = 72
REDUCED_NOTICE_HOURS = 24
REDUCED_FEE_PCT = Decimal("0.25")
LATE_FEE_PCT = Decimal("0.50")


def flock_tier_fee(n):
    if n <= 6:
        return 0
    if n <= 12:
        return 1500
    if n <= 20:
        return 3000
    return 3000 + 250 * (n - 20)


# ---------------------------------------------------------------------------
# seasonal_surcharge_lookup
# ---------------------------------------------------------------------------
def window_covers(window, md):
    """Wrap-aware inclusive MM-DD coverage."""
    start, end = window["start_md"], window["end_md"]
    if start <= end:
        return start <= md <= end
    return md >= start or md <= end


def seasonal_surcharge_lookup(zone_code, date_dt):
    """Return the single SeasonalWindow covering this zone/date, or None."""
    md = md_of(date_dt)
    for w in store.windows.values():
        if w["zone_code"] == zone_code and window_covers(w, md):
            return w
    return None


def window_ordinal_set(window):
    """Set of covered day-of-year ordinals (leap reference year), wrap-aware."""
    s, e = md_ordinal(window["start_md"]), md_ordinal(window["end_md"])
    if s <= e:
        return set(range(s, e + 1))
    return set(range(s, 366)) | set(range(0, e + 1))


# ---------------------------------------------------------------------------
# Subscription helpers
# ---------------------------------------------------------------------------
def active_subscription(household_id):
    for s in store.subscriptions.values():
        if s["household_id"] == household_id and s["status"] == "ACTIVE":
            return s
    return None


def active_plan(household_id):
    sub = active_subscription(household_id)
    if not sub:
        return None
    return store.plans.get(sub["plan_id"])


# ---------------------------------------------------------------------------
# subscription_coverage_resolution
# ---------------------------------------------------------------------------
def resolve_coverage(household_id, visit_type, scheduled_start):
    """Returns (coverage, subscription_or_None). Strict less-than counters."""
    sub = active_subscription(household_id)
    if sub is None or visit_type in ("PREDATOR_PROOFING", "SETUP_INSTALL"):
        return "BILLABLE", None
    d = scheduled_start.date()
    if not (sub["current_period_start"].date() <= d < sub["current_period_end"].date()):
        return "BILLABLE", None
    plan = store.plans.get(sub["plan_id"])
    if visit_type == "COOP_CLEANING":
        if sub["used_cleanings"] < plan["included_cleanings_per_period"]:
            return "SUBSCRIPTION_COVERED", sub
    elif visit_type == "FLOCK_HEALTH_CHECK":
        if sub["used_health_checks"] < plan["included_health_checks_per_period"]:
            return "SUBSCRIPTION_COVERED", sub
    return "BILLABLE", None


# ---------------------------------------------------------------------------
# visit_provisional_price / visit_final_price
# ---------------------------------------------------------------------------
def _base_component(zone_code, visit_type, on_dt):
    w = seasonal_surcharge_lookup(zone_code, on_dt)
    seasonal_pct = dec(w["visit_surcharge_pct"]) if w else Decimal("0")
    raw = dec(BASE_RATE[visit_type]) * ZONE_MULT[zone_code] * (Decimal("1") + seasonal_pct)
    return rhu(raw)


def visit_provisional_price(household, coop, visit_type, scheduled_start):
    base = _base_component(household["zone_code"], visit_type, scheduled_start)
    return base + flock_tier_fee(coop["coop_capacity_hens"])


def visit_final_price(household, visit, observed_flock_size, actual_duration_minutes):
    base = _base_component(household["zone_code"], visit["visit_type"], visit["completed_at"])
    flock_fee = flock_tier_fee(observed_flock_size)
    overtime_minutes = max(0, actual_duration_minutes - STANDARD_DURATION[visit["visit_type"]])
    overtime_blocks = -(-overtime_minutes // OVERTIME_BLOCK_MINUTES)  # ceil; each STARTED block bills
    overtime_fee = overtime_blocks * OVERTIME_BLOCK_FEE_CENTS
    return base + flock_fee + overtime_fee


# ---------------------------------------------------------------------------
# sitting_quote_price / sitting_final_settlement / sitting_cancellation_fee
# ---------------------------------------------------------------------------
def engagement_nights(engagement):
    return (engagement["end_date"] - engagement["start_date"]).days


def sitting_quote_price(engagement, household):
    nights = engagement_nights(engagement)
    w = seasonal_surcharge_lookup(household["zone_code"], engagement["start_date"])
    sitting_pct = dec(w["sitting_surcharge_pct"]) if w else Decimal("0")
    plan = active_plan(household["id"])
    discount_pct = dec(plan["sitting_discount_pct"]) if plan else Decimal("0")
    raw = dec(nights * DAILY_RATE_CENTS) * (Decimal("1") + sitting_pct) * (Decimal("1") - discount_pct)
    return rhu(raw)


def sitting_final_settlement(engagement, household):
    stops = [s for s in store.stops.values() if s["engagement_id"] == engagement["id"]]
    stops.sort(key=lambda s: (s["planned_start"], s["_seq"]))
    acc = 0
    for s in stops:
        if s["status"] != "DONE":
            continue
        route = store.routes[s["route_id"]]
        w = seasonal_surcharge_lookup(route["zone_code"], s["planned_start"])
        sitting_pct = dec(w["sitting_surcharge_pct"]) if w else Decimal("0")
        acc += rhu(dec(DAILY_RATE_CENTS) * (Decimal("1") + sitting_pct))
    plan = active_plan(household["id"])
    discount_pct = dec(plan["sitting_discount_pct"]) if plan else Decimal("0")
    return rhu(dec(acc) * (Decimal("1") - discount_pct))


def sitting_cancellation_fee(engagement, now_dt):
    """Notice-based fee on cancel from CONFIRMED. Boundaries are exact."""
    notice_hours = (engagement["start_date"] - now_dt).total_seconds() / 3600.0
    if notice_hours >= FREE_NOTICE_HOURS:
        return 0
    if notice_hours >= REDUCED_NOTICE_HOURS:
        return rhu(dec(engagement["quoted_price_cents"]) * REDUCED_FEE_PCT)
    return rhu(dec(engagement["quoted_price_cents"]) * LATE_FEE_PCT)


# ---------------------------------------------------------------------------
# route_assignment_selector / technician_schedule_conflict
# ---------------------------------------------------------------------------
def _route_has_conflict(route, ws, we):
    for s in store.stops.values():
        if s["route_id"] != route["id"] or s["status"] not in ("PENDING", "DONE"):
            continue
        if buffered_conflict(ws, we, s["planned_start"], s["planned_end"], TRAVEL_BUFFER_MINUTES):
            return True
    return False


def route_assignment_selector(zone_code, stop_date, ws, we):
    """Best eligible PUBLISHED route for one stop date, or None."""
    candidates = []
    for r in store.routes.values():
        if r["route_date"].date() != stop_date:
            continue
        if r["zone_code"] != zone_code or r["status"] != "PUBLISHED":
            continue
        if r["committed_stops"] >= r["max_stops"]:
            continue
        if _route_has_conflict(r, ws, we):
            continue
        candidates.append(r)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["committed_stops"], r["created_at"], r["_seq"]))
    return candidates[0]


def technician_schedule_conflict(technician_id, ws, we, exclude_visit_id=None):
    for v in store.visits.values():
        if v["assigned_technician_id"] != technician_id:
            continue
        if v["status"] not in ("SCHEDULED", "ON_SITE"):
            continue
        if exclude_visit_id is not None and v["id"] == exclude_visit_id:
            continue
        if buffered_conflict(ws, we, v["scheduled_start"], v["scheduled_end"], TRAVEL_BUFFER_MINUTES):
            return True
    return False


# ---------------------------------------------------------------------------
# engagement_date_overlap
# ---------------------------------------------------------------------------
def engagement_date_overlap(household_id, new_start, new_end, exclude_id=None):
    """Closed-interval overlap against non-CANCELLED engagements of the household."""
    for e in store.engagements.values():
        if e["household_id"] != household_id or e["status"] == "CANCELLED":
            continue
        if exclude_id is not None and e["id"] == exclude_id:
            continue
        if new_start <= e["end_date"] and new_end >= e["start_date"]:
            return True
    return False


# ---------------------------------------------------------------------------
# supply_order_totals / invoice_total_composition
# ---------------------------------------------------------------------------
def supply_order_totals(order, household):
    subtotal = sum(line["line_total_cents"] for line in order["lines"])
    plan = active_plan(household["id"])
    discount_pct = dec(plan["supply_discount_pct"]) if plan else Decimal("0")
    discount = rhu(dec(subtotal) * discount_pct)  # single rounding on the subtotal
    return subtotal, discount, subtotal - discount


def invoice_total_composition(invoice):
    """Pinned order: lines -> subtotal -> tax -> total."""
    lines = [l for l in store.lines.values() if l["invoice_id"] == invoice["id"]]
    subtotal = sum(l["amount_cents"] for l in lines)
    tax = rhu(dec(subtotal) * TAX_RATE)
    return subtotal, tax, subtotal + tax
