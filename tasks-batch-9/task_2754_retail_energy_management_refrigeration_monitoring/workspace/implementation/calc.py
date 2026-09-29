"""The thirteen calculation rules of PRD section 3.

Every rounding step materialises its result at the stated precision before
the next step consumes it (PRD section 2.8).
"""

from decimal import Decimal

import derive
from db import db
from util import D, exact_hours, q, rhu, whole_minutes

# ------------------------------------------------------------- constants -----
RATCHET_FLOOR_FRACTION = Decimal("0.80")
RIDER_RATE = Decimal("0.0375")
SURCHARGE_THRESHOLD_USD = Decimal("20000.00")
SURCHARGE_RATE = Decimal("0.015")
BILL_VARIANCE_TOLERANCE_PCT = Decimal("2.00")

BASELINE_LOOKBACK_INTERVALS = 10
BASELINE_TOP_N = 3

INTERVAL_HOURS = Decimal("0.25")
INCENTIVE_RATE_USD_PER_KWH = Decimal("0.42")
PENALTY_RATE_USD_PER_KWH = Decimal("0.18")
PERFORMANCE_FLOOR_PCT = Decimal("75.0")

DR_OPTOUT_SUSPEND_COUNT = 3
DR_RECOVERY_GAP_MINUTES = 240

GRACE_READINGS = 2
ESCALATE_MINUTES = 120
DISPOSITION_MINUTES = 240

SEVERITY_WEIGHT = {
    "INFO": Decimal(5),
    "MINOR": Decimal(20),
    "MAJOR": Decimal(45),
    "CRITICAL": Decimal(70),
}
PERSISTENCE_STEP = Decimal("0.1")
PERSISTENCE_MAX_OCCURRENCES = 10
LOAD_DIVISOR_KW = Decimal("200.0")
LOAD_FACTOR_CAP = Decimal("1.25")
REFRIGERATION_BONUS = Decimal("15.00")
SCORE_CAP = Decimal("100.0")
WORK_ORDER_URGENT_THRESHOLD = Decimal("70.0")
SUPPRESSION_MAX_SCORE = Decimal("50.0")

OVERRIDE_MAX_HOURS = Decimal(12)

DEFAULT_REALIZATION_RATE = Decimal("0.85")
PAYBACK_PENALTY_PER_YEAR = Decimal(10)
FAULT_DENSITY_BONUS = Decimal(8)
FAULT_DENSITY_CAP = 3
SCORE_MIN = Decimal("0.0")
SCORE_MAX = Decimal("100.0")

CLIMATE_ADJUST = {
    "HOT_HUMID": Decimal("1.08"),
    "HOT_DRY": Decimal("1.05"),
    "MIXED": Decimal("1.00"),
    "MARINE": Decimal("0.96"),
    "COLD": Decimal("0.93"),
}
MV_MIN_PERIOD_DAYS = 60
VERIFY_FLOOR_RATE = Decimal("0.8000")
DAYS_PER_YEAR = Decimal(365)

KWH_TO_KBTU = Decimal("3.412")
TRAILING_WINDOW_DAYS = 365
OUTLIER_MEDIAN_MULTIPLE = Decimal("1.30")

ANNUALIZATION_MONTHS = Decimal(12)
SWITCH_MIN_SAVINGS_USD = Decimal("2500.00")

WORK_ORDER_STORE_CAPACITY = 2


# ------------------------------------------------- period peak demand --------

def period_peak_demand(intervals, rate_family, ratchet_peak_kw):
    """Returns (billable_demand_kw, peak_basis) or (None, basis) when empty."""
    if rate_family == "TOU_DEMAND":
        eligible = [i for i in intervals if i["is_on_peak"]]
        basis = "COINCIDENT_PEAK"
    else:
        eligible = list(intervals)
        basis = "ANYTIME_PEAK"
    if not eligible:
        return None, basis
    ranked = sorted(
        eligible,
        key=lambda i: (-i["kw_demand"], i["interval_start_iso"], i["created_at"], i["_seq"]),
    )
    observed_peak_kw = q(ranked[0]["kw_demand"], 1)
    ratchet_floor_kw = rhu(RATCHET_FLOOR_FRACTION * D(ratchet_peak_kw), 1)
    billable = observed_peak_kw if observed_peak_kw >= ratchet_floor_kw else ratchet_floor_kw
    return q(billable, 1), basis


