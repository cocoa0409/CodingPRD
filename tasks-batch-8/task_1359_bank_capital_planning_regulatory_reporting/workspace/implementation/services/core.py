"""Core business logic: constants, calculations, cascades, serializers.

Implements SCAFFOLD 1.3 calculation rules and PRD section 3 workflows with
integer-cents / integer-bps arithmetic and floor rounding throughout.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import db
from db import (
    banks, reporting_periods, capital_instruments, risk_exposures,
    capital_plans, stress_scenarios, call_reports, edit_exceptions,
    distribution_requests, sub_debt_issuances, pca_threshold_events,
    icaap_documents, stamp_new, touch, public,
)
from util import parse_datetime, fmt_dt


# ---------------------------------------------------------------------------
# Constants (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

BPS_DENOMINATOR = 10000
ADVANCED_MULTIPLIER_BPS = 10600
AT1_CAP_BPS_OF_RWA = 150
T2_CAP_BPS_OF_RWA = 200
TAX_RATE_BPS = 2100
STRESS_RWA_GROWTH_BPS_PER_QUARTER = 50
SCB_FLOOR_BPS = 250
PCA_ADEQUATE_CET1_BPS = 450
MAX_ACTIVE_SCENARIOS = 2
DISTRIBUTION_WINDOW_DAYS = 10
FILING_LAG_Q1_Q2_Q3_DAYS = 35
FILING_LAG_Q4_DAYS = 40
QUARTER_WEIGHTS_BPS = [800, 1000, 1200, 1400, 1300, 1200, 1100, 1100, 900]

PCA_BUCKETS = [
    "WELL_CAPITALIZED",
    "ADEQUATELY_CAPITALIZED",
    "UNDERCAPITALIZED",
    "SIGNIFICANTLY_UNDERCAPITALIZED",
    "CRITICALLY_UNDERCAPITALIZED",
]
PCA_ORDER = {b: i for i, b in enumerate(PCA_BUCKETS)}  # best -> worst
PCA_PASSING = {"WELL_CAPITALIZED", "ADEQUATELY_CAPITALIZED"}

PCA_THRESHOLDS = {
    "CET1": (650, 450, 400, 300),
    "TIER1": (800, 600, 500, 400),
    "TOTAL": (1000, 800, 700, 600),
    "LEVERAGE": (500, 400, 350, 300),
}
# Adequate floor per metric (used by MDBA waterfall)
PCA_ADEQUATE_FLOOR = {
    "CET1": 450,
    "TIER1": 600,
    "TOTAL": 800,
    "LEVERAGE": 400,
}

RWA_METHODOLOGIES = {"STANDARDIZED", "ADVANCED"}
PERIOD_QUARTERS = {"Q1", "Q2", "Q3", "Q4"}
INSTRUMENT_CLASSES = {"CET1", "AT1", "T2"}
INSTRUMENT_SUBTYPES = {"COMMON_STOCK", "PREFERRED", "TRUST_PREFERRED", "SUBORDINATED_DEBT", "OTHER"}
CALLABLE_SUBTYPES = {"PREFERRED", "TRUST_PREFERRED", "SUBORDINATED_DEBT"}
EXPOSURE_CLASSES = {
    "SOVEREIGN", "CORPORATE", "RETAIL_MORTGAGE", "RETAIL_OTHER", "CRE",
    "HVCRE", "EQUITY", "SECURITIZATION", "OPERATIONAL_RISK", "MARKET_RISK",
}
OBLIGOR_GRADES = {"INVESTMENT_GRADE", "NON_INVESTMENT_GRADE", "DEFAULT"}
GRADE_MULTIPLIER = {"INVESTMENT_GRADE": 1, "NON_INVESTMENT_GRADE": 2, "DEFAULT": 3}
SEVERITIES = {"FATAL", "QUALITY", "INFORMATIONAL"}
DISTRIBUTION_KINDS = {"DIVIDEND", "BUYBACK"}
REQUIRED_ICAAP_SECTIONS = {
    "GOVERNANCE", "RISK_APPETITE", "CAPITAL_ADEQUACY", "STRESS_TESTING", "DISTRIBUTION_POLICY",
}
IN_FLIGHT_PLAN_STATES = {"BOARD_REVIEW", "SUBMITTED", "SUPERVISORY_REVIEW", "APPROVED"}


# ---------------------------------------------------------------------------
# Logical-clock helpers
# ---------------------------------------------------------------------------

def clock_now() -> datetime:
    """Current logical time as a datetime (UTC)."""
    dt = parse_datetime(db.get_current_utc())
    return dt if dt is not None else parse_datetime("2026-08-01T00:00:00Z")


def clock_today() -> date:
    return clock_now().date()


# ---------------------------------------------------------------------------
# Entity lookup helpers (left-to-right path resolution, ERR_NOT_FOUND)
# ---------------------------------------------------------------------------

from errors import raise_err, ERR_NOT_FOUND  # noqa: E402


def get_bank(bank_id: str) -> dict:
    b = banks.get(bank_id)
    if b is None:
        raise_err(ERR_NOT_FOUND, "Bank not found")
    return b


def get_period(bank: dict, period_id: str) -> dict:
    p = reporting_periods.get(period_id)
    if p is None or p["bank_id"] != bank["id"]:
        raise_err(ERR_NOT_FOUND, "ReportingPeriod not found")
    return p


def get_report(period: dict, report_id: str) -> dict:
    r = call_reports.get(report_id)
    if r is None or r["reporting_period_id"] != period["id"]:
        raise_err(ERR_NOT_FOUND, "CallReport not found")
    return r


def get_edit(report: dict, edit_id: str) -> dict:
    e = edit_exceptions.get(edit_id)
    if e is None or e["call_report_id"] != report["id"]:
        raise_err(ERR_NOT_FOUND, "EditException not found")
    return e


def get_instrument(bank: dict, instrument_id: str) -> dict:
    i = capital_instruments.get(instrument_id)
    if i is None or i["bank_id"] != bank["id"]:
        raise_err(ERR_NOT_FOUND, "CapitalInstrument not found")
    return i


def get_exposure(period: dict, exposure_id: str) -> dict:
    e = risk_exposures.get(exposure_id)
    if e is None or e["reporting_period_id"] != period["id"]:
        raise_err(ERR_NOT_FOUND, "RiskExposure not found")
    return e


def get_scenario(bank: dict, scenario_id: str) -> dict:
    s = stress_scenarios.get(scenario_id)
    if s is None or s["bank_id"] != bank["id"]:
        raise_err(ERR_NOT_FOUND, "StressScenario not found")
    return s


def get_plan(bank: dict, plan_id: str) -> dict:
    p = capital_plans.get(plan_id)
    if p is None or p["bank_id"] != bank["id"]:
        raise_err(ERR_NOT_FOUND, "CapitalPlan not found")
    return p


def get_distribution(bank: dict, request_id: str) -> dict:
    d = distribution_requests.get(request_id)
    if d is None or d["bank_id"] != bank["id"]:
        raise_err(ERR_NOT_FOUND, "CapitalDistributionRequest not found")
    return d


def get_issuance(bank: dict, issuance_id: str) -> dict:
    s = sub_debt_issuances.get(issuance_id)
    if s is None or s["bank_id"] != bank["id"]:
        raise_err(ERR_NOT_FOUND, "SubordinatedDebtIssuance not found")
    return s


def get_pca_event(bank: dict, event_id: str) -> dict:
    e = pca_threshold_events.get(event_id)
    if e is None or e["bank_id"] != bank["id"]:
        raise_err(ERR_NOT_FOUND, "PCAThresholdEvent not found")
    return e


def get_icaap(bank: dict, doc_id: str) -> dict:
    d = icaap_documents.get(doc_id)
    if d is None or d["bank_id"] != bank["id"]:
        raise_err(ERR_NOT_FOUND, "ICAAPDocument not found")
    return d


def bump_bank(bank: dict) -> None:
    """Bank.version increments on capacity-affecting mutations (PRD 2.8)."""
    touch(bank, bump=True)


# ---------------------------------------------------------------------------
# Filing deadline computation (filing_deadline_computation)
# ---------------------------------------------------------------------------

def compute_filing_due_at(period_end: date, quarter: str) -> datetime:
    lag = FILING_LAG_Q4_DAYS if quarter == "Q4" else FILING_LAG_Q1_Q2_Q3_DAYS
    d = period_end + timedelta(days=lag)
    return datetime(d.year, d.month, d.day, 17, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# T2 amortization haircut (t2_amortization_haircut)
# ---------------------------------------------------------------------------

def t2_haircut_pct_for(maturity: date | None, as_of: date) -> int:
    if maturity is None:
        return 0
    days = (maturity - as_of).days
    years = int(days // 365.25) if days >= 0 else -1
    if days < 0:
        return 100
    if years >= 5:
        return 0
    if years == 4:
        return 20
    if years == 3:
        return 40
    if years == 2:
        return 60
    if years == 1:
        return 80
    return 100


def recompute_instrument_reg_cap(inst: dict, as_of: date) -> bool:
    """Recompute t2_haircut_pct / regulatory_capital_cents. Returns True if changed."""
    if inst["instrument_subtype"] == "SUBORDINATED_DEBT":
        if inst["status"] == "MATURED":
            haircut = 100
        else:
            haircut = t2_haircut_pct_for(inst.get("_maturity_date"), as_of)
        reg_cap = (inst["outstanding_amount_cents"] * (100 - haircut)) // 100
    else:
        haircut = 0
        reg_cap = inst["outstanding_amount_cents"]
    changed = (inst.get("t2_haircut_pct") != haircut or inst.get("regulatory_capital_cents") != reg_cap)
    inst["t2_haircut_pct"] = haircut
    inst["regulatory_capital_cents"] = reg_cap
    return changed


# ---------------------------------------------------------------------------
# RWA aggregation (rwa_standardized / rwa_advanced / rwa_selected)
# ---------------------------------------------------------------------------

def exposures_for_period(period_id: str) -> list[dict]:
    return [e for e in risk_exposures.values() if e["reporting_period_id"] == period_id]


def rwa_line_standardized(e: dict) -> int:
    return (e["exposure_at_default_cents"] * e["risk_weight_bps"]) // BPS_DENOMINATOR


def rwa_line_advanced(e: dict) -> int:
    effective_ead = (e["exposure_at_default_cents"] * (BPS_DENOMINATOR - e.get("collateral_haircut_bps", 0))) // BPS_DENOMINATOR
    return (effective_ead * e["risk_weight_bps"] * ADVANCED_MULTIPLIER_BPS) // (BPS_DENOMINATOR * BPS_DENOMINATOR)


def compute_rwa_variants(period_id: str) -> tuple[int, int, int]:
    """Returns (rwa_standardized_cents, rwa_advanced_cents, total_exposure_cents)."""
    std = 0
    adv = 0
    total_ead = 0
    for e in exposures_for_period(period_id):
        std += rwa_line_standardized(e)
        adv += rwa_line_advanced(e)
        total_ead += e["exposure_at_default_cents"]
    return std, adv, total_ead


def select_rwa(bank: dict, rwa_std: int, rwa_adv: int) -> int:
    if bank["rwa_methodology"] == "ADVANCED":
        return max(rwa_adv, rwa_std)  # Collins floor
    return rwa_std


# ---------------------------------------------------------------------------
# Capital stack (cet1_tier1_total_capital)
# ---------------------------------------------------------------------------

def compute_capital_stack(bank: dict, rwa_cents: int, period_end: date) -> tuple[int, int, int]:
    """Recompute instrument haircuts against the period end, then stack."""
    cet1 = 0
    at1_raw = 0
    t2_raw = 0
    for inst in capital_instruments.values():
        if inst["bank_id"] != bank["id"] or inst["status"] != "OUTSTANDING":
            continue
        recompute_instrument_reg_cap(inst, period_end)
        reg = inst["regulatory_capital_cents"]
        if inst["instrument_class"] == "CET1":
            cet1 += reg
        elif inst["instrument_class"] == "AT1":
            at1_raw += reg
        elif inst["instrument_class"] == "T2":
            t2_raw += reg
    at1_cap = (rwa_cents * AT1_CAP_BPS_OF_RWA) // BPS_DENOMINATOR
    tier1 = cet1 + min(at1_raw, at1_cap)
    t2_cap_pct = (rwa_cents * T2_CAP_BPS_OF_RWA) // BPS_DENOMINATOR
    t2_counted = min(t2_raw, t2_cap_pct, cet1)
    total = tier1 + t2_counted
    return cet1, tier1, total


def ratio_bps(numerator: int, denominator: int) -> int | None:
    if denominator == 0:
        return None
    return (numerator * BPS_DENOMINATOR) // denominator


# ---------------------------------------------------------------------------
# PCA classification (pca_bucket_classification)
# ---------------------------------------------------------------------------

def classify_metric(metric: str, ratio: int | None) -> str:
    if ratio is None:
        return "CRITICALLY_UNDERCAPITALIZED"
    well, adequate, under, significant = PCA_THRESHOLDS[metric]
    if ratio >= well:
        return "WELL_CAPITALIZED"
    if ratio >= adequate:
        return "ADEQUATELY_CAPITALIZED"
    if ratio >= under:
        return "UNDERCAPITALIZED"
    if ratio >= significant:
        return "SIGNIFICANTLY_UNDERCAPITALIZED"
    return "CRITICALLY_UNDERCAPITALIZED"


def classify_bank(report: dict) -> dict[str, str]:
    return {
        "CET1": classify_metric("CET1", report.get("cet1_ratio_bps")),
        "TIER1": classify_metric("TIER1", report.get("tier1_ratio_bps")),
        "TOTAL": classify_metric("TOTAL", report.get("total_ratio_bps")),
        "LEVERAGE": classify_metric("LEVERAGE", report.get("leverage_ratio_bps")),
    }


def worst_bucket(metric_buckets: dict[str, str]) -> str:
    return max(metric_buckets.values(), key=lambda b: PCA_ORDER[b])


# ---------------------------------------------------------------------------
# Latest accepted call report
# ---------------------------------------------------------------------------

def latest_accepted_report(bank: dict) -> dict | None:
    accepted = [
        r for r in call_reports.values()
        if r["bank_id"] == bank["id"] and r["status"] == "ACCEPTED"
    ]
    if not accepted:
        return None
    accepted.sort(key=lambda r: (r.get("accepted_at") or "", r.get("_seq", 0)))
    return accepted[-1]


# ---------------------------------------------------------------------------
# Stress loss projection (stress_loss_projection)
# ---------------------------------------------------------------------------

def _base_loss_bps_x1000(exposure_class: str, sc: dict) -> int:
    """Base loss rate in bps, scaled by 1000 to preserve integer exactness."""
    g = abs(sc["gdp_shock_bps"])
    u = sc["unemployment_peak_bps"]
    h = abs(sc["hpi_shock_bps"])
    c = abs(sc["cre_price_shock_bps"])
    m = abs(sc["market_shock_bps"])
    if exposure_class == "CORPORATE":
        return 200 * 1000 + g * 30
    if exposure_class == "CRE":
        return 150 * 1000 + c * 25
    if exposure_class == "HVCRE":
        return 300 * 1000 + c * 40
    if exposure_class == "RETAIL_MORTGAGE":
        return 100 * 1000 + h * 20
    if exposure_class == "RETAIL_OTHER":
        return 250 * 1000 + u * 15
    if exposure_class == "SOVEREIGN":
        return 0
    if exposure_class == "EQUITY":
        return 500 * 1000 + m * 50
    if exposure_class == "SECURITIZATION":
        return 300 * 1000 + g * 20 + h * 10
    if exposure_class == "OPERATIONAL_RISK":
        return 50 * 1000
    if exposure_class == "MARKET_RISK":
        return 100 * 1000 + m * 30
    return 0


def compute_projected_pre_tax_loss(bank: dict, scenario: dict) -> int:
    total = 0
    for e in risk_exposures.values():
        if e["bank_id"] != bank["id"]:
            continue
        period = reporting_periods.get(e["reporting_period_id"])
        if period is None or period["status"] not in ("OPEN", "FILING_DUE"):
            continue
        base_x1000 = _base_loss_bps_x1000(e["exposure_class"], scenario)
        mult = GRADE_MULTIPLIER.get(e["obligor_grade"], 1)
        total += (e["exposure_at_default_cents"] * base_x1000 * mult) // (1000 * BPS_DENOMINATOR)
    return total


# ---------------------------------------------------------------------------
# Plan projections (stress_capital_buffer)
# ---------------------------------------------------------------------------

def proposed_distributions_cents(plan: dict) -> int:
    total = 0
    for d in distribution_requests.values():
        if d["capital_plan_id"] == plan["id"] and d["status"] not in ("REJECTED", "WITHDRAWN"):
            total += d["distribution_amount_cents"]
    return total


def compute_plan_projections(plan: dict, bank: dict) -> None:
    """Compute projected_cet1_bps_9q (base case) and stressed_min_cet1_bps_9q."""
    baseline_cet1 = plan.get("baseline_cet1_cents") or 0
    baseline_rwa = plan.get("baseline_rwa_cents") or 0
    scenario = stress_scenarios.get(plan.get("stress_scenario_id") or "")
    loss = (scenario.get("projected_pre_tax_loss_cents") or 0) if scenario else 0
    per_q_distributions = proposed_distributions_cents(plan)

    base_min = None
    stressed_min = None
    cum_weight = 0
    for q in range(1, 10):
        cum_weight += QUARTER_WEIGHTS_BPS[q - 1]
        cum_pre_tax = (loss * cum_weight) // BPS_DENOMINATOR
        cum_after_tax = (cum_pre_tax * (BPS_DENOMINATOR - TAX_RATE_BPS)) // BPS_DENOMINATOR
        cum_distributions = per_q_distributions * q
        if baseline_rwa > 0:
            # Base case: no stress losses, no RWA growth; planned distributions continue.
            base_ratio = ((baseline_cet1 - cum_distributions) * BPS_DENOMINATOR) // baseline_rwa
            # Stressed: after-tax losses + distributions; RWA grows 50 bps per quarter.
            num = baseline_cet1 - cum_after_tax - cum_distributions
            stressed_ratio = (num * BPS_DENOMINATOR * BPS_DENOMINATOR) // (
                baseline_rwa * (BPS_DENOMINATOR + STRESS_RWA_GROWTH_BPS_PER_QUARTER * q)
            )
        else:
            base_ratio = None
            stressed_ratio = None
        if base_ratio is not None:
            base_min = base_ratio if base_min is None else min(base_min, base_ratio)
        if stressed_ratio is not None:
            stressed_min = stressed_ratio if stressed_min is None else min(stressed_min, stressed_ratio)
    plan["projected_cet1_bps_9q"] = base_min
    plan["stressed_min_cet1_bps_9q"] = stressed_min


def baseline_cet1_ratio_bps(plan: dict) -> int | None:
    cet1 = plan.get("baseline_cet1_cents")
    rwa = plan.get("baseline_rwa_cents")
    if cet1 is None or rwa is None or rwa == 0:
        return None
    return (cet1 * BPS_DENOMINATOR) // rwa


def stress_floor_required_bps(plan: dict) -> int:
    """Floor stressed_min must meet at regulator_approve:
    max(PCA_ADEQUATE_CET1_BPS + SCB_FLOOR_BPS, baseline_cet1_ratio - stressed_min)."""
    stressed_min = plan.get("stressed_min_cet1_bps_9q") or 0
    base_ratio = baseline_cet1_ratio_bps(plan)
    drop = (base_ratio - stressed_min) if base_ratio is not None else 0
    return max(PCA_ADEQUATE_CET1_BPS + SCB_FLOOR_BPS, drop)


def refresh_plan_baseline(plan: dict, bank: dict) -> None:
    """Refresh baseline_* from the baseline period's accepted call report."""
    period = reporting_periods.get(plan.get("baseline_period_id") or "")
    if period is None:
        return
    accepted = [
        r for r in call_reports.values()
        if r["reporting_period_id"] == period["id"] and r["status"] == "ACCEPTED"
    ]
    if not accepted:
        return
    accepted.sort(key=lambda r: (r.get("accepted_at") or "", r.get("_seq", 0)))
    rep = accepted[-1]
    plan["baseline_cet1_cents"] = rep.get("cet1_cents")
    plan["baseline_t1_cents"] = rep.get("tier1_cents")
    plan["baseline_total_capital_cents"] = rep.get("total_capital_cents")
    plan["baseline_rwa_cents"] = rep.get("rwa_cents")


