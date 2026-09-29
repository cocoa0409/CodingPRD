"""The thirteen calculations of SCAFFOLD 1.3 / PRD 3.

All money is integer cents. Every product is rounded with round_half_up at
exactly the point the formula pins it; caps and ratios use floor.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from services.constants import (
    APPLICANT_TYPE_POINTS,
    DELINQUENCY_POINTS_PER_REPORT,
    EQUIPMENT_DAILY_HOURS_CAP,
    FACILITY_POINTS_PER_FACILITY,
    FRINGE_CAP_PCT,
    MIN_COMPETITIVE_BIDS,
    MITIGATION_CAP_PCT_LARGE,
    MITIGATION_CAP_PCT_SMALL,
    OVERTIME_MULTIPLIER,
    PER_CAPITA_INDICATOR_CENTS,
    SIMPLIFIED_ACQUISITION_THRESHOLD_CENTS,
    SMALL_PURCHASE_CEILING_CENTS,
    TIER_HIGH_MIN,
    TIER_MEDIUM_MIN,
    W_SECOND,
    W_THIRD,
    W_TYPE,
)


def dec(value):
    """Exact Decimal from an int/float/Decimal without binary artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value):
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# 1. disaster_validated_loss_indicator
# ---------------------------------------------------------------------------

def disaster_validated_loss_indicator(total_validated_loss_cents, population):
    per_capita = floor_int(dec(total_validated_loss_cents) / dec(population)) \
        if population else 0
    return {
        "total_validated_loss_cents": total_validated_loss_cents,
        "per_capita_impact_cents": per_capita,
        "indicator_met": per_capita >= PER_CAPITA_INDICATOR_CENTS,
    }


# ---------------------------------------------------------------------------
# 2. facility_eligibility_screening
# ---------------------------------------------------------------------------

def facility_eligibility_screening(facility, applicant):
    if facility["legal_responsibility_documented"] is False:
        return "INELIGIBLE", "LEGAL_RESPONSIBILITY_NOT_DOCUMENTED"
    if facility["in_active_use"] is False:
        return "INELIGIBLE", "NOT_IN_ACTIVE_USE"
    if applicant is not None and applicant["applicant_type"] == "PRIVATE_NONPROFIT":
        if facility["ownership"] != "PNP_OWNED":
            return "INELIGIBLE", "PNP_MUST_OWN_FACILITY"
        if applicant["tax_exempt_letter_on_file"] is False:
            return "INELIGIBLE", "TAX_EXEMPT_DOCUMENTATION_MISSING"
        if applicant["pnp_service_type"] == "NON_ELIGIBLE":
            return "INELIGIBLE", "PNP_SERVICE_NOT_ELIGIBLE"
    return "ELIGIBLE", None


# ---------------------------------------------------------------------------
# 3. procurement_compliance_review
# ---------------------------------------------------------------------------

def procurement_compliance_review(contract):
    award = contract["award_amount_cents"]
    ctype = contract["contract_type"]
    if ctype == "COST_PLUS_PERCENTAGE_OF_COST":
        return "NONCOMPLIANT", "PROHIBITED_CONTRACT_TYPE"
    if ctype == "TIME_AND_MATERIALS" and award > SMALL_PURCHASE_CEILING_CENTS:
        return "NONCOMPLIANT", "TIME_AND_MATERIALS_CEILING_EXCEEDED"
    if award >= SIMPLIFIED_ACQUISITION_THRESHOLD_CENTS:
        if ctype == "NONCOMPETITIVE" and contract["sole_source_justification_on_file"] is False:
            return "NONCOMPLIANT", "SOLE_SOURCE_UNJUSTIFIED"
        if ctype in ("SEALED_BID", "COMPETITIVE_PROPOSAL") and (
            contract["advertised"] is False
            or contract["bids_received"] < MIN_COMPETITIVE_BIDS
        ):
            return "NONCOMPLIANT", "INADEQUATE_COMPETITION"
    if award >= SMALL_PURCHASE_CEILING_CENTS and contract["debarment_check_completed"] is False:
        return "NONCOMPLIANT", "DEBARMENT_CHECK_MISSING"
    return "COMPLIANT", None


# ---------------------------------------------------------------------------
# 4. cost_line_item_eligible_cost
# ---------------------------------------------------------------------------