def period_intervals(account_id, period_start, period_end):
    """Half-open billing window: start <= interval_start < end."""
    return [i for i in derive.account_intervals(account_id)
            if period_start <= i["interval_start_iso"] < period_end]


# ---------------------------------------------------- bill recompute ---------

def bill_recompute(on_peak_kwh, off_peak_kwh, rate_on_peak, rate_off_peak,
                   billable_demand_kw, demand_charge_per_kw):
    """Steps 1 and 3 through 8 of the bill recompute."""
    energy_cost = rhu(D(on_peak_kwh) * D(rate_on_peak)
                      + D(off_peak_kwh) * D(rate_off_peak), 2)
    demand_cost = rhu(D(billable_demand_kw) * D(demand_charge_per_kw), 2)
    base_subtotal = energy_cost + demand_cost
    rider_cost = rhu(base_subtotal * RIDER_RATE, 2)
    pre_surcharge_total = base_subtotal + rider_cost
    if pre_surcharge_total < SURCHARGE_THRESHOLD_USD:
        surcharge = rhu(0, 2)
    else:
        surcharge = rhu((pre_surcharge_total - SURCHARGE_THRESHOLD_USD)
                        * SURCHARGE_RATE, 2)
    total = q(pre_surcharge_total + surcharge, 2)
    return {
        "recomputed_energy_cost_usd": energy_cost,
        "recomputed_demand_cost_usd": demand_cost,
        "recomputed_rider_cost_usd": rider_cost,
        "recomputed_surcharge_usd": surcharge,
        "recomputed_amount_usd": total,
    }


def bill_variance_pct(billed_amount_usd, recomputed_amount_usd):
    return rhu((D(billed_amount_usd) - D(recomputed_amount_usd))
               / D(recomputed_amount_usd) * Decimal(100), 2)


# --------------------------------------------------- demand response ---------

def dr_baseline_kw(account_id, curtailment_start):
    """Recency pass then severity pass; None when no candidate exists."""
    pool = [i for i in derive.account_intervals(account_id)
            if i["is_on_peak"] and not i["is_dr_event_day"]
            and i["interval_start_iso"] < curtailment_start]
    if not pool:
        return None
    recent = sorted(
        pool,
        key=lambda i: (i["interval_start_iso"], i["created_at"], i["_seq"]),
        reverse=True,
    )[:BASELINE_LOOKBACK_INTERVALS]
    ranked = sorted(
        recent,
        key=lambda i: (-i["kw_demand"], i["interval_start_iso"], i["created_at"], i["_seq"]),
    )[:BASELINE_TOP_N]
    total = Decimal(0)
    for interval in ranked:
        total += D(interval["kw_demand"])
    return rhu(total / Decimal(len(ranked)), 2)


def dr_settlement(account_id, event):
    """Returns total_reduction_kwh, target_kwh, performance_pct, incentive, penalty."""
    window = [i for i in derive.account_intervals(account_id)
              if event["curtailment_start_iso"] <= i["interval_start_iso"]
              < event["curtailment_end_iso"]]
    window.sort(key=lambda i: (i["interval_start_iso"], i["created_at"], i["_seq"]))
    baseline = event["baseline_kw"] if event["baseline_kw"] is not None else Decimal(0)
    total = Decimal(0)
    for interval in window:
        delivered = D(baseline) - D(interval["kw_demand"])
        if delivered < 0:
            delivered = Decimal(0)
        total += rhu(delivered * INTERVAL_HOURS, 2)
    total_reduction_kwh = q(total, 2)
    target_kwh = rhu(D(event["target_reduction_kw"]) * INTERVAL_HOURS
                     * Decimal(len(window)), 2)
    if not window or target_kwh == 0:
        performance_pct = rhu(0, 1)
    else:
        performance_pct = rhu(total_reduction_kwh / target_kwh * Decimal(100), 1)
    if performance_pct >= PERFORMANCE_FLOOR_PCT:
        incentive = rhu(total_reduction_kwh * INCENTIVE_RATE_USD_PER_KWH, 2)
        penalty = rhu(0, 2)
    else:
        incentive = rhu(0, 2)
        penalty = rhu((target_kwh - total_reduction_kwh) * PENALTY_RATE_USD_PER_KWH, 2)
    if not window:
        incentive = rhu(0, 2)
        penalty = rhu(0, 2)
    return total_reduction_kwh, target_kwh, performance_pct, incentive, penalty


