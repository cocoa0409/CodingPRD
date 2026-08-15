"""Calculation rules (scaffold table 3) with pinned constants, evaluation
order, precision, and rounding. All rounding is round-half-up. Money uses
integer cents via Decimal; never bare float arithmetic for money.
"""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import db, now, touch

# Pinned constants
ML_PER_GAL = 3785.411
MINUTES_PER_DAY = 1440
BASELINE_COC = 3.0
ESCALATION_THRESHOLD = 3
WINDOW_DAYS = 7
DEPLETION_ALERT_DAYS = 14
MPY_CONSTANT = 22300
RELIABLE_MIN_DAYS = 30
REPASSIVATION_BUFFER_DAYS = 7
TDS_CONDUCTIVITY_FACTOR = 0.7
SCALE_THRESHOLD = 2.5
CORROSIVE_THRESHOLD = -2.5
INVOICE_OVERDUE_DAYS = 30
DELINQUENCY_GRACE_DAYS = 14
SECONDS_PER_DAY = 86400
COUPON_DEPOSIT_ALLOWANCE_G = 2.0


def round_places(x, places):
    """Round half up to the given number of decimal places; returns float."""
    q = Decimal(1).scaleb(-places)
    v = Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP)
    return float(v) + 0.0


def round_cents(x):
    """Round half up to whole cents; returns int. Accepts float or Decimal."""
    if not isinstance(x, Decimal):
        x = Decimal(repr(float(x)))
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# 1. LSI (dual variant)
# ---------------------------------------------------------------------------

def compute_lsi(ph, tds_ppm, calcium_ppm, alkalinity_ppm, temperature_f):
    """Intermediate terms held at full double precision; store 2dp half-up."""
    A = (math.log10(tds_ppm) - 1) / 10
    temperature_c = (temperature_f - 32) * 5 / 9
    B = -13.12 * math.log10(temperature_c + 273) + 34.55
    C = math.log10(calcium_ppm) - 0.4
    D = math.log10(alkalinity_ppm)
    pHs = (9.3 + A + B) - (C + D)
    return round_places(ph - pHs, 2)


def classify_lsi(lsi):
    if lsi >= SCALE_THRESHOLD:
        return "SCALE_FORMING"
    if lsi <= CORROSIVE_THRESHOLD:
        return "CORROSIVE"
    return "BALANCED"


def lsi_provisional(ph, conductivity_umhos, calcium_ppm, alkalinity_ppm, temperature_f):
    return compute_lsi(ph, conductivity_umhos * TDS_CONDUCTIVITY_FACTOR,
                       calcium_ppm, alkalinity_ppm, temperature_f)


def lsi_finalized(ph, lab_tds_ppm, calcium_ppm, alkalinity_ppm, temperature_f):
    return compute_lsi(ph, lab_tds_ppm, calcium_ppm, alkalinity_ppm, temperature_f)


# ---------------------------------------------------------------------------
# 2. Feed-rate setpoint: pinned order evaporation -> drift -> blowdown ->
#    mode branch -> clamp. Stored 4dp half-up.
# ---------------------------------------------------------------------------

def feed_rate_setpoint(asset, accepted_design, product, station):
    evaporation_gpm = asset["recirculation_rate_gpm"] * asset["evaporation_factor"]
    drift_gpm = asset["recirculation_rate_gpm"] * asset["drift_factor"]
    blowdown_gpm = max(0.0, evaporation_gpm / (asset["target_coc"] - 1) - drift_gpm)
    inhibitor = accepted_design["inhibitor_target_ppm"]
    active_pct = product["active_pct"]
    if station["feed_mode"] == "CONTINUOUS":
        raw = inhibitor * blowdown_gpm * ML_PER_GAL / (active_pct * 100)
    else:  # SHOT_FEED: whole day's dose as one daily shot
        raw = (inhibitor * blowdown_gpm * ML_PER_GAL * MINUTES_PER_DAY
               / (active_pct * 100) / MINUTES_PER_DAY)
    setpoint = min(station["capacity_cap_ml_per_min"], max(0.0, raw))
    return round_places(setpoint, 4)


