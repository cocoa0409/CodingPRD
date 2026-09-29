"""Calculation rules (SCAFFOLD 1.3 / PRD 3.x).  Integer cents, integer basis points.

None of these helpers bumps a version: routes and cascades own `db.touch`, so each
mutated row's `version` moves exactly once per request.
"""
from datetime import timedelta
from decimal import Decimal

import db
import util

# ------------------------------------------------------------------ constants
BANKING_YEARS_CAP = 20
MIN_QUALIFYING_SUBSCORE = 50
MIN_ORGANIZERS = 5
MIN_INDEPENDENT_ORGANIZERS = 3
AFFILIATION_CONCENTRATION_DIVISOR = 2
MIN_MANAGEMENT_COMPOSITE_SCORE = Decimal("70.00")
DE_NOVO_FLOOR_LEVERAGE_BPS = 800
STRESS_YEARS = 3
CONCENTRATION_TRIP_BPS = 6500
REQUIRED_LEVERAGE_CEILING_BPS = 1200
BREACH_ADD_ON_BPS_PER_SCENARIO = 25
ORG_EXPENSE_REIMBURSEMENT_CAP_PCT = Decimal("0.05")
MAX_INFO_ROUNDS = 3
EXAM_BUFFER_HOURS = 48
MAX_PASSING_FINDINGS = 3
MAX_CONVERSION_WINDOW_HOURS = Decimal("72.00")
MAX_CONCURRENT_CONVERSIONS = 2
DEVIATION_APPROVAL_THRESHOLD_BPS = 1000
DEVIATION_ESCALATION_THRESHOLD_BPS = 2500
SUPERVISION_YEARS = 3
DAYS_PER_SUPERVISION_YEAR = 365
MIN_OPENING_CAPITAL_CENTS = 2000000000
MIN_CRITICAL_DUE_DILIGENCE_SCORE = 70

KEY_OFFICER_ROLES = ("PROPOSED_CEO", "PROPOSED_CFO", "PROPOSED_CRO", "PROPOSED_CCO")
REQUIRED_POLICY_DOMAINS = (
    "LENDING",
    "COMPLIANCE_BSA_AML",
    "INFORMATION_SECURITY",
    "RISK_MANAGEMENT",
)
GOOD_QUALIFICATION = ("QUALIFIED", "WAIVER_GRANTED")
BASE_REQUIRED_BPS = {
    "NATIONAL": 800,
    "STATE_MEMBER": 850,
    "STATE_NONMEMBER": 900,
}


# ------------------------------------------------------------------ selectors
def organizers_of(group_id):
    return [r for r in db.all_rows("organizers") if r["group_id"] == group_id]


def plans_of(group_id):
    return [r for r in db.all_rows("plans") if r["group_id"] == group_id]


def scenarios_of(plan_id):
    return [r for r in db.all_rows("scenarios") if r["business_plan_id"] == plan_id]


def raises_of(group_id):
    return [r for r in db.all_rows("raises") if r["group_id"] == group_id]


def subscriptions_of(raise_id):
    return [r for r in db.all_rows("subscriptions") if r["capital_raise_id"] == raise_id]


def filings_of(group_id):
    return [r for r in db.all_rows("filings") if r["group_id"] == group_id]


def conditions_of(filing_id):
    return [r for r in db.all_rows("conditions") if r["filing_id"] == filing_id]


def policies_of(group_id):
    return [r for r in db.all_rows("policies") if r["group_id"] == group_id]


def contracts_of(group_id):
    return [r for r in db.all_rows("contracts") if r["group_id"] == group_id]


def windows_of(contract_id):
    return [r for r in db.all_rows("windows") if r["vendor_contract_id"] == contract_id]


def exams_of(group_id):
    return [r for r in db.all_rows("exams") if r["group_id"] == group_id]


def deviations_of(group_id):
    return [r for r in db.all_rows("deviations") if r["group_id"] == group_id]


def filing_by_authority(group_id, authority):
    for row in filings_of(group_id):
        if row["authority"] == authority:
            return row
    return None


def group_raise(group_id):
    """The group's raise: the live one, else the newest row."""
    rows = raises_of(group_id)
    live = [r for r in rows if r["status"] in ("STRUCTURING", "OPEN", "ESCROW_LOCKED")]
    if live:
        return live[-1]
    return rows[-1] if rows else None


def raise_in(group_id, statuses):
    for row in raises_of(group_id):
        if row["status"] in statuses:
            return row
    return None