# --------------------------------------------------------- posture ----------

POSTURE_RANK = {"NORMAL": 0, "CONSTRAINED": 1, "CURTAILED": 2, "LOCKED": 3}


def compute_posture(store):
    store_id = store["id"]
    for excursion in derive.store_excursions(store_id):
        if excursion["state"] in ("ESCALATED", "DISPOSITION_REQUIRED"):
            return "LOCKED"
    for event in derive.store_events(store_id):
        if event["event_state"] == "ACTIVE":
            return "CURTAILED"
    if derive.alarm_case_count(store_id) >= 1:
        return "CONSTRAINED"
    if store["bms_status"] == "DEGRADED":
        return "CONSTRAINED"
    if derive.urgent_work_order_count(store_id) >= 1:
        return "CONSTRAINED"
    return "NORMAL"


# ------------------------------------------------- excursion exposure -------

def breaches(case, temp_f):
    return D(temp_f) >= D(case["alarm_high_f"]) or D(temp_f) <= D(case["alarm_low_f"])


def breach_deviation(case, temp_f):
    high = D(temp_f) - D(case["alarm_high_f"])
    low = D(case["alarm_low_f"]) - D(temp_f)
    return high if high >= low else low


def exposure_minutes(first_breach, last_breach):
    return whole_minutes(first_breach, last_breach)


def exposure_ladder(minutes):
    if minutes >= DISPOSITION_MINUTES:
        return "DISPOSITION_REQUIRED", "DISCARD"
    if minutes >= ESCALATE_MINUTES:
        return "ESCALATED", "NONE"
    return "OPEN", "NONE"


# ------------------------------------------------------- fault score --------

def fault_score(severity, occurrence_count, affected_load_kw, equipment_class):
    severity_weight = SEVERITY_WEIGHT[severity]
    recurrences = occurrence_count - 1
    if recurrences > PERSISTENCE_MAX_OCCURRENCES:
        recurrences = PERSISTENCE_MAX_OCCURRENCES
    if recurrences < 0:
        recurrences = 0
    persistence = rhu(Decimal(1) + PERSISTENCE_STEP * Decimal(recurrences), 2)
    load_factor = rhu(Decimal(1) + D(affected_load_kw) / LOAD_DIVISOR_KW, 4)
    if load_factor > LOAD_FACTOR_CAP:
        load_factor = LOAD_FACTOR_CAP
    weighted = rhu(severity_weight * persistence, 2)
    loaded = rhu(weighted * load_factor, 2)
    with_class = loaded + REFRIGERATION_BONUS if equipment_class == "REFRIGERATION" else loaded
    score = rhu(with_class, 1)
    if score > SCORE_CAP:
        score = q(SCORE_CAP, 1)
    return score


# ------------------------------------------ lighting override projection ----

def override_projection(zone_load_kw, start, end):
    hours = exact_hours(start, end)
    return rhu(D(zone_load_kw) * hours, 2)


# --------------------------------------------- retrofit priority score ------

