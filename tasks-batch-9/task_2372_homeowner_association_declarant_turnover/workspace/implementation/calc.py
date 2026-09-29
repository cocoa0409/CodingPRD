"""Calculation rules (SCAFFOLD §1.3 / PRD §3).

Every formula is implemented in the pinned order the PRD states; money is
integer cents and percentages are two-decimal round-half-up values.
"""
from decimal import Decimal

import constants
import util
from db import db, ordered


# ------------------------------------------------------------ lookup helpers ---
def lots_of(association_id):
    return ordered([l for l in db.lots.values() if l["association_id"] == association_id])


def components_of(association_id):
    return ordered(
        [c for c in db.components.values() if c["association_id"] == association_id]
    )


def claims_of(association_id):
    return ordered(
        [c for c in db.defect_claims.values() if c["association_id"] == association_id]
    )


def claims_of_component(component_id):
    return ordered(
        [c for c in db.defect_claims.values() if c["component_id"] == component_id]
    )


def contracts_of(association_id):
    return ordered(
        [c for c in db.vendor_contracts.values() if c["association_id"] == association_id]
    )


def studies_of(association_id):
    return ordered(
        [s for s in db.reserve_studies.values() if s["association_id"] == association_id]
    )


def schedules_of(association_id):
    return ordered(
        [s for s in db.assessment_schedules.values()
         if s["association_id"] == association_id]
    )


def entries_of(association_id):
    return ordered(
        [e for e in db.subsidy_entries.values() if e["association_id"] == association_id]
    )


def engagements_of(association_id):
    return ordered(
        [e for e in db.audit_engagements.values()
         if e["association_id"] == association_id]
    )


def records_items_of(turnover_case_id):
    return ordered(
        [i for i in db.records_items.values()
         if i["turnover_case_id"] == turnover_case_id]
    )


def directors_of(turnover_case_id):
    return ordered(
        [d for d in db.directors.values() if d["turnover_case_id"] == turnover_case_id]
    )


def case_for_association(association_id):
    for case in ordered(list(db.turnover_cases.values())):
        if case["association_id"] == association_id:
            return case
    return None


def adopted_study(association_id):
    for study in studies_of(association_id):
        if study["status"] == "ADOPTED":
            return study
    return None


def adopted_schedule(association_id):
    for schedule in schedules_of(association_id):
        if schedule["status"] == "ADOPTED":
            return schedule
    return None


# -------------------------------------------------- sold_lot_percentage (§3.1) ---
def apply_sold_lot_percentage(association):
    closed = [l for l in lots_of(association["id"]) if l["sale_status"] == "CLOSED"]
    association["sold_lot_count"] = len(closed)
    association["sold_lot_pct"] = float(
        util.pct_half_up(len(closed), association["total_planned_lots"])
    )


# ------------------------------------------ subsidy_receivable_balance (§3.6) ---
def apply_subsidy_receivable(association):
    accrual = 0
    payment = 0
    for entry in entries_of(association["id"]):
        if entry["status"] != "POSTED":
            continue
        if entry["direction"] == "ACCRUAL":
            accrual += entry["amount_cents"]
        elif entry["direction"] == "PAYMENT":
            payment += entry["amount_cents"]
    association["subsidy_receivable_cents"] = accrual - payment


# ------------------------------------------------- claim reserve pool (§3.8) ---
def apply_claim_pool(association):
    committed = 0
    for claim in claims_of(association["id"]):
        if claim["status"] == "RESERVED":
            committed += claim["reserved_amount_cents"]
    association["reserve_claim_committed_cents"] = committed
    association["reserve_claim_available_cents"] = (
        association["reserve_claim_pool_cents"] - committed
    )


# ----------------------------------------- audit_unreconciled_delta (§3.6) ---
def audit_snapshot(engagement):
    """In-window receivable frozen at issuance."""
    start = util.parse_dt(engagement["period_start"])
    end = util.parse_dt(engagement["period_end"])
    low = util.month_of(start)
    high = util.month_of(end)
    accrual = 0
    payment = 0
    for entry in entries_of(engagement["association_id"]):
        if entry["status"] != "POSTED":
            continue
        month = entry["period_month"]
        if not (low <= month <= high):
            continue
        if entry["direction"] == "ACCRUAL":
            accrual += entry["amount_cents"]
        elif entry["direction"] == "PAYMENT":
            payment += entry["amount_cents"]
    return accrual - payment


