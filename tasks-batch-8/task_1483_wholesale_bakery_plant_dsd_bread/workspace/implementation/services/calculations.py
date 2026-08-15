"""Business calculations: production requirement, stale credit, surcharge,
shrink, thrift pool, sanitation matrix, stale ratio."""

import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import DB


# ---------------------------------------------------------------------------
# order_cutoff_window
# ---------------------------------------------------------------------------

DELIVERY_DAY_START_HOUR_UTC = 8


def delivery_instant(delivery_date_str):
    """delivery_date (YYYY-MM-DD) fixed at 08:00:00Z that day."""
    d = datetime.strptime(delivery_date_str, "%Y-%m-%d").date()
    return datetime(d.year, d.month, d.day, DELIVERY_DAY_START_HOUR_UTC, 0, 0,
                    tzinfo=timezone.utc)


def cutoff_instant(store, delivery_date_str):
    return delivery_instant(delivery_date_str) - timedelta(hours=store["lead_time_hours"])


def clock_at_or_before_cutoff(store, delivery_date_str):
    return DB.clock <= cutoff_instant(store, delivery_date_str)


# ---------------------------------------------------------------------------
# production_requirement
# ---------------------------------------------------------------------------

FLOUR_FRACTION = Decimal("0.60")
TIER1_MAX_UNITS = 1000
TIER2_MAX_UNITS = 5000
TIER1_BUFFER_PCT = Decimal("0.10")
TIER2_BUFFER_PCT = Decimal("0.07")
TIER3_BUFFER_PCT = Decimal("0.05")