def retrofit_simple_payback(projected_annual_savings_kwh, capex_usd, blended_rate):
    annual_savings_usd = rhu(D(projected_annual_savings_kwh) * D(blended_rate), 2)
    payback_years = rhu(D(capex_usd) / annual_savings_usd, 2)
    score = rhu(Decimal(100) - PAYBACK_PENALTY_PER_YEAR * payback_years, 1)
    if score > SCORE_MAX:
        score = q(SCORE_MAX, 1)
    if score < SCORE_MIN:
        score = q(SCORE_MIN, 1)
    return annual_savings_usd, payback_years, score


def retrofit_risk_adjusted(projected_annual_savings_kwh, capex_usd, blended_rate,
                           fault_density):
    raw = rhu(D(projected_annual_savings_kwh) * D(blended_rate), 2)
    annual_savings_usd = rhu(raw * DEFAULT_REALIZATION_RATE, 2)
    payback_years = rhu(D(capex_usd) / annual_savings_usd, 2)
    bonus_count = fault_density if fault_density < FAULT_DENSITY_CAP else FAULT_DENSITY_CAP
    score = rhu(Decimal(100) - PAYBACK_PENALTY_PER_YEAR * payback_years
                + FAULT_DENSITY_BONUS * Decimal(bonus_count), 1)
    if score > SCORE_MAX:
        score = q(SCORE_MAX, 1)
    if score < SCORE_MIN:
        score = q(SCORE_MIN, 1)
    return annual_savings_usd, payback_years, score


# --------------------------------------- measurement and verification -------

def measured_savings(climate_zone, baseline_period_kwh, post_period_kwh,
                     mv_period_days, projected_annual_savings_kwh):
    climate_factor = CLIMATE_ADJUST[climate_zone]
    adjusted_baseline_kwh = rhu(D(baseline_period_kwh) * climate_factor, 2)
    measured_savings_kwh = rhu(adjusted_baseline_kwh - D(post_period_kwh), 2)
    expected_savings_kwh = rhu(D(projected_annual_savings_kwh)
                               * Decimal(mv_period_days) / DAYS_PER_YEAR, 2)
    realization_rate = rhu(measured_savings_kwh / expected_savings_kwh, 4)
    return adjusted_baseline_kwh, measured_savings_kwh, expected_savings_kwh, realization_rate


# ------------------------------------------------------ EUI benchmarking -----

def qualifying_bills(store_id):
    from datetime import timedelta
    window_start = db.clock - timedelta(days=TRAILING_WINDOW_DAYS)
    out = []
    for bill in derive.store_bills(store_id):
        if bill["validation_state"] not in ("VALIDATED", "ADJUSTED"):
            continue
        if window_start <= bill["period_end_iso"] <= db.clock:
            out.append(bill)
    return out


def store_eui(store):
    bills = qualifying_bills(store["id"])
    if not bills:
        return None
    window_kwh = Decimal(0)
    for bill in bills:
        window_kwh += D(bill["billed_kwh"])
    return rhu(window_kwh * KWH_TO_KBTU / Decimal(store["floor_area_sqft"]), 2)