def cost_line_item_eligible_cost(line, project, resource, contract, siblings):
    """`siblings` = every other line on the same contract (CONTRACT branch only)."""
    cost_type = line["cost_type"]
    claimed = line["claimed_cents"]

    if cost_type == "FORCE_ACCOUNT_LABOR":
        if resource is not None and resource["employee_type"] == "PERMANENT" \
                and project["work_type"] == "EMERGENCY":
            billable_straight = dec(0)
            reason = "STRAIGHT_TIME_NOT_ELIGIBLE_FOR_EMERGENCY_WORK"
        else:
            billable_straight = dec(line["straight_time_hours"])
            reason = "CLAIM_EXCEEDS_COMPUTED_COST"
        billable_overtime = dec(line["overtime_hours"])
        base_rate = dec(resource["base_hourly_rate_cents"]) if resource else dec(0)
        fringe_pct = dec(resource["fringe_benefit_pct"]) if resource else dec(0)
        straight_cost = round_half_up(billable_straight * base_rate)
        overtime_cost = round_half_up(billable_overtime * base_rate * OVERTIME_MULTIPLIER)
        applied_fringe = fringe_pct if fringe_pct < FRINGE_CAP_PCT else FRINGE_CAP_PCT
        fringe_cost = round_half_up(dec(straight_cost + overtime_cost) * applied_fringe)
        computed = straight_cost + overtime_cost + fringe_cost
        if fringe_pct > FRINGE_CAP_PCT:
            reason = "FRINGE_RATE_CAPPED"

    elif cost_type == "FORCE_ACCOUNT_EQUIPMENT":
        published = resource["published_hourly_rate_cents"] if resource else 0
        schedule = resource["schedule_hourly_rate_cents"] if resource else 0
        applied_rate = published if published < schedule else schedule
        computed = round_half_up(dec(line["equipment_hours"]) * dec(applied_rate))
        reason = "LESSER_OF_RATE_APPLIED" if published > schedule \
            else "CLAIM_EXCEEDS_COMPUTED_COST"

    elif cost_type == "MATERIALS":
        computed = claimed
        reason = "CLAIM_EXCEEDS_COMPUTED_COST"

    else:  # CONTRACT
        if contract is not None and contract["procurement_status"] == "NONCOMPLIANT":
            computed = 0
            reason = "PROCUREMENT_NONCOMPLIANT"
        else:
            award = contract["award_amount_cents"] if contract else 0
            already_allowed = sum(
                other["eligible_cents"] for other in siblings
                if other["review_status"] in ("ALLOWED", "PARTIALLY_ALLOWED")
            )
            headroom = award - already_allowed
            if headroom < 0:
                headroom = 0
            computed = claimed if claimed < headroom else headroom
            reason = "CONTRACT_AWARD_CEILING_REACHED" if headroom < claimed \
                else "CLAIM_EXCEEDS_COMPUTED_COST"

    eligible = computed if computed < claimed else claimed
    if eligible == claimed:
        status = "ALLOWED"
    elif eligible == 0:
        status = "DISALLOWED"
    else:
        status = "PARTIALLY_ALLOWED"
    return eligible, status, (None if status == "ALLOWED" else reason)


# ---------------------------------------------------------------------------
# 5/6. project_review_basis + mitigation_cap_allocation
# ---------------------------------------------------------------------------

def covering_capacity(policies):
    return sum(
        max(0, p["coverage_limit_cents"] - p["deductible_cents"]) for p in policies
    )


def size_class_for(repair_basis_cents, small_project_threshold_cents):
    return "SMALL" if repair_basis_cents < small_project_threshold_cents else "LARGE"


def cap_pct_for(size_class):
    return MITIGATION_CAP_PCT_SMALL if size_class == "SMALL" else MITIGATION_CAP_PCT_LARGE


def mitigation_cap_allocation(repair_basis_cents, mitigation_requested_cents, size_class):
    cap = floor_int(dec(repair_basis_cents) * cap_pct_for(size_class))
    return min(mitigation_requested_cents, cap)


def project_review_basis(project, disaster, reviewed_lines, covering_policies):
    if reviewed_lines:
        repair = sum(line["eligible_cents"] for line in reviewed_lines)
    else:
        repair = project["estimated_repair_cost_cents"]
    capacity = covering_capacity(covering_policies)
    anticipated = min(repair, capacity)
    reduction = max(anticipated, project["settlement_allocated_cents"])
    size_class = size_class_for(repair, disaster["small_project_threshold_cents"])
    return {
        "repair_eligible_cents": repair,
        "anticipated_insurance_cents": anticipated,
        "insurance_reduction_cents": reduction,
        "size_class": size_class,
    }