# ---------------------------------------------------------------------------
# Maximum distributable amount (maximum_distributable_amount)
# ---------------------------------------------------------------------------

def gross_capacity_cents(bank: dict) -> int:
    """min(PCA capacity, stress capacity) before subtracting pending."""
    if bank["pca_bucket"] not in PCA_PASSING:
        return 0
    rep = latest_accepted_report(bank)
    if rep is None:
        pca_capacity = 0
        rwa = 0
    else:
        rwa = rep.get("rwa_cents") or 0
        candidates = []
        for metric, field in (("CET1", "cet1_ratio_bps"), ("TIER1", "tier1_ratio_bps"),
                              ("TOTAL", "total_ratio_bps"), ("LEVERAGE", "leverage_ratio_bps")):
            ratio = rep.get(field)
            if ratio is not None:
                candidates.append((ratio, PCA_ADEQUATE_FLOOR[metric]))
        if not candidates:
            pca_capacity = 0
        else:
            min_ratio, floor = min(candidates, key=lambda t: t[0])
            pca_capacity = max(0, ((min_ratio - floor) * rwa) // BPS_DENOMINATOR)
    eff_plans = [
        p for p in capital_plans.values()
        if p["bank_id"] == bank["id"] and p["status"] == "EFFECTIVE"
    ]
    if not eff_plans or bank.get("stressed_capital_buffer_bps") is None:
        stress_capacity = 0
    else:
        eff_plans.sort(key=lambda p: p.get("_seq", 0))
        plan = eff_plans[-1]
        stressed_min = plan.get("stressed_min_cet1_bps_9q")
        if stressed_min is None:
            stress_capacity = 0
        else:
            headroom = stressed_min - (PCA_ADEQUATE_CET1_BPS + bank["stressed_capital_buffer_bps"])
            stress_capacity = max(0, (headroom * rwa) // BPS_DENOMINATOR)
    return max(0, min(pca_capacity, stress_capacity))


def recompute_mdba(bank: dict) -> None:
    if bank["pca_bucket"] not in PCA_PASSING:
        bank["mdba_cents"] = 0
        return
    cap = gross_capacity_cents(bank)
    bank["mdba_cents"] = max(0, cap - bank.get("pending_distribution_cents", 0))


# ---------------------------------------------------------------------------
# T2 capacity headroom (t2_capacity_headroom)
# ---------------------------------------------------------------------------

def t2_headroom_cents(bank: dict) -> int:
    rep = latest_accepted_report(bank)
    rwa = (rep.get("rwa_cents") or 0) if rep else 0
    cap = (rwa * T2_CAP_BPS_OF_RWA) // BPS_DENOMINATOR
    t2_outstanding = 0
    for inst in capital_instruments.values():
        if (inst["bank_id"] == bank["id"] and inst["status"] == "OUTSTANDING"
                and inst["instrument_class"] == "T2"):
            t2_outstanding += inst.get("regulatory_capital_cents") or 0
    return max(0, cap - t2_outstanding)


def refresh_open_issuance_headrooms(bank: dict) -> None:
    headroom = t2_headroom_cents(bank)
    for s in sub_debt_issuances.values():
        if s["bank_id"] == bank["id"] and s["status"] in ("PROPOSED", "APPROVED", "PRICED"):
            if s.get("t2_capacity_headroom_cents") != headroom:
                s["t2_capacity_headroom_cents"] = headroom
                touch(s)


# ---------------------------------------------------------------------------
# Distribution cascades
# ---------------------------------------------------------------------------

def release_distribution_reservation(d: dict, bank: dict) -> None:
    reserved = d.get("capacity_reserved_cents") or 0
    if reserved:
        bank["pending_distribution_cents"] = max(0, bank.get("pending_distribution_cents", 0) - reserved)
    d["capacity_reserved_cents"] = 0


def expire_over_reserved_distributions(bank: dict) -> None:
    """Acceptance cascade: expire APPROVED_NOT_EXECUTED requests whose
    reservation exceeds the bank's new gross capacity."""
    cap = gross_capacity_cents(bank)
    reqs = [
        d for d in distribution_requests.values()
        if d["bank_id"] == bank["id"] and d["status"] == "APPROVED_NOT_EXECUTED"
    ]
    reqs.sort(key=lambda d: d.get("_seq", 0))
    for d in reqs:
        if (d.get("capacity_reserved_cents") or 0) > cap:
            release_distribution_reservation(d, bank)
            d["status"] = "EXPIRED"
            touch(d)
    recompute_mdba(bank)


def withdraw_plan_distributions(plan: dict, bank: dict) -> None:
    for d in distribution_requests.values():
        if d["capital_plan_id"] != plan["id"]:
            continue
        if d["status"] in ("PROPOSED", "APPROVED_NOT_EXECUTED"):
            if d["status"] == "APPROVED_NOT_EXECUTED":
                release_distribution_reservation(d, bank)
            d["status"] = "WITHDRAWN"
            touch(d)
    recompute_mdba(bank)


def supersede_plan(plan: dict, bank: dict) -> None:
    if plan["status"] in ("SUPERSEDED",):
        return
    plan["status"] = "SUPERSEDED"
    touch(plan)
    withdraw_plan_distributions(plan, bank)


# ---------------------------------------------------------------------------
# Acceptance cascade (original + amendment)
# ---------------------------------------------------------------------------

def run_acceptance_cascade(bank: dict, period: dict, report: dict, amendment: bool) -> None:
    # 1. PCA bucket recompute + threshold events
    old_bucket = bank["pca_bucket"]
    metric_buckets = classify_bank(report)
    for metric in ("CET1", "TIER1", "TOTAL", "LEVERAGE"):
        new_b = metric_buckets[metric]
        if new_b != old_bucket:
            event = {
                "bank_id": bank["id"],
                "call_report_id": report["id"],
                "metric": metric,
                "ratio_bps_observed": report.get({
                    "CET1": "cet1_ratio_bps", "TIER1": "tier1_ratio_bps",
                    "TOTAL": "total_ratio_bps", "LEVERAGE": "leverage_ratio_bps",
                }[metric]),
                "bucket_before": old_bucket,
                "bucket_after": new_b,
                "breached": PCA_ORDER[new_b] > PCA_ORDER[old_bucket],
            }
            stamp_new(event)
            del event["updated_at"]
            del event["version"]
            pca_threshold_events[event["id"]] = event
    bank["pca_bucket"] = worst_bucket(metric_buckets)
    bank["pca_bucket_as_of_period_id"] = period["id"]

    # 2. MDBA recompute
    recompute_mdba(bank)

    if not amendment:
        # 3. Expire over-reserved approved distributions
        expire_over_reserved_distributions(bank)
        # 4. Refresh T2 headroom on open issuances
        refresh_open_issuance_headrooms(bank)
        # 5. Refresh baseline on DRAFT / BOARD_REVIEW plans for this period
        for plan in capital_plans.values():
            if (plan["bank_id"] == bank["id"] and plan.get("baseline_period_id") == period["id"]
                    and plan["status"] in ("DRAFT", "BOARD_REVIEW")):
                refresh_plan_baseline(plan, bank)
                touch(plan)
    else:
        # Amendment cascade (harsher mode): all non-SUPERSEDED plans on this
        # baseline get refreshed, recomputed, and possibly superseded.
        for plan in capital_plans.values():
            if (plan["bank_id"] != bank["id"] or plan.get("baseline_period_id") != period["id"]
                    or plan["status"] == "SUPERSEDED"):
                continue
            refresh_plan_baseline(plan, bank)
            compute_plan_projections(plan, bank)
            stressed_min = plan.get("stressed_min_cet1_bps_9q")
            base_min = plan.get("projected_cet1_bps_9q")
            below_floor = False
            if stressed_min is not None and stressed_min < stress_floor_required_bps(plan):
                below_floor = True
            if base_min is not None and base_min < PCA_ADEQUATE_CET1_BPS:
                below_floor = True
            if below_floor:
                supersede_plan(plan, bank)
            else:
                touch(plan)
        refresh_open_issuance_headrooms(bank)
        recompute_mdba(bank)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_bank(b: dict) -> dict:
    out = public(b)
    return out


def ser_period(p: dict) -> dict:
    out = public(p)
    due = p.get("_filing_due_dt")
    out["filing_due_at"] = fmt_dt(due) if due else None
    return out


def ser_instrument(i: dict) -> dict:
    out = public(i)
    md = i.get("_maturity_date")
    out["maturity_date"] = md.isoformat() if md else None
    return out


def ser_exposure(e: dict) -> dict:
    return public(e)


def ser_report(r: dict) -> dict:
    return public(r)


def ser_edit(e: dict) -> dict:
    return public(e)


def ser_scenario(s: dict) -> dict:
    return public(s)


def ser_plan(p: dict) -> dict:
    out = public(p)
    out["proposed_distributions_cents"] = proposed_distributions_cents(p)
    return out


def ser_distribution(d: dict) -> dict:
    out = public(d)
    pd = d.get("_proposed_payment_date")
    out["proposed_payment_date"] = pd.isoformat() if pd else None
    return out


def ser_issuance(s: dict) -> dict:
    out = public(s)
    td = s.get("_target_settlement_date")
    out["target_settlement_date"] = td.isoformat() if td else None
    return out


def ser_pca_event(e: dict) -> dict:
    return public(e)


def ser_icaap(d: dict) -> dict:
    return public(d)