def _median(values):
    """Median of a list of (eui, created_at, seq) tuples already ordered."""
    count = len(values)
    if count == 0:
        return None
    if count % 2 == 1:
        return q(values[count // 2][0], 2)
    lower = values[count // 2 - 1][0]
    upper = values[count // 2][0]
    return rhu((lower + upper) / Decimal(2), 2)


def peer_group_members(store, eui_map):
    return [s for s in derive._by_created(list(db.stores.values()))
            if s["climate_zone"] == store["climate_zone"]
            and s["store_format"] == store["store_format"]
            and eui_map.get(s["id"]) is not None]


def benchmark_for_store(store, eui_map):
    """Per-store benchmark figures; the peer median excludes the subject."""
    own = eui_map.get(store["id"])
    if own is None:
        return {
            "eui_kbtu_per_sqft": None,
            "benchmark_percentile": None,
            "benchmark_outlier_flag": False,
            "peer_median_eui": None,
            "outlier_threshold_eui": None,
        }
    group = peer_group_members(store, eui_map)
    others = [s for s in group if s["id"] != store["id"]]
    ordered_others = sorted(
        [(eui_map[s["id"]], s["created_at"], s["_seq"]) for s in others],
        key=lambda t: (t[0], t[1], t[2]),
    )
    peer_median = _median(ordered_others)
    if peer_median is None:
        return {
            "eui_kbtu_per_sqft": own,
            "benchmark_percentile": rhu(100, 1),
            "benchmark_outlier_flag": False,
            "peer_median_eui": None,
            "outlier_threshold_eui": None,
        }
    threshold = rhu(OUTLIER_MEDIAN_MULTIPLE * peer_median, 2)
    at_or_below = len([s for s in group if eui_map[s["id"]] <= own])
    percentile = rhu(Decimal(100) * Decimal(at_or_below) / Decimal(len(group)), 1)
    return {
        "eui_kbtu_per_sqft": own,
        "benchmark_percentile": percentile,
        "benchmark_outlier_flag": own >= threshold,
        "peer_median_eui": peer_median,
        "outlier_threshold_eui": threshold,
    }


def all_store_euis():
    return dict((s["id"], store_eui(s)) for s in db.stores.values())


# --------------------------------------------- tariff switch projection ------

def reference_bill(account_id):
    eligible = [b for b in derive.account_bills(account_id)
                if b["validation_state"] in ("VALIDATED", "ADJUSTED")]
    if not eligible:
        return None
    eligible.sort(key=lambda b: (b["period_end_iso"], b["created_at"], b["_seq"]),
                  reverse=True)
    return eligible[0]


def tariff_projection(account):
    """Returns the seven projection outputs; all null without a reference bill."""
    empty = {
        "reference_bill_id": None,
        "current_annual_cost_usd": None,
        "candidate_annual_cost_usd": None,
        "annual_delta_usd": None,
        "switch_recommended": None,
        "candidate_peak_basis": None,
        "candidate_billable_demand_kw": None,
    }
    bill = reference_bill(account["id"])
    if bill is None or bill["recomputed_amount_usd"] is None:
        return empty
    current_annual = rhu(D(bill["recomputed_amount_usd"]) * ANNUALIZATION_MONTHS, 2)
    candidate_fields = ("candidate_rate_schedule_code", "candidate_rate_family",
                        "candidate_demand_charge_per_kw", "candidate_rate_on_peak",
                        "candidate_rate_off_peak")
    if any(account[field] is None for field in candidate_fields):
        return {
            "reference_bill_id": bill["id"],
            "current_annual_cost_usd": current_annual,
            "candidate_annual_cost_usd": None,
            "annual_delta_usd": None,
            "switch_recommended": False,
            "candidate_peak_basis": None,
            "candidate_billable_demand_kw": None,
        }
    intervals = period_intervals(account["id"], bill["period_start_iso"],
                                bill["period_end_iso"])
    demand, basis = period_peak_demand(intervals, account["candidate_rate_family"],
                                       account["ratchet_peak_kw"])
    if demand is None:
        return {
            "reference_bill_id": bill["id"],
            "current_annual_cost_usd": current_annual,
            "candidate_annual_cost_usd": None,
            "annual_delta_usd": None,
            "switch_recommended": False,
            "candidate_peak_basis": basis,
            "candidate_billable_demand_kw": None,
        }
    parts = bill_recompute(bill["on_peak_kwh"], bill["off_peak_kwh"],
                           account["candidate_rate_on_peak"],
                           account["candidate_rate_off_peak"],
                           demand, account["candidate_demand_charge_per_kw"])
    candidate_annual = rhu(parts["recomputed_amount_usd"] * ANNUALIZATION_MONTHS, 2)
    delta = q(candidate_annual - current_annual, 2)
    return {
        "reference_bill_id": bill["id"],
        "current_annual_cost_usd": current_annual,
        "candidate_annual_cost_usd": candidate_annual,
        "annual_delta_usd": delta,
        "switch_recommended": delta <= -SWITCH_MIN_SAVINGS_USD,
        "candidate_peak_basis": basis,
        "candidate_billable_demand_kw": demand,
    }
