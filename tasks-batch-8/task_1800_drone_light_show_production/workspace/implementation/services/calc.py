"""Calculation rules from SCAFFOLD 1.3 / PRD 3."""

from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from db import DB, clock_now, parse_dt


# --------------------------------------------------------------------------
# rounding helpers

def rhu_int(x):
    """Round half up to integer."""
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_1dp(x):
    return float(Decimal(str(x)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def rhu_2dp(x):
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# show_contract_pricing

BASE_FEE_CENTS = 500000
SURCHARGE_TIER_CENTS = 1000000


def show_contract_pricing(drone_count_planned):
    n = drone_count_planned
    drone_fee = (
        2500 * min(n, 100)
        + 2200 * min(max(n - 100, 0), 200)
        + 2000 * max(n - 300, 0)
    )
    subtotal_pre = BASE_FEE_CENTS + drone_fee
    rate = Decimal("0.08") if subtotal_pre >= SURCHARGE_TIER_CENTS else Decimal("0.05")
    surcharge = rhu_int(Decimal(subtotal_pre) * rate)
    contract = subtotal_pre + surcharge
    deposit = rhu_int(Decimal(contract) * Decimal("0.30"))
    balance = contract - deposit
    return contract, deposit, balance


# --------------------------------------------------------------------------
# cancellation_refund

ADMIN_FEE_CENTS = 25000


def cancellation_refund(show, cancelled_at):
    """Return (tier, refund_due_cents)."""
    ws = parse_dt(show["window_start"])
    lead = (ws - cancelled_at).total_seconds() / 3600.0
    paid = show["paid_total_cents"]
    deposit_cents = show["deposit_cents"]
    deposit_paid = min(paid, deposit_cents)
    balance_paid = paid - deposit_paid
    if lead >= 336:
        tier, d_pct, b_pct = "T1_FULL", Decimal("1.00"), Decimal("1.00")
    elif lead >= 168:
        tier, d_pct, b_pct = "T2_DEPOSIT_HALF", Decimal("0.50"), Decimal("1.00")
    elif lead >= 72:
        tier, d_pct, b_pct = "T3_BALANCE_ONLY", Decimal("0.00"), Decimal("1.00")
    else:
        tier, d_pct, b_pct = "T4_HALF_ALL", Decimal("0.50"), Decimal("0.50")
    refund = rhu_int(Decimal(deposit_paid) * d_pct) + rhu_int(Decimal(balance_paid) * b_pct)
    if tier == "T1_FULL":
        refund -= ADMIN_FEE_CENTS
    refund = max(0, refund)
    return tier, refund


# --------------------------------------------------------------------------
# crowd_distance

CROWD_BASE_M = Decimal("40")
ALT_COEFF = Decimal("0.4")
DRONE_COEFF = Decimal("1.2")
CROWD_BUFFER_M = 15


def crowd_required_radius(altitude_ft, drone_count):
    val = CROWD_BASE_M + ALT_COEFF * Decimal(str(altitude_ft)) + DRONE_COEFF * Decimal(str(drone_count))
    return rhu_1dp(val)


def site_min_half_dim(site):
    return min(site["ground_length_m"], site["ground_width_m"]) / 2.0


def crowd_containment(site, altitude_ft, drone_count):
    """Return (required_radius_m, containment)."""
    req = crowd_required_radius(altitude_ft, drone_count)
    half = site_min_half_dim(site)
    containment = "VALID" if (Decimal(str(req)) + Decimal(CROWD_BUFFER_M)) <= Decimal(str(half)) else "INSUFFICIENT"
    return req, containment


# --------------------------------------------------------------------------
# effective_wind_limit

BASE_WIND_KT = Decimal("18")
GUST_FACTOR = Decimal("1.3")


def effective_wind_limits(site, design):
    alt = design["max_altitude_ft"]
    if alt <= 200:
        alt_derate = Decimal("1.0")
    elif alt <= 400:
        alt_derate = Decimal("0.9")
    else:
        alt_derate = Decimal("0.8")
    count = design["drone_count"]
    if count <= 100:
        fleet_derate = Decimal("1.0")
    elif count <= 300:
        fleet_derate = Decimal("0.9")
    else:
        fleet_derate = Decimal("0.8")
    baseline = BASE_WIND_KT * alt_derate * fleet_derate
    eff_wind = rhu_1dp(min(Decimal(str(site["site_max_wind_kt"])), baseline))
    eff_gust = rhu_1dp(Decimal(str(eff_wind)) * GUST_FACTOR)
    return eff_wind, eff_gust


# --------------------------------------------------------------------------
# go_no_go_verdict

LOOKBACK_MINUTES = 60
TEMP_MIN_C = -10
TEMP_MAX_C = 40


def latest_weather_in_window(site_id, end_dt, minutes):
    """Latest WeatherReading for site within [end-minutes, end] inclusive,
    ordered by recorded_at DESC then created_at DESC; creation order breaks
    remaining ties (frozen clock => identical created_at values)."""
    start = end_dt - timedelta(minutes=minutes)
    cands = []
    for idx, rid in enumerate(DB.insertion_order["weather_readings"]):
        r = DB.weather_readings[rid]
        if r["site_id"] != site_id:
            continue
        ra = parse_dt(r["recorded_at"])
        if start <= ra <= end_dt:
            cands.append((idx, r))
    if not cands:
        return None, []
    cands.sort(key=lambda t: (parse_dt(t[1]["recorded_at"]), parse_dt(t[1]["created_at"]), t[0]),
               reverse=True)
    return cands[0][1], [c for _, c in cands]


def go_no_go_verdict(site, design, evaluated_at):
    """Return (verdict, reason_codes, eff_wind, eff_gust)."""
    eff_wind, eff_gust = effective_wind_limits(site, design)
    reading, _ = latest_weather_in_window(site["id"], evaluated_at, LOOKBACK_MINUTES)
    if reading is None:
        return "NO_GO", ["NO_WEATHER_DATA"], eff_wind, eff_gust
    reasons = []
    if reading["wind_speed_kt"] > eff_wind:
        reasons.append("WIND_SUSTAINED_EXCEEDED")
    if reading["gust_kt"] > eff_gust:
        reasons.append("GUST_EXCEEDED")
    if reading["precip_mm_hr"] != 0:
        reasons.append("PRECIPITATION")
    if reading["temperature_c"] < TEMP_MIN_C or reading["temperature_c"] > TEMP_MAX_C:
        reasons.append("TEMPERATURE")
    verdict = "GO" if not reasons else "NO_GO"
    return verdict, reasons, eff_wind, eff_gust


# --------------------------------------------------------------------------
# battery_derated_charge

LAUNCH_MIN_CHARGE_PCT = 85
RECENCY_MINUTES = 120


def battery_derated_charge(drone_charge_pct, site_id):
    """Return effective charge (2dp) using latest reading in 120-min window."""
    now = clock_now()
    latest, _ = latest_weather_in_window(site_id, now, RECENCY_MINUTES)
    if latest is None or latest["temperature_c"] >= 5:
        derate = Decimal("1.0")
    elif latest["temperature_c"] >= -5:
        derate = Decimal("0.85")
    else:
        derate = Decimal("0.70")
    return rhu_2dp(Decimal(str(drone_charge_pct)) * derate)


# --------------------------------------------------------------------------
# simulation_verdict

MAX_SIM_DRAW_PCT = 80
DRONE_MAX_SPEED_MPS = 12.0


def simulation_verdict(design, min_sep_obs, battery_draw_pct, max_speed_mps):
    ok = (
        min_sep_obs >= design["min_separation_m"]
        and battery_draw_pct <= MAX_SIM_DRAW_PCT
        and max_speed_mps <= DRONE_MAX_SPEED_MPS
    )
    return "PASS" if ok else "FAIL"


# --------------------------------------------------------------------------
# show_window_turnaround

TURNAROUND_MINUTES = 120


def show_window_conflict(site_id, new_start, new_end, exclude_show_id=None):
    """True iff another non-CANCELLED/non-POSTPONED show at the site violates
    the 120-minute turnaround buffer vs [new_start, new_end)."""
    buf = timedelta(minutes=TURNAROUND_MINUTES)
    for sid in DB.insertion_order["show_events"]:
        s = DB.show_events[sid]
        if s["id"] == exclude_show_id or s["site_id"] != site_id:
            continue
        if s["lifecycle_status"] in ("CANCELLED", "POSTPONED"):
            continue
        o_start = parse_dt(s["window_start"])
        o_end = parse_dt(s["window_end"])
        if new_start >= o_end + buf or new_end <= o_start - buf:
            continue
        return True
    return False


# --------------------------------------------------------------------------
# authorization_window_overlap


def authorization_window_overlap(site_id, cand_start, cand_end, statuses, exclude_auth_id=None):
    """Half-open overlap vs authorizations in `statuses` whose shows share site."""
    for aid in DB.insertion_order["authorizations"]:
        a = DB.authorizations[aid]
        if a["id"] == exclude_auth_id or a["status"] not in statuses:
            continue
        other_show = DB.show_events.get(a["show_event_id"])
        if other_show is None or other_show["site_id"] != site_id:
            continue
        o_start = parse_dt(a["window_start"])
        o_end = parse_dt(a["window_end"])
        if o_start < cand_end and cand_start < o_end:
            return True
    return False


# --------------------------------------------------------------------------
# flight battery reconciliation constants

CYCLE_LIMIT = 200
DEVIATION_FLAG_M = 5.0
GO_VALIDITY_MINUTES = 240