# --------------------------------------------- organizer subscore and status
def organizer_qualification_subscore(org):
    years = min(int(org["banking_years"]), BANKING_YEARS_CAP)
    experience = Decimal("0.40") * (Decimal(years) / Decimal(BANKING_YEARS_CAP)) * Decimal(100)
    regulatory = Decimal("0.35") * Decimal(int(org["regulatory_experience_score"]))
    integrity = Decimal("0.25") * (Decimal(100) if org["fingerprint_state"] == "CLEARED" else Decimal(0))
    return util.rhu_int(experience + regulatory + integrity)


def organizer_qualification_status(org):
    if org.get("waiver_granted"):
        return "WAIVER_GRANTED"
    if org["fingerprint_state"] == "FLAGGED" or org["credit_state"] == "ADVERSE":
        return "DISQUALIFIED"
    if org["fingerprint_state"] == "PENDING" or org["credit_state"] == "PENDING":
        return "PENDING"
    if org["qualification_subscore"] < MIN_QUALIFYING_SUBSCORE:
        return "DISQUALIFIED"
    return "QUALIFIED"


def recompute_organizer(org):
    org["qualification_subscore"] = organizer_qualification_subscore(org)
    org["qualification_status"] = organizer_qualification_status(org)
    return org


# ------------------------------------- group composite score and composition
def management_composite_score(group_id):
    eligible = [r for r in organizers_of(group_id) if r["role_on_board"] != "INVESTOR_ONLY"]
    if not eligible:
        return Decimal("0.00")
    subscore_sum = sum(int(r["qualification_subscore"]) for r in eligible)
    return util.round_half_up(Decimal(subscore_sum) / Decimal(len(eligible)), 2)