def accepted_design_of(asset_id):
    designs = [d for d in db["program_designs"].values()
               if d["asset_id"] == asset_id and d["status"] == "ACCEPTED"]
    if not designs:
        return None
    designs.sort(key=lambda d: d["_seq"])
    return designs[-1]


# ---------------------------------------------------------------------------
# 3. Inventory & depletion projection (trailing 7-day half-open window)
# ---------------------------------------------------------------------------

def station_orders(station_id):
    return [o for o in db["delivery_orders"].values() if o["station_id"] == station_id]


def station_readings(station_id):
    rs = [r for r in db["telemetry_readings"].values() if r["station_id"] == station_id]
    # recorded_at ASC, tie-break created_at ASC (never id); stable on _seq.
    rs.sort(key=lambda r: (r["recorded_at"], r["created_at"], r["_seq"]))
    return rs


def recompute_station(station, bump=True):
    """Recompute consumption rate, inventory, depletion projection. Stores
    rate to 4dp half-up; projection to whole seconds; null while rate is 0."""
    current = now()
    readings = station_readings(station["id"])
    window_start = current - timedelta(days=WINDOW_DAYS)
    window = [r for r in readings
              if window_start <= r["recorded_at"] < current]
    if window:
        consumed_window = sum(r["feed_pulses"] * r["ml_per_pulse"] for r in window) / ML_PER_GAL
        rate = round_places(consumed_window / WINDOW_DAYS, 4)
    else:
        rate = 0
    lifetime_consumed = (sum(r["feed_pulses"] * r["ml_per_pulse"] for r in readings)
                         / ML_PER_GAL) if readings else 0.0
    delivered = sum(o["delivered_gal"] or 0 for o in station_orders(station["id"])
                    if o["status"] in ("DELIVERED", "CLOSED"))
    returned = sum(o["returned_residual_gal"] or 0 for o in station_orders(station["id"])
                   if o["status"] == "CLOSED")
    inventory = delivered - returned - lifetime_consumed
    if rate == 0:
        projection = None
    else:
        projection = (current + timedelta(days=inventory / rate)).replace(microsecond=0)

    changed = (station["consumption_rate_gal_per_day"] != rate
               or station["inventory_gal"] != inventory
               or station["projected_depletion_at"] != projection)
    station["consumption_rate_gal_per_day"] = rate
    station["inventory_gal"] = inventory
    station["projected_depletion_at"] = projection
    if changed and bump:
        touch(station)
    return station


def depletion_alert(station):
    """True when the projection lands within 14 days of the clock (inclusive)."""
    projection = station["projected_depletion_at"]
    if projection is None:
        return False
    return projection <= now() + timedelta(days=DEPLETION_ALERT_DAYS)


# ---------------------------------------------------------------------------
# 4. Cycles & water balance (pinned evaluation order)
# ---------------------------------------------------------------------------

def blowdown_calc(asset, window_start_ts, occurred_at, blowdown_gal, makeup_gal):
    window_minutes = (occurred_at - window_start_ts).total_seconds() / 60.0
    evaporation_gal = asset["recirculation_rate_gpm"] * asset["evaporation_factor"] * window_minutes
    drift_gal = asset["recirculation_rate_gpm"] * asset["drift_factor"] * window_minutes
    achieved_coc = makeup_gal / (blowdown_gal + drift_gal)
    balance_residual_gal = round_places(makeup_gal - evaporation_gal - blowdown_gal - drift_gal, 2)
    baseline_blowdown_gal = evaporation_gal / (BASELINE_COC - 1) - drift_gal
    saved_gal = max(0.0, baseline_blowdown_gal - blowdown_gal)
    return {
        "evaporation_gal": round_places(evaporation_gal, 2),
        "drift_gal": drift_gal,
        "achieved_coc": achieved_coc,
        "balance_residual_gal": balance_residual_gal,
        "baseline_blowdown_gal": baseline_blowdown_gal,
        "saved_gal": round_places(saved_gal, 2),
    }


