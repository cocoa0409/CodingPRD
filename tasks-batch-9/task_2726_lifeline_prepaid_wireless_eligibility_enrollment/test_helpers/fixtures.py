"""Composite setup helpers.

These build the multi-step ladders the domain needs before an interesting write is
even reachable: a registered carrier, a dwelling, a screened applicant, an active
benefit, stocked handsets, a filed claim, a drawn audit sample and a de-enrolled
benefit with an open appeal. Setup calls use the lenient success reader so a fixture
never masks the assertion the test itself is making.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import CLOCK_EPOCH
from .test_users import (
    AUDITOR_ADJUDICATOR,
    AUDITOR_DRAWER,
    NATIONAL_VERIFIER,
    PROGRAM_ADMIN,
    make_provider_agent_headers,
    make_subscriber_headers,
)

# --------------------------------------------------------------------- clock


def set_clock(api: ApiClient, moment: str) -> str:
    """Move the logical clock and return the instant the API reports."""
    data = get_success_data(api.set_clock(moment, PROGRAM_ADMIN))
    return data["current_utc"]


def reset_clock(api: ApiClient) -> str:
    return set_clock(api, CLOCK_EPOCH)


# ------------------------------------------------------------------ providers


def provider_headers(provider: Dict[str, Any]) -> Dict[str, str]:
    """ProviderAgent headers bound to this carrier's own row id."""
    return make_provider_agent_headers(provider["id"])


def subscriber_headers(subscriber: Dict[str, Any]) -> Dict[str, str]:
    """Subscriber headers bound to this applicant's own row id."""
    return make_subscriber_headers(subscriber["id"])


