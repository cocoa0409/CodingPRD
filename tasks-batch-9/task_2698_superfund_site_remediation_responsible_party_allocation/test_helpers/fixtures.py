"""Composite setup builders and pytest fixtures.

The builders walk the lifecycle the PRD describes -- site created, listed on the
National Priorities List, parties identified and noticed, waste-in records
verified, a remedial investigation opened, an allocation round opened, balloted
and adopted, a consent decree lodged and entered, a contract awarded and
construction certified complete -- so a test can start from whatever stage its
subject requires.

Two conventions matter throughout:

* Ownership-gated calls thread the acting identity. A party representative acts
  with its own party identifier in `X-User-ID` and a contractor with its own
  contract identifier, because a request from an entity-backed role naming
  another record is refused.
* Allocation-round creation reads the site immediately beforehand so that
  `expected_site_version` carries the current version rather than a stale one.
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    AUTHOR_PM_ID,
    COMMUNITY_ID,
    COUNSEL_ID,
    FACILITATOR_ID,
    REVIEWER_PM_ID,
    SIGNER_PM_ID,
    TEST_USERS,
    make_contractor_headers,
    make_prp_representative_headers,
    make_project_manager_headers,
)

AUTHOR = TEST_USERS["author_pm_headers"]
REVIEWER = TEST_USERS["reviewer_pm_headers"]
SIGNER = TEST_USERS["signer_pm_headers"]
FACILITATOR = TEST_USERS["facilitator_headers"]
COUNSEL = TEST_USERS["counsel_headers"]
COMMUNITY = TEST_USERS["community_headers"]


# ==========================================================================
# Clock
# ==========================================================================
def set_clock(current_utc: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Move the service clock; every role may do this and nothing is mutated."""
    response = api_client.set_clock(current_utc, headers or AUTHOR)
    return get_success_data(response)


