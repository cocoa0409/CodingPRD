"""Business logic: calculations, recompute chains, and cascades."""

from datetime import timedelta, date
from decimal import Decimal

import store
from store import touch
from util import dec, round_half_up

# --- calculation constants (scaffold §1.3) ---
KW_PER_CFM = Decimal("0.20")
SEQ_BASE_PCT = Decimal("0.07")
PRESSURE_SAVINGS_PCT_PER_PSI = Decimal("0.005")
PRESSURE_REDUCTION_CAP_PSI = 20

TIER1_KWH = 100000
TIER1_RATE_CENTS = 7
TIER2_RATE_CENTS = 3
COST_CAP_PCT = Decimal("0.50")
PROGRAM_CAP_CENTS = 20000000

SLA_BASE_HOURS = {"BASIC": 48, "STANDARD": 24, "PREMIUM": 8}
SEVERITY_MULTIPLIER = {"EMERGENCY": 1, "URGENT": 2, "ROUTINE": 4}
SLA_CREDIT_PCT = Decimal("0.05")
SLA_BREACH_SUSPEND_THRESHOLD = 3
CREDIT_TTL_DAYS = 90

MIN_BILL_DAYS = 3
LONG_TERM_DAY = 28
LONG_TERM_RATE_FACTOR = Decimal("0.85")

DEADBAND_PCT = Decimal("0.02")
PAYOUT_CAP_MONTHS = 12

CONTRACT_TERMINAL = {"SUPERSEDED", "EXPIRED", "TERMINATED"}
RETROFIT_APPROVED_OR_LATER = {"APPROVED", "INSTALLED", "COMMISSIONED", "ACCEPTED"}


# ---------------------------------------------------------------------------
# Facility watermark / delinquency / posture / settlement_blocked recompute
# ---------------------------------------------------------------------------

def facility_watermark(facility_id):
    """Max run_hours_total over the facility's non-DECOMMISSIONED compressors."""
    vals = [
        c["run_hours_total"]
        for c in store.compressors.values()
        if c["facility_id"] == facility_id and c["status"] != "DECOMMISSIONED"
    ]
    return max(vals) if vals else 0


def recompute_facility_chain(facility_id):
    """Delinquency -> posture -> certificate settlement_blocked (all atomic)."""
    fac = store.facilities.get(facility_id)
    if fac is None:
        return
    watermark = facility_watermark(facility_id)

    for sched in store.maintenance_schedules.values():
        if sched["facility_id"] != facility_id:
            continue
        due = sched["anchor_run_hours"] + sched["interval_hours"]
        if sched["next_due_run_hours"] != due:
            sched["next_due_run_hours"] = due
            touch(sched)
        delinquent = sched["status"] == "ACTIVE" and watermark >= sched["next_due_run_hours"]
        if sched["is_delinquent"] != delinquent:
            sched["is_delinquent"] = delinquent
            touch(sched)

    any_down = any(
        c["facility_id"] == facility_id and c["status"] == "DOWN"
        for c in store.compressors.values()
    )
    any_delinquent = any(
        s["facility_id"] == facility_id and s["status"] == "ACTIVE" and s["is_delinquent"]
        for s in store.maintenance_schedules.values()
    )
    # precedence pinned: OUTAGE_ACTIVE > MAINTENANCE_DELINQUENT > NORMAL
    if any_down:
        posture = "OUTAGE_ACTIVE"
    elif any_delinquent:
        posture = "MAINTENANCE_DELINQUENT"
    else:
        posture = "NORMAL"
    if fac["posture"] != posture:
        fac["posture"] = posture
        touch(fac)

    blocked = fac["posture"] != "NORMAL"
    for cert in store.guarantee_certificates.values():
        if cert["facility_id"] != facility_id:
            continue
        if cert["settlement_status"] == "PAID":
            continue  # PAID certificates are history; left untouched
        if cert["settlement_blocked"] != blocked:
            cert["settlement_blocked"] = blocked
            touch(cert)


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

def active_contract_of(facility_id):
    for c in store.service_contracts.values():
        if c["facility_id"] == facility_id and c["status"] == "ACTIVE":
            return c
    return None


def latest_nonterminal_contract_of(facility_id):
    candidates = [
        c
        for c in store.service_contracts.values()
        if c["facility_id"] == facility_id and c["status"] not in CONTRACT_TERMINAL
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda c: c["created_at"])
    return candidates[-1]


# ---------------------------------------------------------------------------
# Savings calculations
# ---------------------------------------------------------------------------

def leak_annual_savings(cfm_loss, operating_hours_per_year):
    return round_half_up(dec(cfm_loss) * KW_PER_CFM * Decimal(operating_hours_per_year))