def audit_delta(engagement, association):
    return (
        association["subsidy_receivable_cents"]
        - engagement["audited_receivable_snapshot_cents"]
    )


# --------------------------------------- defect_claim_reserve_amount (§3.8) ---
def claim_reserve_amounts(claim, valuation_basis):
    if valuation_basis == "REPAIR_COST":
        subtotal = claim["repair_cost_estimate_cents"]
    else:
        subtotal = claim["diminution_value_cents"]
    # (1) subtotal  (2) tier from the subtotal alone  (3) fee  (4) total
    if subtotal < constants.CLAIM_FEE_TIER_1_CEILING_CENTS:
        rate = constants.CLAIM_FEE_TIER_1_RATE
    elif subtotal < constants.CLAIM_FEE_TIER_2_CEILING_CENTS:
        rate = constants.CLAIM_FEE_TIER_2_RATE
    else:
        rate = constants.CLAIM_FEE_TIER_3_RATE
    fee = int(util.round_half_up(Decimal(subtotal) * rate, 0))
    return subtotal, fee, subtotal + fee


# ---------------------------------------- defect_repose_deadline (§3.8) ---
def repose_deadline(component, association):
    raw = component.get("substantial_completion_date")
    base = util.parse_dt(raw) if raw else None
    if base is None:
        return None
    return util.fmt_dt(util.add_years(base, association["statute_of_repose_years"]))


# ------------------------------------- records_transfer_completeness (§3.5) ---
def records_completeness_pct(turnover_case_id):
    required = [i for i in records_items_of(turnover_case_id) if i["required"]]
    if not required:
        return Decimal("100.00")
    accepted = [i for i in required if i["status"] == "ACCEPTED"]
    return util.pct_half_up(len(accepted), len(required))


# ------------------------------------------- governance_seat_ledger (§3.4) ---
def owner_elected_seats_required(case):
    if case["governance_status"] == "DECLARANT_CONTROL":
        return 0
    return util.ceil_div(
        case["total_seats"] * constants.OWNER_CONTROL_SEAT_NUMERATOR,
        constants.OWNER_CONTROL_SEAT_DENOMINATOR,
    )


def apply_seat_ledger(case):
    appointed = 0
    elected = 0
    for director in directors_of(case["id"]):
        if director["status"] != "SEATED":
            continue
        if director["seat_type"] == "DECLARANT_APPOINTED":
            appointed += 1
        elif director["seat_type"] == "OWNER_ELECTED":
            elected += 1
    case["declarant_appointed_seats"] = appointed
    case["owner_elected_seats"] = elected
    case["vacant_seats"] = case["total_seats"] - (appointed + elected)
    case["owner_elected_seats_required"] = owner_elected_seats_required(case)


# ------------------------------------- turnover_posture_derivation (§2.8) ---
def derive_posture(case):
    governance = case["governance_status"]
    financial = case["financial_status"]
    if governance == "DECLARANT_CONTROL" and financial == "SUBSIDY_ACTIVE":
        posture = "DECLARANT_CONTROL_OPEN"
    elif governance == "OWNER_CONTROL" and financial == "SETTLED":
        posture = "SETTLED_LOCKED"
    elif governance == "OWNER_CONTROL":
        posture = "OWNER_CONTROL_OPEN"
    else:
        posture = "TRANSITION_RESTRICTED"
    case["turnover_posture"] = posture
    return posture


# -------------------------------------- reserve_funding_adequacy (§3.7) ---
def funded_components(association_id):
    return [
        c for c in components_of(association_id)
        if c["build_status"] == "COMPLETE" and c["conveyance_status"] == "CONVEYED"
    ]