# ---------------------------------------------------------------------------
# 5. Coupon corrosion rate (mpy, 3dp half-up)
# ---------------------------------------------------------------------------

def coupon_corrosion(pre_weight_g, post_weight_g, density_g_cm3, area_in2, exposure_days):
    weight_loss_g = pre_weight_g - post_weight_g
    mpy = (weight_loss_g * MPY_CONSTANT) / (density_g_cm3 * area_in2 * exposure_days)
    return round_places(mpy, 3)


def coupon_rating(exposure_days):
    return "RELIABLE" if exposure_days >= RELIABLE_MIN_DAYS else "UNRELIABLE"


# ---------------------------------------------------------------------------
# 6. Invoice pricing: per-line round half up to whole cents FIRST, then sum.
# ---------------------------------------------------------------------------

def invoice_pricing(account, invoice):
    lines = [o for o in db["delivery_orders"].values()
             if o["account_id"] == account["id"]
             and o["status"] in ("DELIVERED", "CLOSED")
             and o["scheduled_for"] is not None
             and invoice["period_start"] <= o["scheduled_for"] < invoice["period_end"]]
    lines.sort(key=lambda o: o["_seq"])
    variant = account["billing_model"]
    product_charges = 0
    for order in lines:
        station = db["feed_stations"][order["station_id"]]
        product = db["products"][station["product_id"]]
        price = (product["unit_price_cents_per_gal"] if variant == "PRODUCT"
                 else product["contract_price_cents_per_gal"])
        line_cents = round_cents(Decimal(repr(float(order["delivered_gal"]))) * price)
        product_charges += line_cents
    service_fee = 0
    if variant == "SERVICE_CONTRACT" and lines:
        first_station = db["feed_stations"][lines[0]["station_id"]]
        design = accepted_design_of(first_station["asset_id"])
        if design is not None:
            service_fee = design["service_rate_cents_per_month"]
    return variant, product_charges, service_fee, product_charges + service_fee


# ---------------------------------------------------------------------------
# Posture: derived parallel dimension. FROZEN > NON_COMPLIANT > WATCH > COMPLIANT.
# ---------------------------------------------------------------------------

def asset_plans(asset_id):
    return [p for p in db["legionella_plans"].values() if p["asset_id"] == asset_id]


def compute_posture(asset):
    account = db["accounts"].get(asset["account_id"])
    plans = asset_plans(asset["id"])
    if (account is not None and account["status"] == "SUSPENDED") or \
            any(p["status"] == "SUSPENDED" for p in plans):
        return "FROZEN"
    if any(p["status"] == "DELINQUENT" for p in plans):
        return "NON_COMPLIANT"
    if asset["consecutive_out_of_range_count"] >= ESCALATION_THRESHOLD:
        return "NON_COMPLIANT"
    if asset["consecutive_out_of_range_count"] >= 1:
        return "WATCH"
    return "COMPLIANT"


def recompute_posture(asset):
    new_posture = compute_posture(asset)
    if asset["posture"] != new_posture:
        asset["posture"] = new_posture
        touch(asset)
    return asset


# ---------------------------------------------------------------------------
# Clock sweeps (PRD 2.4)
# ---------------------------------------------------------------------------

def run_sweeps(current):
    for plan in db["legionella_plans"].values():
        if plan["status"] == "ACTIVE" and plan["validation_due_at"] is not None \
                and plan["validation_due_at"] <= current:
            plan["status"] = "VALIDATION_DUE"
            touch(plan)
    for inv in db["invoices"].values():
        if inv["status"] == "ISSUED" \
                and current > inv["period_end"] + timedelta(days=INVOICE_OVERDUE_DAYS):
            inv["status"] = "OVERDUE"
            touch(inv)