# ==========================================================================
# Sites
# ==========================================================================
def create_site(
    name: Optional[str] = None,
    epa_region: int = 5,
    hrs_score: float = 50.00,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.create_site(
        factories.site_payload(name=name, epa_region=epa_region, hrs_score=hrs_score),
        headers or AUTHOR,
    )
    return get_success_data(response)


def list_site_on_npl(
    site_id: str,
    listing_reference: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.list_on_npl(
        site_id,
        factories.listing_payload(listing_reference=listing_reference),
        headers or AUTHOR,
    )
    return get_success_data(response)


def create_listed_site(
    name: Optional[str] = None,
    epa_region: int = 5,
    hrs_score: float = 50.00,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create a site and place it on the National Priorities List."""
    site = create_site(name=name, epa_region=epa_region, hrs_score=hrs_score, headers=headers)
    return list_site_on_npl(site["id"], headers=headers)


def read_site(site_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_site(site_id, headers or AUTHOR))


def site_version(site_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    """Read the site's current version, for optimistic concurrency payloads."""
    return read_site(site_id, headers)["version"]


def read_ledger(site_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_cost_ledger(site_id, headers or AUTHOR))


# ==========================================================================
# Parties
# ==========================================================================
def create_party(
    site_id: str,
    legal_name: Optional[str] = None,
    party_type: str = "OWNER_OPERATOR",
    viability_score: int = 80,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.create_prp(
        site_id,
        factories.prp_payload(
            legal_name=legal_name,
            party_type=party_type,
            viability_score=viability_score,
        ),
        headers or AUTHOR,
    )
    return get_success_data(response)


def issue_notice(
    prp_id: str,
    notice_reference: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.issue_notice(
            prp_id,
            factories.notice_payload(notice_reference=notice_reference),
            headers or AUTHOR,
        )
    )


def record_election(prp_id: str, election: str = "PARTICIPATE") -> Dict[str, Any]:
    """A party answers its own notice, acting as its own representative."""
    response = api_client.record_response(
        prp_id,
        factories.response_payload(election=election),
        make_prp_representative_headers(prp_id),
    )
    return get_success_data(response)


def create_participating_party(
    site_id: str,
    legal_name: Optional[str] = None,
    party_type: str = "OWNER_OPERATOR",
    viability_score: int = 80,
) -> Dict[str, Any]:
    """Create a party, notice it and record a PARTICIPATE election."""
    party = create_party(
        site_id,
        legal_name=legal_name,
        party_type=party_type,
        viability_score=viability_score,
    )
    issue_notice(party["id"])
    return record_election(party["id"], "PARTICIPATE")


def create_noticed_party(
    site_id: str,
    legal_name: Optional[str] = None,
    party_type: str = "OWNER_OPERATOR",
    viability_score: int = 80,
) -> Dict[str, Any]:
    """Create a party and notice it, leaving the election unanswered."""
    party = create_party(
        site_id,
        legal_name=legal_name,
        party_type=party_type,
        viability_score=viability_score,
    )
    return issue_notice(party["id"])


def read_party(prp_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_prp(prp_id, headers or AUTHOR))


def prp_version(prp_id: str, headers: Optional[Dict[str, str]] = None) -> int:
    """Read a party's current version, for cost-recovery concurrency payloads."""
    return read_party(prp_id, headers)["version"]


def record_defunct(prp_id: str, defunct_reason: str = "Dissolved without successor") -> Dict[str, Any]:
    response = api_client.record_defunct(
        prp_id, factories.defunct_payload(defunct_reason=defunct_reason), AUTHOR
    )
    return get_success_data(response)


# ==========================================================================
# Chain of title
# ==========================================================================
def add_ownership_period(
    site_id: str,
    prp_id: str,
    start_date: str,
    end_date: Optional[str],
    acquisition_type: str = "PURCHASE",
) -> Dict[str, Any]:
    response = api_client.create_ownership_period(
        site_id,
        factories.ownership_period_payload(
            prp_id=prp_id,
            start_date=start_date,
            end_date=end_date,
            acquisition_type=acquisition_type,
        ),
        AUTHOR,
    )
    return get_success_data(response)


# ==========================================================================
# Waste-in records
# ==========================================================================
def add_waste_in(
    site_id: str,
    prp_id: str,
    volume_tons: float,
    toxicity_class: str = "II",
    evidence_grade: str = "A",
    disposal_year: int = 1970,
    **extra: Any,
) -> Dict[str, Any]:
    response = api_client.create_waste_in_record(
        site_id,
        factories.waste_in_payload(
            prp_id=prp_id,
            volume_tons=volume_tons,
            toxicity_class=toxicity_class,
            evidence_grade=evidence_grade,
            disposal_year=disposal_year,
            **extra,
        ),
        AUTHOR,
    )
    return get_success_data(response)


def verify_waste_in(
    record_id: str,
    verified_volume_tons: float,
    verification_note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = factories.verification_payload(
        decision="VERIFIED", verified_volume_tons=verified_volume_tons
    )
    if verification_note is not None:
        payload["verification_note"] = verification_note
    return get_success_data(
        api_client.verify_waste_in_record(record_id, payload, headers or AUTHOR)
    )


def reject_waste_in(
    record_id: str,
    verification_note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = factories.verification_payload(decision="REJECTED")
    if verification_note is not None:
        payload["verification_note"] = verification_note
    return get_success_data(
        api_client.verify_waste_in_record(record_id, payload, headers or AUTHOR)
    )


def add_verified_waste_in(
    site_id: str,
    prp_id: str,
    volume_tons: float,
    toxicity_class: str = "II",
    evidence_grade: str = "A",
    disposal_year: int = 1970,
    verified_volume_tons: Optional[float] = None,
) -> Dict[str, Any]:
    """Record a waste-in claim and verify it, by default at the claimed volume."""
    record = add_waste_in(
        site_id,
        prp_id,
        volume_tons=volume_tons,
        toxicity_class=toxicity_class,
        evidence_grade=evidence_grade,
        disposal_year=disposal_year,
    )
    return verify_waste_in(
        record["id"],
        verified_volume_tons if verified_volume_tons is not None else volume_tons,
    )


# ==========================================================================
# Remedial investigations
# ==========================================================================
def create_investigation(
    site_id: str,
    exposure_medium: str = "SOIL",
    scope_summary: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.create_remedial_investigation(
        site_id,
        factories.remedial_investigation_payload(
            scope_summary=scope_summary, exposure_medium=exposure_medium
        ),
        headers or AUTHOR,
    )
    return get_success_data(response)


def add_sample(
    ri_id: str,
    medium: str = "SOIL",
    contaminant: str = "BENZENE",
    concentration_ug_per_l: float = 12.0,
    qa_status: str = "VALID",
    collected_at: str = "2026-08-01T09:00:00Z",
    lab_reference: Optional[str] = None,
) -> Dict[str, Any]:
    response = api_client.create_sample(
        ri_id,
        factories.sample_payload(
            medium=medium,
            contaminant=contaminant,
            concentration_ug_per_l=concentration_ug_per_l,
            qa_status=qa_status,
            collected_at=collected_at,
            lab_reference=lab_reference,
        ),
        AUTHOR,
    )
    return get_success_data(response)


def add_alternative(
    ri_id: str,
    label: Optional[str] = None,
    capital_cost_cents: int = 938_888_889,
    annual_om_cost_cents: int = 40_000_000,
    om_years: int = 2,
    discount_rate_bp: int = 2000,
    effectiveness_score: int = 80,
    implementability_score: int = 75,
) -> Dict[str, Any]:
    response = api_client.create_remedy_alternative(
        ri_id,
        factories.remedy_alternative_payload(
            label=label,
            capital_cost_cents=capital_cost_cents,
            annual_om_cost_cents=annual_om_cost_cents,
            om_years=om_years,
            discount_rate_bp=discount_rate_bp,
            effectiveness_score=effectiveness_score,
            implementability_score=implementability_score,
        ),
        AUTHOR,
    )
    return get_success_data(response)


def submit_investigation(ri_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_remedial_investigation(ri_id, headers or AUTHOR)
    )


def review_investigation(
    ri_id: str,
    decision: str = "APPROVE",
    review_note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """The reviewer must not be the author, so the reviewing manager acts here."""
    response = api_client.review_remedial_investigation(
        ri_id,
        factories.review_payload(decision=decision, review_note=review_note),
        headers or REVIEWER,
    )
    return get_success_data(response)


def read_investigation(ri_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_remedial_investigation(ri_id, headers or AUTHOR))


def create_submitted_investigation(
    site_id: str,
    exposure_medium: str = "SOIL",
    samples: Sequence[Dict[str, Any]] = (),
    alternatives: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """Open an investigation, load it with samples and alternatives, submit it."""
    investigation = create_investigation(site_id, exposure_medium=exposure_medium)
    for sample in samples or ({"medium": exposure_medium},):
        add_sample(investigation["id"], **{"medium": exposure_medium, **sample})
    for alternative in alternatives:
        add_alternative(investigation["id"], **alternative)
    return submit_investigation(investigation["id"])


def create_approved_investigation(
    site_id: str,
    exposure_medium: str = "SOIL",
    samples: Sequence[Dict[str, Any]] = (),
    alternatives: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """Carry an investigation all the way to APPROVED, approved by the reviewer."""
    submitted = create_submitted_investigation(
        site_id,
        exposure_medium=exposure_medium,
        samples=samples,
        alternatives=alternatives,
    )
    return review_investigation(submitted["id"], "APPROVE")


def alternatives_of(ri_id: str, headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    response = api_client.list_remedy_alternatives(
        ri_id, headers or AUTHOR, {"limit": 100}
    )
    return get_success_data(response)


# ==========================================================================
# Records of decision
# ==========================================================================
def create_rod(
    site_id: str,
    ri_id: str,
    comment_period_days: int = 30,
    proposed_plan_summary: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.create_record_of_decision(
        site_id,
        factories.record_of_decision_payload(
            remedial_investigation_id=ri_id,
            proposed_plan_summary=proposed_plan_summary,
            comment_period_days=comment_period_days,
        ),
        headers or AUTHOR,
    )
    return get_success_data(response)


def open_comment_period(rod_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.open_comment_period(rod_id, headers or AUTHOR))


def file_comment(
    rod_id: str,
    commenter_name: Optional[str] = None,
    comment_text: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.file_public_comment(
        rod_id,
        factories.public_comment_payload(
            commenter_name=commenter_name, comment_text=comment_text
        ),
        headers or COMMUNITY,
    )
    return get_success_data(response)


def sign_rod(
    rod_id: str,
    alternative_id: Optional[str] = None,
    responsiveness_summary: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """The signer must be neither the author nor the approver of the cited study."""
    response = api_client.sign_record_of_decision(
        rod_id,
        factories.signature_payload(
            responsiveness_summary=responsiveness_summary,
            alternative_id=alternative_id,
        ),
        headers or SIGNER,
    )
    return get_success_data(response)


def read_rod(rod_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_record_of_decision(rod_id, headers or AUTHOR))


def create_signed_rod(
    site_id: str,
    ri_id: str,
    comment_period_days: int = 30,
    open_at: str = "2027-03-01T09:00:00Z",
    sign_at: str = "2027-04-01T09:00:00Z",
    alternative_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Draft a decision record, run its comment period and sign it.

    A comment period may only open once the cited investigation is approved, a
    signature requires the clock to be strictly past the period end and at
    least one comment on the record, so the chain steps the clock twice.
    """
    rod = create_rod(site_id, ri_id, comment_period_days=comment_period_days)
    set_clock(open_at)
    open_comment_period(rod["id"])
    file_comment(rod["id"])
    set_clock(sign_at)
    return sign_rod(rod["id"], alternative_id=alternative_id)


# ==========================================================================
# Allocation rounds
# ==========================================================================
def open_round(
    site_id: str,
    weights: Tuple[int, int, int] = (5000, 3000, 2000),
    expected_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Open a round, reading the site version immediately beforehand."""
    version = expected_version if expected_version is not None else site_version(site_id)
    response = api_client.create_allocation_round(
        site_id,
        factories.allocation_round_payload(
            expected_site_version=version,
            weight_volume_bp=weights[0],
            weight_toxicity_bp=weights[1],
            weight_ownership_bp=weights[2],
        ),
        headers or FACILITATOR,
    )
    return get_success_data(response)


def open_balloting(round_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.open_balloting(round_id, headers or FACILITATOR))


def cast_ballot(
    round_id: str,
    prp_id: str,
    ballot: str = "ACCEPT",
    ballot_rationale: Optional[str] = None,
) -> Dict[str, Any]:
    """A ballot is cast by the party's own representative."""
    response = api_client.cast_ballot(
        round_id,
        factories.ballot_payload(ballot=ballot, ballot_rationale=ballot_rationale),
        make_prp_representative_headers(prp_id),
    )
    return get_success_data(response)


def reopen_round(
    round_id: str,
    revision_note: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.reopen_round(
        round_id,
        factories.reopening_payload(revision_note=revision_note),
        headers or FACILITATOR,
    )
    return get_success_data(response)


def read_round(round_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_allocation_round(round_id, headers or AUTHOR))


def shares_of(round_id: str, headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    response = api_client.list_round_shares(round_id, headers or AUTHOR, {"limit": 100})
    return get_success_data(response)


def share_for(round_id: str, prp_id: str) -> Dict[str, Any]:
    """The one share of this round that belongs to the given party."""
    for share in shares_of(round_id):
        if share["prp_id"] == prp_id:
            return share
    raise AssertionError(f"round {round_id} has no share for party {prp_id}")


def adopt_round(round_id: str, accepting_prp_ids: Sequence[str]) -> Dict[str, Any]:
    """Open balloting and record an acceptance from every listed party."""
    open_balloting(round_id)
    for prp_id in accepting_prp_ids:
        cast_ballot(round_id, prp_id, "ACCEPT")
    return read_round(round_id)


# ==========================================================================
# Consent decrees
# ==========================================================================
def create_decree(
    site_id: str,
    party_prp_ids: Sequence[str],
    scope_type: str = "RD_RA_CONSENT_DECREE",
    oversight_cost_cap_cents: int = 250_000_000,
    stipulated_penalty_per_day_cents: int = 250_000,
    performance_deadline: str = "2029-06-30",
    scope_summary: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.create_consent_decree(
        site_id,
        factories.consent_decree_payload(
            party_prp_ids=list(party_prp_ids),
            scope_type=scope_type,
            scope_summary=scope_summary,
            oversight_cost_cap_cents=oversight_cost_cap_cents,
            stipulated_penalty_per_day_cents=stipulated_penalty_per_day_cents,
            performance_deadline=performance_deadline,
        ),
        headers or COUNSEL,
    )
    return get_success_data(response)


def lodge_decree(decree_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.lodge_consent_decree(decree_id, headers or COUNSEL))


def enter_decree(
    decree_id: str,
    court_docket_number: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.enter_consent_decree(
        decree_id,
        factories.entry_payload(court_docket_number=court_docket_number),
        headers or COUNSEL,
    )
    return get_success_data(response)


def read_decree(decree_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_consent_decree(decree_id, headers or AUTHOR))


def record_violation(
    decree_id: str,
    effective_at: str,
    violation_type: str = "MISSED_MILESTONE",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.record_compliance_event(
        decree_id,
        factories.violation_event_payload(
            effective_at=effective_at, violation_type=violation_type
        ),
        headers or COUNSEL,
    )
    return get_success_data(response)


def record_penalty_assessment(
    decree_id: str, effective_at: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.record_compliance_event(
        decree_id,
        factories.penalty_assessment_payload(effective_at=effective_at),
        headers or COUNSEL,
    )
    return get_success_data(response)


def record_cure(
    decree_id: str,
    paid_penalty_cents: int,
    effective_at: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.record_compliance_event(
        decree_id,
        factories.cure_event_payload(
            paid_penalty_cents=paid_penalty_cents, effective_at=effective_at
        ),
        headers or COUNSEL,
    )
    return get_success_data(response)


def create_entered_decree(
    site_id: str,
    party_prp_ids: Sequence[str],
    lodge_at: str = "2027-03-01T10:00:00Z",
    enter_at: str = "2027-04-01T10:00:00Z",
    oversight_cost_cap_cents: int = 250_000_000,
    stipulated_penalty_per_day_cents: int = 250_000,
    performance_deadline: str = "2029-06-30",
) -> Dict[str, Any]:
    """Lodge a decree and enter it once its public comment window has closed."""
    decree = create_decree(
        site_id,
        party_prp_ids,
        oversight_cost_cap_cents=oversight_cost_cap_cents,
        stipulated_penalty_per_day_cents=stipulated_penalty_per_day_cents,
        performance_deadline=performance_deadline,
    )
    set_clock(lodge_at)
    lodge_decree(decree["id"])
    set_clock(enter_at)
    return enter_decree(decree["id"])


# ==========================================================================
# Oversight costs
# ==========================================================================
def post_oversight(
    site_id: str,
    incurred_cents: int,
    cost_category: str = "TECHNICAL_REVIEW",
    incurred_on: str = "2027-03-15",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.post_oversight_cost(
        site_id,
        factories.oversight_cost_payload(
            incurred_cents=incurred_cents,
            cost_category=cost_category,
            incurred_on=incurred_on,
        ),
        headers or AUTHOR,
    )
    return get_success_data(response)


# ==========================================================================
# Procurement and construction
# ==========================================================================
def create_solicitation(
    site_id: str,
    rod_id: str,
    engineer_estimate_cents: int = 1_000_000_000,
    solicitation_reference: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.create_remediation_contract(
        site_id,
        factories.remediation_contract_payload(
            record_of_decision_id=rod_id,
            solicitation_reference=solicitation_reference,
            engineer_estimate_cents=engineer_estimate_cents,
        ),
        headers or AUTHOR,
    )
    return get_success_data(response)


def award_contract(
    contract_id: str,
    awarded_amount_cents: int,
    contractor_name: Optional[str] = None,
    max_concurrent_windows: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.award_contract(
        contract_id,
        factories.award_payload(
            awarded_amount_cents=awarded_amount_cents,
            contractor_name=contractor_name,
            max_concurrent_windows=max_concurrent_windows,
        ),
        headers or AUTHOR,
    )
    return get_success_data(response)


def add_work_window(
    contract_id: str,
    start_at: str,
    end_at: str,
    activity_type: str = "CONSTRUCTION",
    crew_size: int = 12,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """The contractor acts with its own contract identifier in `X-User-ID`."""
    response = api_client.create_work_window(
        contract_id,
        factories.work_window_payload(
            start_at=start_at,
            end_at=end_at,
            activity_type=activity_type,
            crew_size=crew_size,
            description=description,
        ),
        make_contractor_headers(contract_id),
    )
    return get_success_data(response)


def complete_construction(
    contract_id: str, punch_list_items: int = 0, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    response = api_client.certify_construction_complete(
        contract_id,
        factories.construction_completion_payload(punch_list_items=punch_list_items),
        headers or AUTHOR,
    )
    return get_success_data(response)


def read_contract(contract_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_remediation_contract(contract_id, headers or AUTHOR)
    )


def record_five_year_review(
    site_id: str,
    protectiveness_determination: str = "PROTECTIVE",
    deletion_recommended: bool = False,
    review_summary: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.record_five_year_review(
        site_id,
        factories.five_year_review_payload(
            protectiveness_determination=protectiveness_determination,
            deletion_recommended=deletion_recommended,
            review_summary=review_summary,
        ),
        headers or AUTHOR,
    )
    return get_success_data(response)


def create_awarded_contract(
    site_id: str,
    rod_id: str,
    engineer_estimate_cents: int = 1_000_000_000,
    awarded_amount_cents: Optional[int] = None,
    max_concurrent_windows: Optional[int] = None,
) -> Dict[str, Any]:
    """Open a solicitation on a signed decision record and award it."""
    contract = create_solicitation(
        site_id, rod_id, engineer_estimate_cents=engineer_estimate_cents
    )
    return award_contract(
        contract["id"],
        awarded_amount_cents
        if awarded_amount_cents is not None
        else engineer_estimate_cents,
        max_concurrent_windows=max_concurrent_windows,
    )


# ==========================================================================
# Cost recovery
# ==========================================================================
def issue_action(
    site_id: str,
    respondent_prp_id: str,
    demanded_cents: int,
    action_type: str = "COST_RECOVERY_DEMAND",
    claimant_prp_id: Optional[str] = None,
    expected_prp_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Issue an action, reading the respondent's version immediately beforehand."""
    version = (
        expected_prp_version
        if expected_prp_version is not None
        else prp_version(respondent_prp_id)
    )
    response = api_client.create_cost_recovery_action(
        site_id,
        factories.cost_recovery_action_payload(
            respondent_prp_id=respondent_prp_id,
            demanded_cents=demanded_cents,
            expected_prp_version=version,
            action_type=action_type,
            claimant_prp_id=claimant_prp_id,
        ),
        headers or COUNSEL,
    )
    return get_success_data(response)


def respond_to_action(
    action_id: str,
    respondent_prp_id: str,
    decision: str = "ACCEPT",
    response_note: Optional[str] = None,
) -> Dict[str, Any]:
    """The respondent answers through its own representative."""
    response = api_client.respond_to_action(
        action_id,
        factories.action_response_payload(decision=decision, response_note=response_note),
        make_prp_representative_headers(respondent_prp_id),
    )
    return get_success_data(response)


def record_collection(
    action_id: str,
    received_cents: int,
    receipt_reference: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.record_collection(
        action_id,
        factories.collection_payload(
            received_cents=received_cents, receipt_reference=receipt_reference
        ),
        headers or COUNSEL,
    )
    return get_success_data(response)


def void_action(
    action_id: str,
    void_reason: str = "Settlement rescinded by agreement",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    response = api_client.void_action(
        action_id, factories.voiding_payload(void_reason=void_reason), headers or COUNSEL
    )
    return get_success_data(response)


def read_action(action_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.get_cost_recovery_action(action_id, headers or AUTHOR))


# ==========================================================================
# Composite scenarios exposed as pytest fixtures
# ==========================================================================
def build_two_party_allocation_basis(
    site_name: str = "Two Party Basis Site",
    epa_region: int = 5,
    hrs_score: float = 52.80,
    exposure_medium: str = "SOIL",
) -> Dict[str, Any]:
    """A listed site with two participating parties and a verified waste basis.

    The larger party claims 3960 tons of class II waste and the smaller 40 tons
    of class IV, both verified at the claimed volume, so the volumetric and
    toxicity factors both carry a non-zero total and a round may open.
    """
    site = create_listed_site(name=site_name, epa_region=epa_region, hrs_score=hrs_score)
    prp_a = create_participating_party(
        site["id"], legal_name=f"{site_name} Works", party_type="OWNER_OPERATOR", viability_score=80
    )
    prp_b = create_participating_party(
        site["id"], legal_name=f"{site_name} Chemical", party_type="GENERATOR", viability_score=49
    )
    add_verified_waste_in(
        site["id"], prp_a["id"], 3960.00, toxicity_class="II", evidence_grade="A", disposal_year=1964
    )
    add_verified_waste_in(
        site["id"], prp_b["id"], 40.00, toxicity_class="IV", evidence_grade="B", disposal_year=1983
    )
    investigation = create_investigation(site["id"], exposure_medium=exposure_medium)
    return {
        "site": read_site(site["id"]),
        "prp_a": read_party(prp_a["id"]),
        "prp_b": read_party(prp_b["id"]),
        "investigation": investigation,
    }


def build_drafting_round(
    weights: Tuple[int, int, int] = (5000, 3000, 2000), **kwargs: Any
) -> Dict[str, Any]:
    """The two-party basis with an allocation round open in DRAFTING."""
    scenario = build_two_party_allocation_basis(**kwargs)
    scenario["round"] = open_round(scenario["site"]["id"], weights=weights)
    scenario["site"] = read_site(scenario["site"]["id"])
    return scenario


def build_adopted_round(
    weights: Tuple[int, int, int] = (5000, 3000, 2000), **kwargs: Any
) -> Dict[str, Any]:
    """The two-party basis with a round adopted by two acceptances."""
    scenario = build_drafting_round(weights=weights, **kwargs)
    scenario["round"] = adopt_round(
        scenario["round"]["id"], [scenario["prp_a"]["id"], scenario["prp_b"]["id"]]
    )
    scenario["site"] = read_site(scenario["site"]["id"])
    scenario["prp_a"] = read_party(scenario["prp_a"]["id"])
    scenario["prp_b"] = read_party(scenario["prp_b"]["id"])
    return scenario


def build_adopted_round_with_oversight(
    incurred_cents: int = 4_000_000,
    weights: Tuple[int, int, int] = (5000, 3000, 2000),
    **kwargs: Any,
) -> Dict[str, Any]:
    """An adopted round plus one oversight posting, so response costs exist.

    With no entered decree governing the site there is no cap to test the
    posting against, and a 4,000,000 cent subtotal sits inside the first fee
    tier, so the site is billed 4,620,000 cents in total.
    """
    scenario = build_adopted_round(weights=weights, **kwargs)
    scenario["site"] = post_oversight(scenario["site"]["id"], incurred_cents)
    return scenario


def build_construction_chain(
    site_name: str = "Construction Chain Site",
    epa_region: int = 8,
    hrs_score: float = 45.60,
    exposure_medium: str = "SOIL",
    contaminant: str = "ARSENIC",
    concentration_ug_per_l: float = 25.0,
    collected_at: str = "2027-01-21T13:00:00Z",
    alternative: Optional[Dict[str, Any]] = None,
    comment_period_days: int = 30,
    open_at: str = "2027-03-01T09:00:00Z",
    sign_at: str = "2027-04-01T09:00:00Z",
    engineer_estimate_cents: int = 800_000_000,
    awarded_amount_cents: int = 800_000_000,
    max_concurrent_windows: int = 2,
) -> Dict[str, Any]:
    """Site listed, investigation approved, decision signed, contract awarded.

    This is the shortest path to a site in CONSTRUCTION: one valid sample makes
    the investigation submittable, the reviewing manager approves it, the
    signing manager signs the decision record after a public comment, and the
    award moves the site out of ROD_SIGNED.
    """
    site = create_listed_site(name=site_name, epa_region=epa_region, hrs_score=hrs_score)
    investigation = create_approved_investigation(
        site["id"],
        exposure_medium=exposure_medium,
        samples=(
            {
                "contaminant": contaminant,
                "concentration_ug_per_l": concentration_ug_per_l,
                "qa_status": "VALID",
                "collected_at": collected_at,
            },
        ),
        alternatives=(
            alternative
            if alternative is not None
            else {
                "label": "Alternative A",
                "capital_cost_cents": 938_888_889,
                "annual_om_cost_cents": 40_000_000,
                "om_years": 2,
                "discount_rate_bp": 2000,
                "effectiveness_score": 81,
                "implementability_score": 77,
            },
        ),
    )
    rod = create_signed_rod(
        site["id"],
        investigation["id"],
        comment_period_days=comment_period_days,
        open_at=open_at,
        sign_at=sign_at,
    )
    contract = create_awarded_contract(
        site["id"],
        rod["id"],
        engineer_estimate_cents=engineer_estimate_cents,
        awarded_amount_cents=awarded_amount_cents,
        max_concurrent_windows=max_concurrent_windows,
    )
    return {
        "site": read_site(site["id"]),
        "investigation": read_investigation(investigation["id"]),
        "alternatives": alternatives_of(investigation["id"]),
        "rod": read_rod(rod["id"]),
        "contract": contract,
    }


def build_operations_and_maintenance_site(
    complete_at: str = "2029-05-15T10:00:00Z",
    punch_list_items: int = 0,
    work_window_start: str = "2029-03-01T08:00:00Z",
    work_window_end: str = "2029-03-01T16:00:00Z",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Carry the construction chain through to certified completion.

    Completion requires at least one scheduled work window, and it moves the
    site into its operations and maintenance phase with a five-year review due
    date recorded.
    """
    scenario = build_construction_chain(**kwargs)
    contract_id = scenario["contract"]["id"]
    scenario["work_window"] = add_work_window(
        contract_id, work_window_start, work_window_end, crew_size=12
    )
    set_clock(complete_at)
    scenario["contract"] = complete_construction(contract_id, punch_list_items=punch_list_items)
    scenario["site"] = read_site(scenario["site"]["id"])
    return scenario


@pytest.fixture
def two_party_allocation_basis() -> Dict[str, Any]:
    """A listed site with two participating parties and verified waste volumes."""
    return build_two_party_allocation_basis()


@pytest.fixture
def drafting_round() -> Dict[str, Any]:
    """The two-party basis with an allocation round open in DRAFTING."""
    return build_drafting_round()


@pytest.fixture
def adopted_round() -> Dict[str, Any]:
    """The two-party basis with an adopted allocation round."""
    return build_adopted_round()


@pytest.fixture
def adopted_round_with_oversight() -> Dict[str, Any]:
    """An adopted allocation round with 4,620,000 cents of response cost."""
    return build_adopted_round_with_oversight()


@pytest.fixture
def construction_chain() -> Dict[str, Any]:
    """A site in CONSTRUCTION with a signed decision record and awarded contract."""
    return build_construction_chain()


@pytest.fixture
def operations_and_maintenance_site() -> Dict[str, Any]:
    """A site in its operations and maintenance phase after certified completion."""
    return build_operations_and_maintenance_site()
