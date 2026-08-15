"""Calculation rules (SCAFFOLD 1.3 / PRD section 3). All decimal arithmetic."""

from decimal import Decimal, ROUND_HALF_UP

import db
from util import D


def r2(x):
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def r1(x):
    return x.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def r6(x):
    return x.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def r0(x):
    return x.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def period_days(period):
    start = db.parse_dt(period["period_start"])
    end = db.parse_dt(period["period_end"])
    days = (end - start).days
    return days if days > 0 else 1  # guard; spec periods are multi-day


def latest_finalized_balance(dma_id):
    """Latest FINALIZED (non-SUPERSEDED) balance: max period_end, tie -> earliest created."""
    bals = [b for b in db.store["water_balance_periods"].values()
            if b["dma_id"] == dma_id and b["status"] == "FINALIZED"]
    if not bals:
        return None
    bals.sort(key=lambda b: (b["period_end"], -b["_seq"]), reverse=True)
    return bals[0]


# ---------------------------------------------------------------------------
# water_balance_nrw
# ---------------------------------------------------------------------------

AUDIT_CONFIDENCE_CREDIT_PCT = Decimal("0.50")
AUDIT_CREDIT_CAP_FRACTION = Decimal("0.10")


def compute_water_balance(period, variant):
    """Populate nrw_volume_m3, apparent_loss_m3, real_loss_m3, nrw_pct in place."""
    siv = D(period["system_input_volume_m3"])
    billed = D(period["billed_authorized_m3"])
    unbilled = D(period["unbilled_authorized_m3"])
    unauth = D(period["unauthorized_consumption_m3"])
    inacc = D(period["metering_inaccuracy_m3"])

    nrw_volume = siv - billed
    apparent = unauth + inacc
    real_raw = nrw_volume - unbilled - apparent
    real = real_raw if real_raw > 0 else Decimal(0)
    base_pct = nrw_volume / siv * Decimal(100)

    if variant == "AUDITED":
        adj = AUDIT_CONFIDENCE_CREDIT_PCT
        cap = base_pct * AUDIT_CREDIT_CAP_FRACTION
        if cap < adj:
            adj = cap
        nrw_pct = r2(base_pct - adj)
    else:
        nrw_pct = r2(base_pct)

    period["nrw_volume_m3"] = float(nrw_volume)
    period["apparent_loss_m3"] = float(apparent)
    period["real_loss_m3"] = float(real)
    period["nrw_pct"] = float(nrw_pct)
    return real_raw


# ---------------------------------------------------------------------------
# infrastructure_leakage_index
# ---------------------------------------------------------------------------

def compute_ili(period, dma):
    cc = D(dma["connection_count"])
    km = D(dma["mains_length_km"])
    uarl = (D(18) * cc + D("0.8") * km + D(25) * D(40)) / D(1000) * D(365)
    days = period_days(period)
    carl = D(period["real_loss_m3"]) * D(365) / D(days)
    ili = r2(carl / uarl)
    if ili < Decimal("0.01"):
        ili = Decimal("0.01")
    return float(ili)


def uarl_annual(dma):
    cc = D(dma["connection_count"])
    km = D(dma["mains_length_km"])
    return (D(18) * cc + D("0.8") * km + D(25) * D(40)) / D(1000) * D(365)


def carl_annual(period):
    days = period_days(period)
    return D(period["real_loss_m3"]) * D(365) / D(days)


# ---------------------------------------------------------------------------
# night_flow_signal
# ---------------------------------------------------------------------------

MNF_ELEVATED_LPS = Decimal("5.0")
MNF_CRITICAL_LPS = Decimal("15.0")
MNF_ELEVATED_PCT = Decimal("8.0")
MNF_CRITICAL_PCT = Decimal("20.0")


def compute_night_flow(assessment):
    measured = D(assessment["measured_mnf_lps"])
    expected = D(assessment["expected_legitimate_night_use_lps"])
    net = measured - expected
    if net < 0:
        net = Decimal(0)
    assessment["net_night_flow_lps"] = float(net)

    bal = latest_finalized_balance(assessment["dma_id"])
    pct = None
    if bal is not None:
        days = period_days(bal)
        inflow_lps = D(bal["system_input_volume_m3"]) * D(1000) / (D(days) * D(86400))
        pct = float(r2(net / inflow_lps * D(100)))
    assessment["net_night_flow_pct"] = pct

    signal = "NONE"
    if net >= MNF_CRITICAL_LPS or (pct is not None and D(pct) >= MNF_CRITICAL_PCT):
        signal = "CRITICAL"
    elif net >= MNF_ELEVATED_LPS or (pct is not None and D(pct) >= MNF_ELEVATED_PCT):
        signal = "ELEVATED"
    assessment["leak_signal"] = signal