def compute_production_requirement(plan):
    """Returns (planned_units_by_product, batches_required_by_product,
    total_planned_units, flour_required_kg)."""
    gross = {}
    for order in DB.store_orders.values():
        if order.get("status") != "LOCKED":
            continue
        if order.get("plant_id") != plan["plant_id"]:
            continue
        if order.get("delivery_date") != plan["bake_date"]:
            continue
        for line in order.get("lines") or []:
            pid = line["product_id"]
            gross[pid] = gross.get(pid, 0) + int(line["qty"])

    planned = {}
    batches_req = {}
    flour_grams_total = Decimal("0")
    total_planned = 0

    for pid, g in gross.items():
        product = DB.products.get(pid)
        if product is None:
            continue
        g_dec = Decimal(g)
        if g < TIER1_MAX_UNITS:
            buffer_pct = TIER1_BUFFER_PCT
        elif g < TIER2_MAX_UNITS:
            buffer_pct = TIER2_BUFFER_PCT
        else:
            buffer_pct = TIER3_BUFFER_PCT
        planned_units = math.ceil(g_dec * (Decimal(1) + buffer_pct))
        planned[pid] = planned_units
        total_planned += planned_units

        cap = int(product["batch_capacity_units"])
        b = math.ceil(planned_units / cap)
        batches_req[pid] = b

        flour_grams_total += (
            Decimal(b) * Decimal(cap) * Decimal(int(product["unit_weight_g"])) * FLOUR_FRACTION
        )

    flour_kg_dec = (flour_grams_total / Decimal(1000)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    flour_required_kg = float(flour_kg_dec)

    return planned, batches_req, total_planned, flour_required_kg


# ---------------------------------------------------------------------------
# sanitation_changeover_minutes
# ---------------------------------------------------------------------------

def sanitation_required_minutes(from_class, to_class):
    if from_class == to_class:
        return 0
    if from_class == "NONE":
        return 30
    if to_class == "NONE":
        return 120
    return 90


# ---------------------------------------------------------------------------
# batch_freshness_window
# ---------------------------------------------------------------------------

def compute_fresh_until(bake_completed_at_dt, shelf_life_hours):
    return bake_completed_at_dt + timedelta(hours=shelf_life_hours)


# ---------------------------------------------------------------------------
# stocking_allocation
# ---------------------------------------------------------------------------

def stocking_allocation(delivered_units, on_shelf_units_observed, shelf_capacity_units):
    room = max(0, shelf_capacity_units - on_shelf_units_observed)
    stocked = min(delivered_units, room)
    refused = delivered_units - stocked
    return stocked, refused


# ---------------------------------------------------------------------------
# stale_credit
# ---------------------------------------------------------------------------

TIER1_MAX_AGE_HOURS = 24
TIER2_MAX_AGE_HOURS = 48
TIER1_RATE = Decimal("1.00")
TIER2_RATE = Decimal("0.50")
TIER3_RATE = Decimal("0.00")
LIMITED_TIER_RATE_CAP = Decimal("0.50")
CREDIT_CAP_CENTS = 50000


def _line_age_hours(pickup_clock_dt, bake_completed_at_dt):
    delta_seconds = (pickup_clock_dt - bake_completed_at_dt).total_seconds()
    return math.floor(delta_seconds / 3600)


def _base_rate(age_hours):
    if age_hours <= TIER1_MAX_AGE_HOURS:
        return TIER1_RATE
    if age_hours <= TIER2_MAX_AGE_HOURS:
        return TIER2_RATE
    return TIER3_RATE


def line_rate(store, age_hours):
    base = _base_rate(age_hours)
    if store.get("stale_credit_tier") == "LIMITED":
        return min(base, LIMITED_TIER_RATE_CAP)
    return base


def compute_stale_credit(store, lines, pickup_clock_dt):
    """lines: [{batch_id, qty}]. Round per line then sum. Returns integer cents."""
    total = Decimal("0")
    for ln in lines:
        batch = DB.batches.get(ln["batch_id"])
        if batch is None or batch.get("bake_completed_at") is None:
            # No bake timestamp -> age undefined; treat rate as 0 contribution.
            continue
        product = DB.products.get(batch["product_id"])
        if product is None:
            continue
        bake_dt = parse_iso_z(batch["bake_completed_at"])
        age = _line_age_hours(pickup_clock_dt, bake_dt)
        rate = line_rate(store, age)
        qty = Decimal(int(ln["qty"]))
        price = Decimal(int(product["base_price_cents"]))
        line_credit = (qty * price * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        total += line_credit
    return int(total)


def parse_iso_z(s):
    """Parse stored ISO Z datetime string back to aware datetime."""
    if s is None:
        return None
    txt = s
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# surcharge_passthrough
# ---------------------------------------------------------------------------

MAX_SURCHARGE_PCT = Decimal("0.15")


def compute_surcharge_cents(product, plant, flour_value, butter_value):
    flour_baseline = Decimal(str(plant["baseline_flour_index"]))
    butter_baseline = Decimal(str(plant["baseline_butter_index"]))
    flour_val = Decimal(str(flour_value))
    butter_val = Decimal(str(butter_value))

    flour_delta = (flour_val - flour_baseline) / flour_baseline
    butter_delta = (butter_val - butter_baseline) / butter_baseline

    surcharge_pct = (
        Decimal(str(product["flour_share_pct"])) * flour_delta
        + Decimal(str(product["butter_share_pct"])) * butter_delta
    )
    if surcharge_pct < Decimal("0"):
        surcharge_pct = Decimal("0")
    if surcharge_pct > MAX_SURCHARGE_PCT:
        surcharge_pct = MAX_SURCHARGE_PCT

    cents = (Decimal(int(product["base_price_cents"])) * surcharge_pct).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(cents)


# ---------------------------------------------------------------------------
# route_settlement_shrink
# ---------------------------------------------------------------------------

SHRINK_TOLERANCE_PCT = Decimal("0.02")
SHRINK_HARD_LIMIT_PCT = Decimal("0.10")
SHRINK_PENALTY_CENTS_PER_UNIT = 150


def compute_route_settlement(route):
    """Returns (delivered, refused, returned_stale, shrink_units, shrink_pct,
    liability_units, shrink_liability_cents)."""
    stops = [s for s in DB.route_stops.values() if s.get("route_id") == route["id"]]
    stops.sort(key=lambda s: (s.get("created_at", ""), s.get("id", "")))

    delivered = 0
    refused = 0
    for s in stops:
        if s.get("status") in ("DELIVERED", "RECONCILED"):
            delivered += int(s.get("delivered_units") or 0)
        refused += int(s.get("refused_units") or 0)

    stop_ids = {s["id"] for s in stops}
    returned_stale = 0
    for r in DB.stale_returns.values():
        if r.get("route_stop_id") in stop_ids and r.get("status") != "REJECTED":
            for ln in r.get("lines") or []:
                returned_stale += int(ln.get("qty", 0))

    loaded = int(route.get("loaded_units") or 0)
    shrink_units = loaded - delivered
    denom = max(1, loaded)
    shrink_pct = Decimal(shrink_units) / Decimal(denom)

    if shrink_pct > SHRINK_TOLERANCE_PCT:
        allowance = math.ceil(Decimal(loaded) * SHRINK_TOLERANCE_PCT)
        liability_units = max(0, shrink_units - allowance)
    else:
        liability_units = 0
    shrink_liability_cents = liability_units * SHRINK_PENALTY_CENTS_PER_UNIT

    return delivered, refused, returned_stale, shrink_units, shrink_pct, liability_units, shrink_liability_cents


# ---------------------------------------------------------------------------
# thrift_stock_pool
# ---------------------------------------------------------------------------

def thrift_pool_available(product_id):
    inflow = 0
    for r in DB.stale_returns.values():
        if r.get("status") not in ("VERIFIED", "DISPUTED", "CREDITED", "REVERSED"):
            continue
        store = DB.stores.get(r.get("store_id"))
        if store is None:
            continue
        pickup_clock_dt = parse_iso_z(r.get("created_at_logical") or r.get("created_at"))
        for ln in r.get("verified_lines") or []:
            batch = DB.batches.get(ln.get("batch_id"))
            if batch is None or batch.get("product_id") != product_id:
                continue
            if batch.get("bake_completed_at") is None:
                continue
            bake_dt = parse_iso_z(batch["bake_completed_at"])
            age = _line_age_hours(pickup_clock_dt, bake_dt)
            rate = line_rate(store, age)
            if rate > 0:
                inflow += int(ln.get("qty", 0))
    outflow = 0
    for sale in DB.thrift_sales.values():
        if sale.get("product_id") == product_id and sale.get("status") == "RECORDED":
            outflow += int(sale.get("units", 0))
    return inflow - outflow


# ---------------------------------------------------------------------------
# store stale ratio
# ---------------------------------------------------------------------------

SUSPENSION_STALE_RATIO = Decimal("0.15")


def compute_stale_ratio(store):
    delivered = int(store.get("lifetime_delivered_units") or 0)
    stale = int(store.get("lifetime_stale_units") or 0)
    denom = max(1, delivered)
    return stale / denom
