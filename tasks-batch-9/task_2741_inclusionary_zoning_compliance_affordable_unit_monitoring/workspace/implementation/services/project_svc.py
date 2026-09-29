"""Project obligation equivalents, compliance posture and the project-side
cascades. Every recomputation of a derived project attribute counts as one
mutation of the project row."""

import db
from services import calc, lookup

FEE_COVERING_STATES = ("ASSESSED", "PARTIALLY_PAID", "DELINQUENT", "PAID")
OPEN_FEE_STATES = ("ASSESSED", "PARTIALLY_PAID", "DELINQUENT")


def onsite_equivalents(project_id):
    """Every unit not WITHDRAWN counts as one whole unit equivalent."""
    return calc.BPS * sum(
        1 for unit in lookup.project_units(project_id)
        if unit.get("occupancy_status") != "WITHDRAWN"
    )


def fee_covered_equivalents(project_id):
    total = 0
    for fee in lookup.project_fees(project_id):
        if fee.get("state") in FEE_COVERING_STATES:
            total += int(fee.get("unit_equivalent_bps") or 0)
    return total


def compliance_posture(project):
    """First matching clause wins (PRD 3.9)."""
    if project.get("state") == "DRAFT":
        return "PENDING"
    if project.get("applicability") == "EXEMPT":
        return "NOT_APPLICABLE"
    for unit in lookup.project_units(project["id"]):
        if unit.get("occupancy_status") == "WITHDRAWN":
            continue
        if unit.get("compliance_status") == "OUT_OF_COMPLIANCE":
            return "UNDER_ENFORCEMENT"
    onsite = int(project.get("onsite_unit_equivalents_bps") or 0)
    fee_covered = int(project.get("fee_covered_equivalents_bps") or 0)
    if onsite + fee_covered < int(project.get("total_obligation_bps") or 0):
        return "DEFICIENT"
    if fee_covered > 0:
        return "COMPLIANT_BY_FEE"
    return "COMPLIANT_ONSITE"


def recompute_equivalents(project):
    project["onsite_unit_equivalents_bps"] = onsite_equivalents(project["id"])
    project["fee_covered_equivalents_bps"] = fee_covered_equivalents(project["id"])


def refresh(project, bump=True):
    """Recompute both equivalents and the posture, then record the mutation."""
    recompute_equivalents(project)
    project["compliance_posture"] = compliance_posture(project)
    if bump:
        db.touch(project)
    return project


def refresh_posture(project, bump=True):
    """Recompute only the posture (the equivalents are untouched)."""
    project["compliance_posture"] = compliance_posture(project)
    if bump:
        db.touch(project)
    return project


def new_project_row(name, developer_user_id, zoning_district, total_units, approval_date):
    return {
        "name": name,
        "developer_user_id": developer_user_id,
        "zoning_district": zoning_district,
        "total_units": total_units,
        "approval_date": approval_date,
        "ordinance_id": None,
        "state": "DRAFT",
        "applicability": "PENDING",
        "required_affordable_units": 0,
        "fractional_obligation_bps": 0,
        "compliance_path": None,
        "onsite_unit_equivalents_bps": 0,
        "fee_covered_equivalents_bps": 0,
        "total_obligation_bps": 0,
        "compliance_posture": "PENDING",
        "screened_at": None,
        "screen_count": 0,
    }


def new_unit_row(project_id, agreement_id, unit_number, bedrooms, sqft, tenure,
                 affordability_level_bps, market_comparable_sqft):
    return {
        "project_id": project_id,
        "agreement_id": agreement_id,
        "unit_number": unit_number,
        "bedrooms": bedrooms,
        "sqft": sqft,
        "tenure": tenure,
        "affordability_level_bps": affordability_level_bps,
        "market_comparable_sqft": market_comparable_sqft,
        "occupancy_status": "PLANNED",
        "compliance_status": "COMPLIANT",
        "restriction_state": "NOT_RECORDED",
        "occupant_household_id": None,
        "current_rent_cents": 0,
        "max_allowed_rent_cents": 0,
        "original_purchase_price_cents": 0,
        "ami_income_at_purchase_cents": 0,
        "restriction_recorded_at": None,
        "last_refinance_balance_cents": 0,
        "approved_refinance_cap_cents": 0,
        "withdrawn_reason": None,
    }