# ---------------------------------------------------------------------------
# leak_repair_priority
# ---------------------------------------------------------------------------

WATER_VALUE_PER_M3 = Decimal("1.20")
COST_EPSILON = Decimal("1.0")
SCORE_SCALE = Decimal("2.0")
PRESSURE_PROJECT_MULTIPLIER = Decimal("1.25")
REOPEN_MULTIPLIER = Decimal("1.10")
P1_THRESHOLD = Decimal("50.0")
P2_THRESHOLD = Decimal("20.0")


def compute_leak_priority(leak, reopened=False):
    annualized = D(leak["estimated_loss_lps"]) * D(86400) * D(365) / D(1000)
    leak["annualized_loss_m3"] = float(annualized)
    value_loss = annualized * WATER_VALUE_PER_M3
    cost = D(leak["repair_cost_estimate"])
    if cost < COST_EPSILON:
        cost = COST_EPSILON
    cost_ratio = value_loss / cost
    score = cost_ratio * SCORE_SCALE
    if score > D(100):
        score = D(100)
    survey = db.store["leak_surveys"].get(leak["survey_id"])
    dma_id = survey["dma_id"] if survey else None
    has_active_pressure = any(
        p["dma_id"] == dma_id and p["status"] == "ACTIVE"
        for p in db.store["pressure_projects"].values()
    )
    if has_active_pressure:
        score *= PRESSURE_PROJECT_MULTIPLIER
    if reopened:
        score *= REOPEN_MULTIPLIER
    score = r2(score)
    leak["repair_priority_score"] = float(score)
    if score >= P1_THRESHOLD:
        leak["priority_band"] = "P1"
    elif score >= P2_THRESHOLD:
        leak["priority_band"] = "P2"
    else:
        leak["priority_band"] = "P3"


# ---------------------------------------------------------------------------
# meter_replacement_due
# ---------------------------------------------------------------------------

AGE_LIMIT_YEARS = 15
ACCURACY_PASS_THRESHOLD = Decimal("98.0")
ACCURACY_OVER_CEILING = Decimal("102.0")


def meter_age_trip(meter):
    installed = db.parse_dt(meter["installed_at"])
    delta_days = (db.logical_now() - installed).days
    age_years = int(D(delta_days) / D("365.25"))  # truncated to integer
    return age_years >= AGE_LIMIT_YEARS


def meter_accuracy_trip(meter):
    tests = [t for t in db.store["meter_accuracy_tests"].values()
             if t["meter_id"] == meter["id"] and t["status"] == "COMPLETED"]
    if not tests:
        return False
    tests.sort(key=lambda t: (t["tested_at"], -t["_seq"]), reverse=True)
    return tests[0]["result"] == "FAIL"


def compute_replacement_due(meter):
    policy = meter["replacement_policy"]
    if policy == "AGE_BASED":
        return meter_age_trip(meter)
    if policy == "ACCURACY_BASED":
        return meter_accuracy_trip(meter)
    return meter_age_trip(meter) or meter_accuracy_trip(meter)  # HYBRID


# ---------------------------------------------------------------------------
# pressure_leak_reduction
# ---------------------------------------------------------------------------

FAVAD_N1 = 1.15


def compute_pressure_reduction(project):
    baseline = D(project["baseline_pressure_m"])
    measured = D(project["measured_pressure_m"])
    pct = r2((baseline - measured) / baseline * D(100))
    project["pressure_reduction_pct"] = float(pct)
    bal = latest_finalized_balance(project["dma_id"])
    if bal is None:
        project["estimated_leak_reduction_m3_per_year"] = None
    else:
        factor = 1.0 - (float(measured) / float(baseline)) ** FAVAD_N1
        annualized = D(bal["real_loss_m3"]) * D(365) / D(period_days(bal))
        est = r0(annualized * D(factor))
        project["estimated_leak_reduction_m3_per_year"] = float(est)


