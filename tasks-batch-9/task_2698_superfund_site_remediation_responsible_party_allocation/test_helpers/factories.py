"""Request-payload factories.

Every factory returns a plain dict that satisfies the PRD's field requirements
for one write endpoint, with `**overrides` so a test can vary exactly the field
it is exercising. Monetary values are integer counts of cents and rates are
basis points, matching the PRD's representation rules.
"""
import itertools
from typing import Any, Dict, List, Optional

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


# --------------------------------------------------------------------------
# Sites
# --------------------------------------------------------------------------
def site_payload(
    name: Optional[str] = None,
    epa_region: int = 5,
    hrs_score: float = 50.00,
    **overrides: Any,
) -> Dict[str, Any]:
    """`name`, `epa_region` 1-10 and `hrs_score` 0.00-100.00 to two decimals."""
    payload: Dict[str, Any] = {
        "name": name if name is not None else f"Site {_seq()}",
        "epa_region": epa_region,
        "hrs_score": hrs_score,
    }
    payload.update(overrides)
    return payload


def listing_payload(
    listing_reference: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """Listing stamps the Federal Register docket reference the manager supplies."""
    payload: Dict[str, Any] = {
        "listing_reference": (
            listing_reference
            if listing_reference is not None
            else f"FR-2027-NPL-{_seq():04d}"
        )
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Potentially responsible parties
# --------------------------------------------------------------------------
def prp_payload(
    legal_name: Optional[str] = None,
    party_type: str = "OWNER_OPERATOR",
    viability_score: int = 80,
    **overrides: Any,
) -> Dict[str, Any]:
    """`legal_name`, `party_type` and `viability_score` 0-100."""
    payload: Dict[str, Any] = {
        "legal_name": legal_name if legal_name is not None else f"Party {_seq()}",
        "party_type": party_type,
        "viability_score": viability_score,
    }
    payload.update(overrides)
    return payload


def notice_payload(
    notice_reference: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """The general notice letter stamps the reference the manager supplies."""
    payload: Dict[str, Any] = {
        "notice_reference": (
            notice_reference if notice_reference is not None else f"GNL-2027-{_seq():04d}"
        )
    }
    payload.update(overrides)
    return payload


def response_payload(election: str = "PARTICIPATE", **overrides: Any) -> Dict[str, Any]:
    """`election` is PARTICIPATE or DECLINE."""
    payload: Dict[str, Any] = {"election": election}
    payload.update(overrides)
    return payload


def defunct_payload(
    defunct_reason: str = "Dissolved without successor", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"defunct_reason": defunct_reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Chain of title
# --------------------------------------------------------------------------
def ownership_period_payload(
    prp_id: str,
    start_date: str = "1960-01-01",
    end_date: Optional[str] = "1970-01-01",
    acquisition_type: str = "PURCHASE",
    **overrides: Any,
) -> Dict[str, Any]:
    """`end_date` is nullable, meaning ownership continues to the present."""
    payload: Dict[str, Any] = {
        "prp_id": prp_id,
        "start_date": start_date,
        "end_date": end_date,
        "acquisition_type": acquisition_type,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Waste-in records
# --------------------------------------------------------------------------
def waste_in_payload(
    prp_id: str,
    volume_tons: float = 500.00,
    toxicity_class: str = "II",
    evidence_grade: str = "A",
    disposal_year: int = 1970,
    **overrides: Any,
) -> Dict[str, Any]:
    """`volume_tons` is positive with at most two decimals."""
    payload: Dict[str, Any] = {
        "prp_id": prp_id,
        "volume_tons": volume_tons,
        "toxicity_class": toxicity_class,
        "evidence_grade": evidence_grade,
        "disposal_year": disposal_year,
    }
    payload.update(overrides)
    return payload


def verification_payload(
    decision: str = "VERIFIED",
    verified_volume_tons: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """VERIFIED carries `verified_volume_tons`; REJECTED must not."""
    payload: Dict[str, Any] = {"decision": decision}
    if verified_volume_tons is not None:
        payload["verified_volume_tons"] = verified_volume_tons
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Remedial investigations
# --------------------------------------------------------------------------
def remedial_investigation_payload(
    scope_summary: Optional[str] = None,
    exposure_medium: str = "SOIL",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "scope_summary": (
            scope_summary
            if scope_summary is not None
            else f"Remedial investigation scope {_seq()}"
        ),
        "exposure_medium": exposure_medium,
    }
    payload.update(overrides)
    return payload


def sample_payload(
    medium: str = "SOIL",
    contaminant: str = "BENZENE",
    concentration_ug_per_l: float = 12.0,
    qa_status: str = "VALID",
    collected_at: str = "2026-08-01T09:00:00Z",
    lab_reference: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """`concentration_ug_per_l` is non-negative with at most three decimals."""
    payload: Dict[str, Any] = {
        "medium": medium,
        "contaminant": contaminant,
        "concentration_ug_per_l": concentration_ug_per_l,
        "qa_status": qa_status,
        "collected_at": collected_at,
        "lab_reference": (
            lab_reference if lab_reference is not None else f"LAB-{_seq():05d}"
        ),
    }
    payload.update(overrides)
    return payload


def review_payload(
    decision: str = "APPROVE", review_note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """`decision` is APPROVE or REQUEST_REVISION."""
    payload: Dict[str, Any] = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Remedy alternatives
# --------------------------------------------------------------------------
def remedy_alternative_payload(
    label: Optional[str] = None,
    capital_cost_cents: int = 938_888_889,
    annual_om_cost_cents: int = 40_000_000,
    om_years: int = 2,
    discount_rate_bp: int = 2000,
    effectiveness_score: int = 80,
    implementability_score: int = 75,
    **overrides: Any,
) -> Dict[str, Any]:
    """Costs are integer cents; `discount_rate_bp` is 0-2000 basis points."""
    payload: Dict[str, Any] = {
        "label": label if label is not None else f"Alternative {_seq()}",
        "capital_cost_cents": capital_cost_cents,
        "annual_om_cost_cents": annual_om_cost_cents,
        "om_years": om_years,
        "discount_rate_bp": discount_rate_bp,
        "effectiveness_score": effectiveness_score,
        "implementability_score": implementability_score,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Records of decision
# --------------------------------------------------------------------------
def record_of_decision_payload(
    remedial_investigation_id: str,
    proposed_plan_summary: Optional[str] = None,
    comment_period_days: int = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    """`comment_period_days` is 30-90."""
    payload: Dict[str, Any] = {
        "remedial_investigation_id": remedial_investigation_id,
        "proposed_plan_summary": (
            proposed_plan_summary
            if proposed_plan_summary is not None
            else f"Proposed plan {_seq()}"
        ),
        "comment_period_days": comment_period_days,
    }
    payload.update(overrides)
    return payload


def public_comment_payload(
    commenter_name: Optional[str] = None,
    comment_text: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "commenter_name": (
            commenter_name if commenter_name is not None else f"Commenter {_seq()}"
        ),
        "comment_text": (
            comment_text
            if comment_text is not None
            else "The community requests additional groundwater monitoring."
        ),
    }
    payload.update(overrides)
    return payload


def signature_payload(
    responsiveness_summary: Optional[str] = None,
    alternative_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """`alternative_id` is optional; omitting it invokes the selector."""
    payload: Dict[str, Any] = {
        "responsiveness_summary": (
            responsiveness_summary
            if responsiveness_summary is not None
            else f"Responsiveness summary {_seq()}"
        )
    }
    if alternative_id is not None:
        payload["alternative_id"] = alternative_id
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Allocation rounds
# --------------------------------------------------------------------------
def allocation_round_payload(
    expected_site_version: int,
    weight_volume_bp: int = 5000,
    weight_toxicity_bp: int = 3000,
    weight_ownership_bp: int = 2000,
    **overrides: Any,
) -> Dict[str, Any]:
    """The three weights must sum to exactly 10000 basis points."""
    payload: Dict[str, Any] = {
        "weight_volume_bp": weight_volume_bp,
        "weight_toxicity_bp": weight_toxicity_bp,
        "weight_ownership_bp": weight_ownership_bp,
        "expected_site_version": expected_site_version,
    }
    payload.update(overrides)
    return payload


def ballot_payload(
    ballot: str = "ACCEPT", ballot_rationale: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """`ballot` is ACCEPT, REJECT or ABSTAIN."""
    payload: Dict[str, Any] = {"ballot": ballot}
    if ballot_rationale is not None:
        payload["ballot_rationale"] = ballot_rationale
    payload.update(overrides)
    return payload


def reopening_payload(
    revision_note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "revision_note": (
            revision_note
            if revision_note is not None
            else f"Reopened to revise the allocation basis {_seq()}"
        )
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Consent decrees
# --------------------------------------------------------------------------
def consent_decree_payload(
    party_prp_ids: List[str],
    scope_type: str = "RD_RA_CONSENT_DECREE",
    scope_summary: Optional[str] = None,
    oversight_cost_cap_cents: int = 250_000_000,
    stipulated_penalty_per_day_cents: int = 250_000,
    performance_deadline: str = "2029-06-30",
    **overrides: Any,
) -> Dict[str, Any]:
    """`party_prp_ids` holds 1-20 distinct parties, all of this site."""
    payload: Dict[str, Any] = {
        "scope_type": scope_type,
        "scope_summary": (
            scope_summary if scope_summary is not None else f"Decree scope {_seq()}"
        ),
        "party_prp_ids": list(party_prp_ids),
        "oversight_cost_cap_cents": oversight_cost_cap_cents,
        "stipulated_penalty_per_day_cents": stipulated_penalty_per_day_cents,
        "performance_deadline": performance_deadline,
    }
    payload.update(overrides)
    return payload


def entry_payload(
    court_docket_number: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "court_docket_number": (
            court_docket_number
            if court_docket_number is not None
            else f"2:27-cv-{_seq():05d}"
        )
    }
    payload.update(overrides)
    return payload


def violation_event_payload(
    effective_at: str = "2027-04-01T00:00:00Z",
    violation_type: str = "MISSED_MILESTONE",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_type": "VIOLATION",
        "effective_at": effective_at,
        "violation_type": violation_type,
    }
    payload.update(overrides)
    return payload


def penalty_assessment_payload(
    effective_at: str = "2027-05-16T00:00:00Z", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "event_type": "PENALTY_ASSESSMENT",
        "effective_at": effective_at,
    }
    payload.update(overrides)
    return payload


def cure_event_payload(
    paid_penalty_cents: int,
    effective_at: str = "2027-06-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """A cure must pay the outstanding penalty balance exactly."""
    payload: Dict[str, Any] = {
        "event_type": "CURE",
        "effective_at": effective_at,
        "paid_penalty_cents": paid_penalty_cents,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Oversight costs
# --------------------------------------------------------------------------
def oversight_cost_payload(
    incurred_cents: int = 4_000_000,
    cost_category: str = "TECHNICAL_REVIEW",
    incurred_on: str = "2027-03-15",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "incurred_cents": incurred_cents,
        "cost_category": cost_category,
        "incurred_on": incurred_on,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Remediation contracts
# --------------------------------------------------------------------------
def remediation_contract_payload(
    record_of_decision_id: str,
    solicitation_reference: Optional[str] = None,
    engineer_estimate_cents: int = 1_000_000_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "record_of_decision_id": record_of_decision_id,
        "solicitation_reference": (
            solicitation_reference
            if solicitation_reference is not None
            else f"SOL-{_seq():05d}"
        ),
        "engineer_estimate_cents": engineer_estimate_cents,
    }
    payload.update(overrides)
    return payload


def award_payload(
    awarded_amount_cents: int = 1_000_000_000,
    contractor_name: Optional[str] = None,
    max_concurrent_windows: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """`max_concurrent_windows` is 1-5 and defaults to 2 when omitted."""
    payload: Dict[str, Any] = {
        "contractor_name": (
            contractor_name if contractor_name is not None else f"Contractor {_seq()}"
        ),
        "awarded_amount_cents": awarded_amount_cents,
    }
    if max_concurrent_windows is not None:
        payload["max_concurrent_windows"] = max_concurrent_windows
    payload.update(overrides)
    return payload


def work_window_payload(
    start_at: str = "2027-06-01T08:00:00Z",
    end_at: str = "2027-06-01T16:00:00Z",
    activity_type: str = "CONSTRUCTION",
    crew_size: int = 12,
    description: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """`end_at` is strictly after `start_at`; `crew_size` is 1-200."""
    payload: Dict[str, Any] = {
        "activity_type": activity_type,
        "start_at": start_at,
        "end_at": end_at,
        "crew_size": crew_size,
    }
    if description is not None:
        payload["description"] = description
    payload.update(overrides)
    return payload


def construction_completion_payload(
    punch_list_items: int = 0, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"punch_list_items": punch_list_items}
    payload.update(overrides)
    return payload


def five_year_review_payload(
    protectiveness_determination: str = "PROTECTIVE",
    deletion_recommended: bool = False,
    review_summary: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "protectiveness_determination": protectiveness_determination,
        "deletion_recommended": deletion_recommended,
        "review_summary": (
            review_summary
            if review_summary is not None
            else f"Five-year review findings {_seq()}"
        ),
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Cost recovery actions
# --------------------------------------------------------------------------
def cost_recovery_action_payload(
    respondent_prp_id: str,
    demanded_cents: int,
    expected_prp_version: int,
    action_type: str = "COST_RECOVERY_DEMAND",
    claimant_prp_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """`claimant_prp_id` is supplied only for a contribution claim."""
    payload: Dict[str, Any] = {
        "respondent_prp_id": respondent_prp_id,
        "action_type": action_type,
        "demanded_cents": demanded_cents,
        "expected_prp_version": expected_prp_version,
    }
    if claimant_prp_id is not None:
        payload["claimant_prp_id"] = claimant_prp_id
    payload.update(overrides)
    return payload


def action_response_payload(
    decision: str = "ACCEPT", response_note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """`decision` is ACCEPT or REJECT."""
    payload: Dict[str, Any] = {"decision": decision}
    if response_note is not None:
        payload["response_note"] = response_note
    payload.update(overrides)
    return payload


def collection_payload(
    received_cents: int, receipt_reference: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"received_cents": received_cents}
    if receipt_reference is not None:
        payload["receipt_reference"] = receipt_reference
    payload.update(overrides)
    return payload


def voiding_payload(
    void_reason: str = "Settlement rescinded by agreement", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"void_reason": void_reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def clock_payload(current_utc: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"current_utc": current_utc}
    payload.update(overrides)
    return payload