def apply_reserve_adequacy(study, association, method):
    funded = funded_components(association["id"])
    fully_funded = 0
    for component in funded:
        life = component["useful_life_years"]
        age = min(component["effective_age_years"], life)
        fully_funded += (component["replacement_cost_cents"] * age) // life

    pool = association["reserve_pool_cents"]
    if fully_funded == 0:
        percent_funded = Decimal("0.00")
    else:
        percent_funded = util.pct_half_up(pool, fully_funded)

    study["evaluated_method"] = method
    study["component_count"] = len(funded)
    study["fully_funded_balance_cents"] = fully_funded
    study["percent_funded"] = float(percent_funded)

    if method == "COMPONENT_FULL_FUNDING":
        if fully_funded == 0:
            study["adequacy_verdict"] = "UNDETERMINED"
            study["recommended_annual_contribution_cents"] = 0
            study["min_projected_balance_cents"] = 0
        else:
            if percent_funded >= constants.PERCENT_FUNDED_ADEQUATE_PCT:
                verdict = "ADEQUATE"
            elif percent_funded >= constants.PERCENT_FUNDED_MARGINAL_PCT:
                verdict = "MARGINAL"
            else:
                verdict = "DEFICIENT"
            study["adequacy_verdict"] = verdict
            gap = fully_funded - pool
            study["recommended_annual_contribution_cents"] = max(
                0, util.ceil_div(gap, constants.FFB_RECOVERY_YEARS)
            )
            study["min_projected_balance_cents"] = 0
        return

    # ---- CASH_FLOW year-walk; year 0 participates in the minimum ----
    planned = study["planned_annual_contribution_cents"]
    projected = study["projected_annual_expenditure_cents"]
    balance = pool
    minimum = pool
    for year in range(1, constants.CASH_FLOW_PROJECTION_YEARS + 1):
        expenditure = (
            projected * (100 + constants.CASH_FLOW_ESCALATION_PCT_PER_YEAR * year)
        ) // 100
        balance = balance + planned - expenditure
        minimum = min(minimum, balance)
    study["min_projected_balance_cents"] = minimum
    if minimum >= 0:
        study["adequacy_verdict"] = "ADEQUATE"
    elif minimum >= -constants.CASH_FLOW_MARGINAL_FLOOR_CENTS:
        study["adequacy_verdict"] = "MARGINAL"
    else:
        study["adequacy_verdict"] = "DEFICIENT"
    shortfall = max(0, -minimum)
    study["recommended_annual_contribution_cents"] = planned + util.ceil_div(
        shortfall, constants.CASH_FLOW_PROJECTION_YEARS
    )


# ------------------------------------------- assessment_reforecast (§3.9) ---
def apply_assessment_reforecast(schedule, association):
    billable = [
        l for l in lots_of(association["id"])
        if l["sale_status"] in ("CLOSED", "UNDER_CONTRACT")
    ]
    billable_count = len(billable)
    schedule["billable_lot_count"] = billable_count

    study = adopted_study(association["id"])
    reserve_contribution = (
        study["recommended_annual_contribution_cents"] if study else 0
    )
    schedule["reserve_contribution_cents"] = reserve_contribution

    subsidised_months = 0
    end_raw = association.get("subsidy_end_date")
    end_dt = util.parse_dt(end_raw) if end_raw else None
    if end_dt is not None:
        end_month = util.month_of(end_dt)
        for month in range(1, 13):
            label = "%04d-%02d" % (schedule["fiscal_year"], month)
            if label < end_month:
                subsidised_months += 1
    subsidy_offset = association["declarant_monthly_subsidy_cents"] * subsidised_months
    schedule["subsidy_offset_cents"] = subsidy_offset

    annual_requirement = (
        schedule["projected_operating_cost_cents"] + reserve_contribution - subsidy_offset
    )
    schedule["annual_requirement_cents"] = annual_requirement

    # ROUNDING ORDER — per-lot first, then multiply back up.
    if billable_count > 0:
        per_lot = util.ceil_div(
            annual_requirement, billable_count * constants.MONTHS_PER_YEAR
        )
    else:
        per_lot = 0
    schedule["per_lot_monthly_assessment_cents"] = per_lot
    annual_total = per_lot * billable_count * constants.MONTHS_PER_YEAR
    schedule["annual_budget_total_cents"] = annual_total
    schedule["residual_cents"] = annual_total - annual_requirement

    prior = adopted_schedule(association["id"])
    if prior is None or prior["per_lot_monthly_assessment_cents"] == 0:
        increase = Decimal("0.00")
    else:
        increase = util.round_half_up(
            Decimal(100)
            * Decimal(per_lot - prior["per_lot_monthly_assessment_cents"])
            / Decimal(prior["per_lot_monthly_assessment_cents"]),
            2,
        )
    schedule["increase_pct_vs_prior"] = float(increase)
    schedule["owner_vote_required"] = increase > constants.ASSESSMENT_INCREASE_CAP_PCT