# ---------------------------------------------------------------------------
# intervention_benefit_cost
# ---------------------------------------------------------------------------

TIER_LOW_MAX = Decimal("50000")
TIER_MID_MAX = Decimal("200000")
VALUE_LOW = Decimal("1.10")
VALUE_MID = Decimal("1.30")
VALUE_HIGH = Decimal("1.55")
ANALYSIS_HORIZON_YEARS = 20
R_PROVISIONAL = Decimal("0.07")
R_BANKABLE = Decimal("0.04")
COST_FLOOR = Decimal("1.0")
BCR_APPROVAL_THRESHOLD = Decimal("1.00")


def compute_bcr(proposal, variant):
    vol = D(proposal["expected_volume_saved_m3_per_year"])
    if vol < TIER_LOW_MAX:
        marginal = VALUE_LOW
    elif vol < TIER_MID_MAX:
        marginal = VALUE_MID
    else:
        marginal = VALUE_HIGH
    gross = vol * marginal
    rate = R_PROVISIONAL if variant == "PROVISIONAL" else R_BANKABLE
    pv_factor = Decimal(0)
    for t in range(1, ANALYSIS_HORIZON_YEARS + 1):
        pv_factor += D(1) / ((D(1) + rate) ** t)
    pv_factor = r6(pv_factor)
    pv_benefit = gross * pv_factor
    pv_cost = D(proposal["capital_cost"]) + D(proposal["annual_om_cost"]) * pv_factor
    denom = pv_cost if pv_cost > COST_FLOOR else COST_FLOOR
    bcr = r2(pv_benefit / denom)
    net = gross - D(proposal["annual_om_cost"])
    if net <= 0:
        payback = None
    else:
        payback = float(r1(D(proposal["capital_cost"]) / net))
    proposal["benefit_cost_ratio"] = float(bcr)
    proposal["payback_years"] = payback


# ---------------------------------------------------------------------------
# benchmark_nrw_aggregation
# ---------------------------------------------------------------------------

def qualifying_balance(dma_id, rep_start, rep_end):
    """FINALIZED non-SUPERSEDED balance fully inside the reporting window;
    max period_end, tie -> earliest created."""
    cands = []
    for b in db.store["water_balance_periods"].values():
        if b["dma_id"] != dma_id or b["status"] != "FINALIZED":
            continue
        if b["period_start"] >= rep_start and b["period_end"] <= rep_end:
            cands.append(b)
    if not cands:
        return None
    cands.sort(key=lambda b: (b["period_end"], -b["_seq"]), reverse=True)
    return cands[0]


def compute_benchmark_snapshot(report):
    rows = []
    sum_nrw_vol = Decimal(0)
    sum_siv = Decimal(0)
    sum_carl = Decimal(0)
    sum_uarl = Decimal(0)
    for dma_id in report["dma_ids"]:
        dma = db.store["dmas"][dma_id]
        bal = qualifying_balance(
            dma_id, report["reporting_period_start"], report["reporting_period_end"])
        rows.append({
            "dma_id": dma_id,
            "dma_code": dma["code"],
            "nrw_pct": bal["nrw_pct"],
            "ili": bal["ili"],
            "real_loss_m3": bal["real_loss_m3"],
            "_dma": dma,
            "_bal": bal,
        })
    rows.sort(key=lambda r: r["dma_code"])
    for r in rows:
        bal = r["_bal"]
        sum_nrw_vol += D(bal["nrw_volume_m3"])
        sum_siv += D(bal["system_input_volume_m3"])
        if bal["ili"] is not None:
            sum_carl += carl_annual(bal)
            sum_uarl += uarl_annual(r["_dma"])
    report["utility_nrw_pct"] = float(r2(sum_nrw_vol / sum_siv * D(100)))
    report["utility_ili"] = float(r2(sum_carl / sum_uarl)) if sum_uarl > 0 else None
    report["per_dma_breakdown"] = [
        {"dma_id": r["dma_id"], "dma_code": r["dma_code"], "nrw_pct": r["nrw_pct"],
         "ili": r["ili"], "real_loss_m3": r["real_loss_m3"]}
        for r in rows
    ]