def recompute_group_derived(group):
    """group_composition_assessment + management_composite_score."""
    members = organizers_of(group["id"])
    group["organizer_count"] = len(members)
    group["independent_organizer_count"] = len([r for r in members if r["is_independent"]])
    counts = {}
    for row in members:
        code = row["affiliation_code"]
        counts[code] = counts.get(code, 0) + 1
    group["max_affiliation_count"] = max(counts.values()) if counts else 0
    group["management_composite_score"] = management_composite_score(group["id"])

    key_roles_filled = set()
    disqualified_count = 0
    for row in members:
        if (row["role_on_board"] in KEY_OFFICER_ROLES
                and row["qualification_status"] in GOOD_QUALIFICATION):
            key_roles_filled.add(row["role_on_board"])
        if row["qualification_status"] == "DISQUALIFIED":
            disqualified_count += 1

    if group["organizer_count"] < MIN_ORGANIZERS:
        group["composition_status"] = "FORMING"
    elif (group["independent_organizer_count"] >= MIN_INDEPENDENT_ORGANIZERS
            and len(key_roles_filled) == 4
            and disqualified_count == 0
            and group["max_affiliation_count"]
            <= group["organizer_count"] // AFFILIATION_CONCENTRATION_DIVISOR):
        group["composition_status"] = "COMPOSITION_MET"
    else:
        group["composition_status"] = "COMPOSITION_DEFICIENT"
    return group


# ------------------------------------------------------ stress leverage path
def stress_leverage_path(plan, scenario, variant):
    capital = int(plan["opening_tier1_capital_cents"])
    ratios = []
    for t in (1, 2, 3):
        if variant == "DYNAMIC_GROWTH":
            assets_t = int(plan["projected_assets_y%d_cents" % t])
            loans_t = int(plan["projected_loans_y%d_cents" % t])
        else:
            assets_t = int(plan["projected_assets_y1_cents"])
            loans_t = int(plan["projected_loans_y1_cents"])
        credit_loss_t = util.rhu_int(
            Decimal(loans_t) * Decimal(int(scenario["credit_loss_rate_bps"])) / Decimal(10000))
        nim_hit_t = util.rhu_int(
            Decimal(assets_t) * Decimal(int(scenario["nim_compression_bps"])) / Decimal(10000))
        overrun_t = int(scenario["expense_overrun_cents"]) if t == 1 else 0
        stressed_ni_t = (int(plan["projected_net_income_y%d_cents" % t])
                         - credit_loss_t - nim_hit_t - overrun_t)
        capital = capital + stressed_ni_t
        ratios.append((capital * 10000) // assets_t)
    min_ratio = min(ratios)
    breach_year = 0
    for index, value in enumerate(ratios, start=1):
        if value < DE_NOVO_FLOOR_LEVERAGE_BPS:
            breach_year = index
            break
    return min_ratio, breach_year


def recompute_scenario(plan, scenario):
    static_min, static_breach = stress_leverage_path(plan, scenario, "STATIC_BALANCE_SHEET")
    dynamic_min, dynamic_breach = stress_leverage_path(plan, scenario, "DYNAMIC_GROWTH")
    scenario["static_min_leverage_ratio_bps"] = static_min
    scenario["static_breach_year_index"] = static_breach
    scenario["dynamic_min_leverage_ratio_bps"] = dynamic_min
    scenario["dynamic_breach_year_index"] = dynamic_breach
    if scenario["scenario_code"] == "BASELINE":
        scenario["governing_variant"] = "STATIC_BALANCE_SHEET"
        scenario["governing_min_leverage_ratio_bps"] = static_min
        scenario["governing_breach_year_index"] = static_breach
    else:
        scenario["governing_variant"] = "DYNAMIC_GROWTH"
        scenario["governing_min_leverage_ratio_bps"] = dynamic_min
        scenario["governing_breach_year_index"] = dynamic_breach
    return scenario


def recompute_plan_aggregates(plan):
    rows = scenarios_of(plan["id"])
    plan["stress_scenario_count"] = len(rows)
    plan["breach_scenario_count"] = len(
        [r for r in rows if r["governing_breach_year_index"] != 0])
    if rows:
        plan["worst_governing_min_leverage_ratio_bps"] = min(
            int(r["governing_min_leverage_ratio_bps"]) for r in rows)
    else:
        plan["worst_governing_min_leverage_ratio_bps"] = 0
    return plan


# ----------------------------------------------------- capital adequacy verdict
def capital_adequacy_verdict(group, plan):
    concentration_bps = ((int(plan["projected_loans_y3_cents"]) * 10000)
                         // int(plan["projected_assets_y3_cents"]))
    if concentration_bps <= CONCENTRATION_TRIP_BPS:
        concentration_add_on_bps = 0
    else:
        concentration_add_on_bps = ((concentration_bps - CONCENTRATION_TRIP_BPS) // 10) * 5
    breach_scenario_count = int(plan["breach_scenario_count"])
    risk_add_on_bps = (BREACH_ADD_ON_BPS_PER_SCENARIO * breach_scenario_count
                       + concentration_add_on_bps)
    base_required_bps = BASE_REQUIRED_BPS.get(group["charter_type"], 900)
    required_leverage_bps = min(
        REQUIRED_LEVERAGE_CEILING_BPS,
        max(base_required_bps, DE_NOVO_FLOOR_LEVERAGE_BPS + risk_add_on_bps),
    )
    worst = int(plan["worst_governing_min_leverage_ratio_bps"])
    verdict = "ADEQUATE" if worst >= required_leverage_bps else "DEFICIENT"
    return {
        "business_plan_id": plan["id"],
        "charter_type": group["charter_type"],
        "base_required_bps": base_required_bps,
        "concentration_bps": concentration_bps,
        "concentration_add_on_bps": concentration_add_on_bps,
        "breach_scenario_count": breach_scenario_count,
        "risk_add_on_bps": risk_add_on_bps,
        "required_leverage_bps": required_leverage_bps,
        "worst_governing_min_leverage_ratio_bps": worst,
        "verdict": verdict,
    }


def governing_plan(group):
    """The plan pinned by the CHARTERING_AUTHORITY filing, else the newest
    SUBMITTED plan of the group (PRD 3.3)."""
    filing = filing_by_authority(group["id"], "CHARTERING_AUTHORITY")
    if filing is not None and filing.get("pinned_business_plan_id"):
        pinned = db.get("plans", filing["pinned_business_plan_id"])
        if pinned is not None and pinned["status"] == "PINNED":
            return pinned
    submitted = [r for r in plans_of(group["id"]) if r["status"] == "SUBMITTED"]
    return submitted[-1] if submitted else None


# --------------------------------------------------- escrow position / release
def recompute_raise(raise_row):
    """escrow_position (both bases) then escrow_release_allocation."""
    subs = subscriptions_of(raise_row["id"])
    subscribed_shares = 0
    pledged = 0
    funded = 0
    refunded = 0
    cleared = 0
    for sub in subs:
        sub["counts_toward_escrow"] = (sub["funding_state"] == "FUNDED"
                                       and sub["clearance_state"] == "CLEARED")
        if sub["funding_state"] in ("PLEDGED", "FUNDED"):
            subscribed_shares += int(sub["shares"])
            pledged += int(sub["amount_cents"])
        if sub["funding_state"] == "FUNDED":
            funded += int(sub["amount_cents"])
        if sub["funding_state"] == "REFUNDED":
            refunded += int(sub["amount_cents"])
        if sub["counts_toward_escrow"]:
            cleared += int(sub["amount_cents"])
    raise_row["subscribed_shares"] = subscribed_shares
    raise_row["pledged_gross_cents"] = pledged
    raise_row["funded_gross_cents"] = funded
    raise_row["refunded_gross_cents"] = refunded
    raise_row["cleared_escrow_cents"] = cleared

    cap = util.rhu_int(ORG_EXPENSE_REIMBURSEMENT_CAP_PCT * Decimal(cleared))
    reimbursement = min(int(raise_row["organizational_expense_claim_cents"]), cap)
    raise_row["projected_reimbursement_cents"] = reimbursement
    raise_row["projected_net_release_cents"] = cleared - reimbursement
    return raise_row


def cleared_subscription_count(raise_row):
    return len([s for s in subscriptions_of(raise_row["id"]) if s["counts_toward_escrow"]])


# -------------------------------------------------- filing condition posture
def recompute_filing_posture(filing):
    conds = conditions_of(filing["id"])
    filing["condition_total_count"] = len(conds)
    filing["settled_condition_count"] = len(
        [c for c in conds if c["status"] in ("SATISFIED", "WAIVED")])
    filing["open_blocking_condition_count"] = len(
        [c for c in conds
         if c["is_pre_opening_blocking"]
         and c["status"] in ("OPEN", "EVIDENCE_SUBMITTED", "FAILED")])
    filing["pre_opening_clearance"] = (
        filing["status"] in ("CONDITIONALLY_APPROVED", "FINAL_APPROVED")
        and filing["open_blocking_condition_count"] == 0)
    return filing


# ------------------------------------------------------- interval occupations
def exam_buffer_end(window_end):
    return window_end + timedelta(hours=EXAM_BUFFER_HOURS)


def exam_window_conflict(group_id, new_start, new_buffer_end, exclude_id=None):
    for exam in exams_of(group_id):
        if exclude_id is not None and exam["id"] == exclude_id:
            continue
        if exam["status"] not in ("SCHEDULED", "DEFICIENT", "PASSED"):
            continue
        if new_start < exam["buffer_end_utc"] and exam["window_start_utc"] < new_buffer_end:
            return True
    return False


def window_duration_hours(start, end):
    seconds = Decimal((end - start).total_seconds())
    return util.round_half_up(seconds / Decimal(3600), 2)


def conversion_overlap_count(contract_id, new_start, new_end):
    total = 0
    for window in windows_of(contract_id):
        if window["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        if new_start < window["window_end_utc"] and window["window_start_utc"] < new_end:
            total += 1
    return total


def recompute_contract_windows(contract):
    contract["active_window_count"] = len(
        [w for w in windows_of(contract["id"]) if w["status"] in ("RESERVED", "CONFIRMED")])
    return contract


# ----------------------------------------------------- deviations / supervision
def supervision_year_index(group, now):
    if group.get("supervision_started_at") is None:
        return 0
    elapsed_days = int((now - group["supervision_started_at"]).total_seconds()) // 86400
    raw_index = elapsed_days // DAYS_PER_SUPERVISION_YEAR + 1
    return raw_index if raw_index <= SUPERVISION_YEARS else 0


def recompute_supervision(group):
    group["supervision_year_index"] = supervision_year_index(group, db.clock())
    return group


def deviation_baseline(plan, metric, year_index):
    if metric == "BRANCH_COUNT":
        return int(plan["projected_branch_count"])
    field = {
        "ASSET_GROWTH": "projected_assets_y%d_cents",
        "LOAN_GROWTH": "projected_loans_y%d_cents",
        "DEPOSIT_GROWTH": "projected_deposits_y%d_cents",
    }[metric]
    index = year_index if year_index in (1, 2, 3) else 1
    return int(plan[field % index])


def deviation_magnitude(plan, metric, actual_value, year_index):
    baseline = deviation_baseline(plan, metric, year_index)
    if baseline == 0:
        deviation_bps = 0 if int(actual_value) == 0 else DEVIATION_ESCALATION_THRESHOLD_BPS
    else:
        deviation_bps = (abs(int(actual_value) - baseline) * 10000) // abs(baseline)
    return baseline, deviation_bps, deviation_bps >= DEVIATION_APPROVAL_THRESHOLD_BPS
