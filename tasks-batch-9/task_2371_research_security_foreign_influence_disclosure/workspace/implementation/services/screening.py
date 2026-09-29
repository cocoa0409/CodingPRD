"""Restricted-entity screening of subaward counterparties (PRD 3.6)."""

import db
from services import derive
from services import enums as E


def screen_outcome(organization, variant):
    """Resolve (designation, matched_org_id, depth, outcome, points)."""
    if variant == "DIRECT_MATCH":
        designation = (organization.get("own_designation") or "NONE") \
            if organization else "NONE"
        depth = 0
        matched_id = organization["id"] if organization else None
    else:
        designation, depth = derive.effective_designation(organization)
        matched = derive.chain_member_at(organization, depth) \
            if organization else None
        matched_id = matched["id"] if matched else None

    strictness = E.DESIGNATION_STRICTNESS[designation]
    if strictness >= E.BLOCK_STRICTNESS:
        outcome = "BLOCKED"
        points = E.BLOCK_BASE_POINTS + E.STRICTNESS_POINT_STEP * strictness
    elif strictness == 1:
        outcome = "FLAGGED"
        points = E.FLAG_POINTS
    else:
        outcome = "CLEARED"
        points = 0
    return designation, matched_id, depth, outcome, points


def apply_screening(subaward, variant):
    """Store the screening result on the subaward; returns the outcome state."""
    organization = db.organizations.get(subaward["organization_id"])
    designation, matched_id, depth, outcome, points = screen_outcome(
        organization, variant)
    subaward["applied_screening_variant"] = variant
    subaward["screening_designation"] = designation
    subaward["screening_matched_organization_id"] = matched_id
    subaward["screening_match_depth"] = depth
    subaward["screening_risk_points"] = points
    return outcome