def register_provider(
    api: ApiClient,
    name: str = "SafeLink Wireless",
    licensed_state_codes: Optional[List[str]] = None,
    enrollment_cap: Optional[int] = 50,
    status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.provider_payload(
        name=name,
        licensed_state_codes=licensed_state_codes,
        enrollment_cap=enrollment_cap,
        status=status,
        **overrides,
    )
    return get_success_data(api.create_provider(payload, PROGRAM_ADMIN))


def register_provider_pair(
    api: ApiClient, licensed_state_codes: Optional[List[str]] = None
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Two distinct active carriers, useful for porting and peer isolation setups."""
    first = register_provider(
        api, name="SafeLink Wireless", licensed_state_codes=licensed_state_codes
    )
    second = register_provider(
        api, name="Assurance Mobile", licensed_state_codes=licensed_state_codes
    )
    return first, second


def refresh_provider(api: ApiClient, provider_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_provider(provider_id, PROGRAM_ADMIN))


def provider_version(api: ApiClient, provider_id: str) -> int:
    """The carrier's current version, read immediately before an OCC write."""
    return refresh_provider(api, provider_id)["version"]


# ------------------------------------------------------------------ dwellings


def register_address(
    api: ApiClient,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = f.address_payload(**overrides)
    return get_success_data(api.create_address(payload, headers or PROGRAM_ADMIN))


def register_distinct_address(
    api: ApiClient, index: int, state_code: str = "TX", headers=None
) -> Dict[str, Any]:
    """A dwelling guaranteed not to share a cohort with any other index."""
    payload = f.distinct_address_payload(index, state_code=state_code)
    return get_success_data(api.create_address(payload, headers or PROGRAM_ADMIN))


def refresh_address(api: ApiClient, address_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_address(address_id, PROGRAM_ADMIN))


def address_version(api: ApiClient, address_id: str) -> int:
    return refresh_address(api, address_id)["version"]


def duplicate_cohort(
    api: ApiClient, count: int = 2
) -> List[Dict[str, Any]]:
    """Several differently punctuated spellings of one dwelling, all flagged duplicate."""
    spellings = [
        f.address_payload(
            address_line1="1200 N Main St",
            unit_designator="Apt 4B",
            city="El Paso",
            state_code="TX",
            postal_code="79901",
        ),
        f.address_payload(
            address_line1="1200  n. main st.",
            unit_designator="apt 4-b",
            city="EL PASO",
            state_code="TX",
            postal_code="799012214",
        ),
        f.address_payload(
            address_line1="1200-N-MAIN-ST",
            unit_designator="APT4B",
            city="el paso",
            state_code="TX",
            postal_code="79901",
        ),
    ]
    rows = []
    for index in range(count):
        rows.append(
            get_success_data(api.create_address(spellings[index % 3], PROGRAM_ADMIN))
        )
    return rows


def resolve_multi_household(
    api: ApiClient,
    address_id: str,
    declared_household_count: int = 2,
    worksheet_ref: str = "WS-1",
) -> Dict[str, Any]:
    payload = f.duplicate_resolution_payload(
        resolution="MULTI_HOUSEHOLD",
        expected_address_version=address_version(api, address_id),
        declared_household_count=declared_household_count,
        independent_household_worksheet_ref=worksheet_ref,
    )
    return get_success_data(
        api.resolve_duplicate_address(address_id, payload, PROGRAM_ADMIN)
    )


def resolve_single_household(
    api: ApiClient, address_id: str, headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    payload = f.duplicate_resolution_payload(
        resolution="SINGLE_HOUSEHOLD",
        expected_address_version=address_version(api, address_id),
    )
    return get_success_data(
        api.resolve_duplicate_address(address_id, payload, headers or PROGRAM_ADMIN)
    )


# ---------------------------------------------------------------- applicants


def create_subscriber(
    api: ApiClient,
    address_id: str,
    headers: Optional[Dict[str, str]] = None,
    distinct_identity: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    if distinct_identity and not {"full_name", "last4_ssn"} & set(overrides):
        overrides.update(f.distinct_person_fields())
    payload = f.subscriber_payload(address_id, **overrides)
    return get_success_data(api.create_subscriber(payload, headers or PROGRAM_ADMIN))


def refresh_subscriber(api: ApiClient, subscriber_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_subscriber(subscriber_id, PROGRAM_ADMIN))


def open_eligibility_check(
    api: ApiClient,
    subscriber_id: str,
    claimed_basis: str = "INCOME",
    proof_document_ref: Optional[str] = "DOC-1",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = f.eligibility_check_payload(
        claimed_basis=claimed_basis, proof_document_ref=proof_document_ref
    )
    return get_success_data(
        api.create_eligibility_check(subscriber_id, payload, headers or PROGRAM_ADMIN)
    )


def confirm_eligibility_check(
    api: ApiClient, check_id: str, matched_benefit: Optional[str] = None
) -> Dict[str, Any]:
    payload = f.verifier_result_payload(
        verifier_outcome="MATCH", matched_benefit=matched_benefit
    )
    return get_success_data(
        api.submit_verifier_result(check_id, payload, NATIONAL_VERIFIER)
    )


def refresh_eligibility_check(api: ApiClient, check_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_eligibility_check(check_id, PROGRAM_ADMIN))


def eligible_applicant(
    api: ApiClient,
    address_id: str,
    claimed_basis: str = "INCOME",
    matched_benefit: Optional[str] = None,
    subscriber_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """An applicant screened all the way to VERIFIED_ELIGIBLE on a confirmed check."""
    subscriber = create_subscriber(api, address_id, **(subscriber_overrides or {}))
    check = open_eligibility_check(api, subscriber["id"], claimed_basis=claimed_basis)
    confirmed = confirm_eligibility_check(
        api, check["id"], matched_benefit=matched_benefit
    )
    return {
        "subscriber": refresh_subscriber(api, subscriber["id"]),
        "check": confirmed,
    }


# --------------------------------------------------------------- enrollments


def refresh_enrollment(api: ApiClient, enrollment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_enrollment(enrollment_id, PROGRAM_ADMIN))


def enrollment_version(api: ApiClient, enrollment_id: str) -> int:
    return refresh_enrollment(api, enrollment_id)["version"]


def enroll(
    api: ApiClient,
    provider: Dict[str, Any],
    subscriber: Dict[str, Any],
    check: Dict[str, Any],
    address: Dict[str, Any],
    service_type: str = "VOICE",
    benefit_start_date: Optional[str] = None,
) -> Dict[str, Any]:
    payload = f.enrollment_payload(
        subscriber_id=subscriber["id"],
        provider_id=provider["id"],
        eligibility_check_id=check["id"],
        certified_address_id=address["id"],
        service_type=service_type,
        benefit_start_date=benefit_start_date,
    )
    return get_success_data(api.create_enrollment(payload, provider_headers(provider)))


def active_benefit(
    api: ApiClient,
    provider: Optional[Dict[str, Any]] = None,
    service_type: str = "VOICE",
    benefit_start_date: Optional[str] = None,
    address: Optional[Dict[str, Any]] = None,
    state_code: str = "TX",
    subscriber_overrides: Optional[Dict[str, Any]] = None,
    address_index: int = 1,
) -> Dict[str, Any]:
    """A carrier, a dwelling, a screened applicant and one ACTIVE benefit."""
    provider = provider or register_provider(api, licensed_state_codes=[state_code])
    address = address or register_distinct_address(api, address_index, state_code)
    applicant = eligible_applicant(
        api, address["id"], subscriber_overrides=subscriber_overrides
    )
    enrollment = enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type=service_type,
        benefit_start_date=benefit_start_date,
    )
    return {
        "provider": refresh_provider(api, provider["id"]),
        "address": refresh_address(api, address["id"]),
        "subscriber": refresh_subscriber(api, applicant["subscriber"]["id"]),
        "check": applicant["check"],
        "enrollment": enrollment,
        "agent": provider_headers(provider),
        "holder": subscriber_headers(applicant["subscriber"]),
    }


def additional_benefit_at(
    api: ApiClient,
    provider: Dict[str, Any],
    address: Dict[str, Any],
    service_type: str = "VOICE",
    benefit_start_date: Optional[str] = None,
) -> Dict[str, Any]:
    """A second (or later) benefit at an existing dwelling for a fresh applicant."""
    applicant = eligible_applicant(api, address["id"])
    enrollment = enroll(
        api,
        provider,
        applicant["subscriber"],
        applicant["check"],
        address,
        service_type=service_type,
        benefit_start_date=benefit_start_date,
    )
    return {
        "subscriber": applicant["subscriber"],
        "check": applicant["check"],
        "enrollment": enrollment,
        "holder": subscriber_headers(applicant["subscriber"]),
    }


def de_enroll(
    api: ApiClient,
    enrollment_id: str,
    reason: str = "SUBSCRIBER_REQUEST",
    headers: Optional[Dict[str, str]] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    payload = f.de_enroll_payload(de_enrollment_reason=reason, note=note)
    return get_success_data(
        api.de_enroll(enrollment_id, payload, headers or PROGRAM_ADMIN)
    )


def record_usage(
    api: ApiClient,
    enrollment_id: str,
    headers: Optional[Dict[str, str]] = None,
    usage_at: Optional[str] = None,
) -> Dict[str, Any]:
    payload = f.usage_payload(usage_at=usage_at)
    return get_success_data(
        api.record_usage(enrollment_id, payload, headers or PROGRAM_ADMIN)
    )


def sweep(api: ApiClient, provider_id: str) -> Dict[str, Any]:
    return get_success_data(api.run_compliance_sweep(provider_id, PROGRAM_ADMIN))


# ------------------------------------------------------------------- handsets


def stock_device(
    api: ApiClient,
    provider: Dict[str, Any],
    model_tier: str = "BASIC",
    unit_cost_cents: int = 2100,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = f.device_payload(model_tier=model_tier, unit_cost_cents=unit_cost_cents)
    return get_success_data(
        api.stock_device(provider["id"], payload, headers or PROGRAM_ADMIN)
    )


def stock_devices(
    api: ApiClient, provider: Dict[str, Any], specs: List[Tuple[str, int]]
) -> List[Dict[str, Any]]:
    """Stock handsets in the given order so created_at tie-breaks are predictable."""
    return [
        stock_device(api, provider, model_tier=tier, unit_cost_cents=cost)
        for tier, cost in specs
    ]


def refresh_device(api: ApiClient, device_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_device(device_id, PROGRAM_ADMIN))


def issue_device(
    api: ApiClient,
    enrollment_id: str,
    provider: Dict[str, Any],
    device_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload = f.device_issuance_payload(device_id=device_id)
    return get_success_data(
        api.issue_device(enrollment_id, payload, provider_headers(provider))
    )


def return_device(
    api: ApiClient,
    device_id: str,
    return_condition: str = "GOOD",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    payload = f.device_return_payload(return_condition=return_condition)
    return get_success_data(
        api.return_device(device_id, payload, headers or PROGRAM_ADMIN)
    )


# ------------------------------------------------------------------ transfers


def request_transfer(
    api: ApiClient,
    source_provider: Dict[str, Any],
    enrollment_id: str,
    target_provider_id: str,
    consent_ref: str = "CONSENT-1",
) -> Dict[str, Any]:
    payload = f.service_transfer_payload(
        enrollment_id=enrollment_id,
        target_provider_id=target_provider_id,
        expected_enrollment_version=enrollment_version(api, enrollment_id),
        subscriber_consent_ref=consent_ref,
    )
    return get_success_data(
        api.create_service_transfer(payload, provider_headers(source_provider))
    )


def refresh_transfer(api: ApiClient, transfer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_service_transfer(transfer_id, PROGRAM_ADMIN))


def accept_transfer(
    api: ApiClient, transfer_id: str, target_provider: Dict[str, Any]
) -> Dict[str, Any]:
    return get_success_data(
        api.accept_service_transfer(
            transfer_id, f.transfer_accept_payload(), provider_headers(target_provider)
        )
    )


# --------------------------------------------------------------------- claims


def draft_claim(
    api: ApiClient, provider: Dict[str, Any], service_month: str
) -> Dict[str, Any]:
    payload = f.claim_payload(
        provider_id=provider["id"],
        service_month=service_month,
        expected_provider_version=provider_version(api, provider["id"]),
    )
    return get_success_data(api.create_claim(payload, provider_headers(provider)))


def file_claim(
    api: ApiClient,
    claim_id: str,
    provider: Dict[str, Any],
    certifying_officer_ref: str = "OFFICER-1",
) -> Dict[str, Any]:
    payload = f.claim_file_payload(certifying_officer_ref=certifying_officer_ref)
    return get_success_data(
        api.file_claim(claim_id, payload, provider_headers(provider))
    )


def drafted_and_filed_claim(
    api: ApiClient, provider: Dict[str, Any], service_month: str
) -> Dict[str, Any]:
    draft = draft_claim(api, provider, service_month)
    return file_claim(api, draft["id"], provider)


def refresh_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_claim(claim_id, PROGRAM_ADMIN))


def draw_samples(api: ApiClient, claim_id: str, sample_size: int = 1) -> List[Dict[str, Any]]:
    payload = f.audit_draw_payload(sample_size=sample_size)
    return get_success_data(api.draw_audit_sample(claim_id, payload, AUDITOR_DRAWER))


def refresh_sample(api: ApiClient, sample_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_audit_sample(sample_id, PROGRAM_ADMIN))


def adjudicate(
    api: ApiClient,
    sample_id: str,
    finding: str = "COMPLIANT",
    finding_note: Optional[str] = None,
) -> Dict[str, Any]:
    """Adjudicate with the auditor identity that did not draw the sample."""
    payload = f.adjudicate_payload(finding=finding, finding_note=finding_note)
    return get_success_data(
        api.adjudicate_audit_sample(sample_id, payload, AUDITOR_ADJUDICATOR)
    )


# ---------------------------------------------------------------------- cases


def file_case(
    api: ApiClient,
    subscriber_id: str,
    enrollment_id: str,
    case_type: str = "SERVICE_COMPLAINT",
    headers: Optional[Dict[str, str]] = None,
    narrative: str = "I am asking the program office to review this benefit",
) -> Dict[str, Any]:
    payload = f.subscriber_case_payload(
        subscriber_id=subscriber_id,
        enrollment_id=enrollment_id,
        case_type=case_type,
        narrative=narrative,
    )
    return get_success_data(
        api.create_subscriber_case(payload, headers or PROGRAM_ADMIN)
    )


def assign_review(
    api: ApiClient, case_id: str, reviewer_ref: str = "REV-1"
) -> Dict[str, Any]:
    payload = f.assign_review_payload(reviewer_ref=reviewer_ref)
    return get_success_data(api.assign_case_review(case_id, payload, PROGRAM_ADMIN))


def decide_case(
    api: ApiClient,
    case_id: str,
    decision: str,
    headers: Optional[Dict[str, str]] = None,
    rationale: str = "the record supports this outcome",
) -> Dict[str, Any]:
    payload = f.decide_case_payload(decision=decision, decision_rationale=rationale)
    return get_success_data(
        api.decide_case(case_id, payload, headers or PROGRAM_ADMIN)
    )


def refresh_case(api: ApiClient, case_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_subscriber_case(case_id, PROGRAM_ADMIN))


def under_review_case(
    api: ApiClient,
    subscriber_id: str,
    enrollment_id: str,
    case_type: str = "SERVICE_COMPLAINT",
    reviewer_ref: str = "REV-1",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """A case carried from SUBMITTED to UNDER_REVIEW on review round 1."""
    case = file_case(
        api, subscriber_id, enrollment_id, case_type=case_type, headers=headers
    )
    return assign_review(api, case["id"], reviewer_ref=reviewer_ref)


def de_enrolled_benefit_with_appeal(
    api: ApiClient,
    reason: str = "SUBSCRIBER_REQUEST",
    de_enroller_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """An ACTIVE benefit taken to DE_ENROLLED with an appeal already UNDER_REVIEW."""
    context = active_benefit(api)
    de_enroll(
        api,
        context["enrollment"]["id"],
        reason=reason,
        headers=de_enroller_headers or PROGRAM_ADMIN,
    )
    case = under_review_case(
        api,
        context["subscriber"]["id"],
        context["enrollment"]["id"],
        case_type="DE_ENROLLMENT_APPEAL",
    )
    context["case"] = case
    context["enrollment"] = refresh_enrollment(api, context["enrollment"]["id"])
    return context