def compute_deemed(case):
    """Deemed = per-tag leak rollup (pre-rounded) + sequencing component."""
    leak_component = 0
    for tag in store.leak_tags.values():
        if tag["status"] != "VERIFIED_CLOSED":
            continue
        survey = store.leak_surveys.get(tag["survey_id"])
        if survey is None or survey["facility_id"] != case["facility_id"]:
            continue
        if survey["status"] != "VERIFIED":
            continue
        leak_component += tag["annual_kwh_savings"] or 0

    project = store.retrofit_projects.get(case["retrofit_project_id"])
    baseline = store.demand_profiles.get(case["baseline_profile_id"])
    if project is None or baseline is None:
        return leak_component
    raw_drop = project["baseline_pressure_psi"] - project["target_pressure_psi"]
    drop = min(raw_drop, PRESSURE_REDUCTION_CAP_PSI)
    pct = SEQ_BASE_PCT + PRESSURE_SAVINGS_PCT_PER_PSI * Decimal(drop)
    sequencing_component = round_half_up(Decimal(baseline["baseline_annual_kwh"]) * pct)
    return leak_component + sequencing_component


def utility_rebate(savings_kwh, project_cost_cents):
    """Tiered amount first, then cost cap and program cap (order pinned)."""
    tiered = TIER1_RATE_CENTS * min(savings_kwh, TIER1_KWH) + TIER2_RATE_CENTS * max(
        0, savings_kwh - TIER1_KWH
    )
    cost_cap = round_half_up(Decimal(project_cost_cents) * COST_CAP_PCT)
    return min(tiered, cost_cap, PROGRAM_CAP_CENTS)


def annualized_kwh(measured_kwh, window_days):
    return round_half_up(Decimal(measured_kwh) * 365 / Decimal(window_days))


def window_days(start, end):
    return (end - start).days + 1  # inclusive both ends


# ---------------------------------------------------------------------------
# Rentals
# ---------------------------------------------------------------------------

def reservation_occupied_interval(reservation):
    """[start_date, effective_end + 1 day turnaround buffer], closed-closed."""
    start = date.fromisoformat(reservation["start_date"])
    if reservation["status"] in ("RETURNED", "INVOICED") and reservation["actual_return_date"]:
        eff_end = date.fromisoformat(reservation["actual_return_date"])
    else:
        eff_end = date.fromisoformat(reservation["end_date"])
    return start, eff_end + timedelta(days=1)


def asset_has_buffered_overlap(asset_id, new_start, new_end):
    for r in store.rental_reservations.values():
        if r["rental_asset_id"] != asset_id:
            continue
        if r["status"] not in ("RESERVED", "ON_RENT", "RETURNED", "INVOICED"):
            continue
        occ_start, occ_end = reservation_occupied_interval(r)
        if new_start <= occ_end and occ_start <= new_end:
            return True
    return False


def select_rental_asset(down_compressor, new_start, new_end):
    """Smallest sufficient AVAILABLE asset with no buffered overlap."""
    eligible = [
        a
        for a in store.rental_assets.values()
        if a["status"] == "AVAILABLE"
        and a["rated_cfm"] >= down_compressor["rated_cfm"]
        and not asset_has_buffered_overlap(a["id"], new_start, new_end)
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda a: (a["rated_cfm"], a["created_at"]))
    return eligible[0]


def rental_actual_bill(daily_rate_cents, start, actual_return):
    actual_days = (actual_return - start).days + 1
    billable = max(actual_days, MIN_BILL_DAYS)
    full_rate_days = min(billable, LONG_TERM_DAY - 1)  # days 1..27 full rate
    discounted_days = max(0, billable - (LONG_TERM_DAY - 1))  # days 28+ at 85%
    amount = dec(daily_rate_cents) * (
        Decimal(full_rate_days) + LONG_TERM_RATE_FACTOR * Decimal(discounted_days)
    )
    return round_half_up(amount)


# ---------------------------------------------------------------------------
# Guarantee certificates
# ---------------------------------------------------------------------------

def guarantee_settlement_figures(cert, measured_kwh):
    """shortfall = max(0, guaranteed - measured - deadband); payout capped."""
    shortfall = max(0, cert["guaranteed_kwh"] - measured_kwh - cert["deadband_kwh"])
    fac = store.facilities[cert["facility_id"]]
    contract = store.service_contracts[cert["contract_id"]]
    payout = round_half_up(Decimal(shortfall) * Decimal(fac["utility_rate_cents_per_kwh"]))
    payout = min(payout, contract["monthly_fee_cents"] * PAYOUT_CAP_MONTHS)
    return shortfall, payout


# ---------------------------------------------------------------------------
# Compressor decommission cascade
# ---------------------------------------------------------------------------

def decommission_cascade(compressor):
    facility_id = compressor["facility_id"]
    cancelled_ids = []
    for project in store.retrofit_projects.values():
        if project["facility_id"] != facility_id:
            continue
        if project["status"] not in ("PROPOSED", "APPROVED", "INSTALLED"):
            continue
        if compressor["id"] not in project["sequence_compressor_ids"]:
            continue
        project["status"] = "CANCELLED"
        touch(project)
        cancelled_ids.append(project["id"])
    if cancelled_ids:
        for case in store.savings_cases.values():
            if case["retrofit_project_id"] not in cancelled_ids:
                continue
            if case["savings_status"] in ("DRAFT", "MODELED") and not case["retrofit_stale"]:
                case["retrofit_stale"] = True
                touch(case)
    recompute_facility_chain(facility_id)