# ---------------------------------------------------------------------------
# 7. federal_share_obligation
# ---------------------------------------------------------------------------

def federal_share_obligation(repair_eligible_cents, insurance_reduction_cents,
                             mitigation_approved_cents, federal_cost_share_pct):
    net_repair = repair_eligible_cents - insurance_reduction_cents
    if net_repair < 0:
        net_repair = 0
    pct = dec(federal_cost_share_pct)
    repair_share = round_half_up(dec(net_repair) * pct)
    mitigation_share = round_half_up(dec(mitigation_approved_cents) * pct)
    return repair_share + mitigation_share


# ---------------------------------------------------------------------------
# 9. project_eligible_cost
# ---------------------------------------------------------------------------

def project_eligible_cost_provisional(project, disaster, covering_policies):
    repair_basis = project["estimated_repair_cost_cents"]
    anticipated = min(repair_basis, covering_capacity(covering_policies))
    size_class = size_class_for(repair_basis, disaster["small_project_threshold_cents"])
    mitigation = mitigation_cap_allocation(
        repair_basis, project["mitigation_requested_cents"], size_class
    )
    eligible = max(0, repair_basis - anticipated) + mitigation
    return {
        "size_class": size_class,
        "anticipated_insurance_cents": anticipated,
        "mitigation_approved_cents": mitigation,
        "eligible_cost_provisional_cents": eligible,
    }


def project_eligible_cost_final(project, reviewed_lines):
    repair_basis = sum(line["eligible_cents"] for line in reviewed_lines)
    offset = project["settlement_allocated_cents"]
    return max(0, repair_basis - offset) + project["mitigation_approved_cents"]


# ---------------------------------------------------------------------------
# 11. applicant_risk_score
# ---------------------------------------------------------------------------

def _score(applicant_type, second_points, third_points):
    type_points = APPLICANT_TYPE_POINTS.get(applicant_type, 0)
    raw = (W_TYPE * dec(type_points)
           + W_SECOND * dec(second_points)
           + W_THIRD * dec(third_points))
    return round_half_up_2(raw)


def risk_tier(score):
    if score is None:
        return "LOW"
    value = dec(score)
    if value >= TIER_HIGH_MIN:
        return "HIGH"
    if value >= TIER_MEDIUM_MIN:
        return "MEDIUM"
    return "LOW"


def risk_score_screening(applicant, facility_count, has_uninsured_flood_facility):
    second = min(100, FACILITY_POINTS_PER_FACILITY * facility_count)
    third = 100 if has_uninsured_flood_facility else 0
    return _score(applicant["applicant_type"], second, third)


def risk_score_monitoring(applicant):
    second = min(100, DELINQUENCY_POINTS_PER_REPORT * applicant["delinquent_report_count"])
    obligated = applicant["total_obligated_cents"]
    cash = applicant["cash_on_hand_cents"]
    if obligated == 0 and cash > 0:
        third = 100
    else:
        third = min(100, floor_int(dec(100) * dec(cash) / dec(max(1, obligated))))
    return _score(applicant["applicant_type"], second, third)


# ---------------------------------------------------------------------------
# 13. closeout_reconciliation
# ---------------------------------------------------------------------------

def closeout_reconciliation(project, disaster):
    if project["size_class"] == "SMALL":
        return project["federal_share_obligated_cents"], 0
    final_basis = project["eligible_cost_final_cents"] or 0
    net_final = final_basis - project["mitigation_approved_cents"]
    if net_final < 0:
        net_final = 0
    pct = dec(disaster["federal_cost_share_pct"])
    final_share = (round_half_up(dec(net_final) * pct)
                   + round_half_up(dec(project["mitigation_approved_cents"]) * pct))
    return final_share, final_share - project["federal_share_obligated_cents"]


# ---------------------------------------------------------------------------
# labor / equipment interval guards
# ---------------------------------------------------------------------------

def equipment_cap_exceeded(new_days, new_hours, existing):
    """`existing` = [(set_of_utc_dates, hours), ...] for the same resource."""
    for day in new_days:
        total = dec(new_hours)
        for days, hours in existing:
            if day in days:
                total += dec(hours)
        if total > EQUIPMENT_DAILY_HOURS_CAP:
            return True
    return False
