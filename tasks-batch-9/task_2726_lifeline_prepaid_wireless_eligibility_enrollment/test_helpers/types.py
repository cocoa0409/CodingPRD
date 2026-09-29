"""TypedDict shapes and role names for the Lifeline API resources."""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class Role(str, Enum):
    """The five roles the API recognises."""

    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    PROVIDER_AGENT = "ProviderAgent"
    NATIONAL_VERIFIER = "NationalVerifier"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    SUBSCRIBER = "Subscriber"


ALL_ROLES = [r.value for r in Role]


class CommonFields(TypedDict):
    """Properties every resource in this API carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Provider(CommonFields):
    name: str
    spin_id: str
    study_area_code: str
    licensed_state_codes: List[str]
    status: str
    enrollment_cap: int
    active_enrollment_count: int
    devices_total_count: int
    devices_in_stock_count: int
    devices_issued_count: int
    devices_reclaim_pending_count: int
    devices_retired_count: int
    open_claim_count: int
    claim_gross_cents: int
    recouped_cents: int
    net_reimbursed_cents: int
    audit_hold_flag: bool


class HouseholdAddress(CommonFields):
    address_line1: str
    unit_designator: Optional[str]
    city: str
    state_code: str
    postal_code: str
    address_hash: str
    status: str
    declared_household_count: Optional[int]
    independent_household_worksheet_ref: Optional[str]
    max_permitted_benefit_slots: int
    occupied_benefit_slots: int
    cohort_address_count: int


class Subscriber(CommonFields):
    address_id: str
    full_name: str
    date_of_birth: str
    last4_ssn: str
    household_size: int
    annual_income_cents: int
    last_3mo_income_cents: Optional[int]
    qualifying_benefit: str
    tribal_lands_flag: bool
    identity_key: str
    status: str
    eligibility_basis: str
    income_threshold_cents: int
    de_enrollment_count: int


class EligibilityCheck(CommonFields):
    subscriber_id: str
    claimed_basis: str
    proof_document_ref: Optional[str]
    income_variant: str
    evaluated_income_cents: Optional[int]
    income_threshold_cents: Optional[int]
    status: str
    verifier_outcome: Optional[str]
    verifier_reason_code: Optional[str]
    matched_benefit: Optional[str]
    confirmed_at: Optional[str]
    expires_at: Optional[str]
    resubmission_count: int


class Enrollment(CommonFields):
    subscriber_id: str
    provider_id: str
    eligibility_check_id: str
    certified_address_id: str
    service_type: str
    one_per_household_attested: bool
    benefit_status: str
    usage_status: str
    recert_status: str
    device_status: str
    benefit_start_date: str
    benefit_end_date: Optional[str]
    port_freeze_until: str
    last_usage_at: Optional[str]
    non_usage_flagged_at: Optional[str]
    cure_deadline_at: Optional[str]
    recert_due_date: str
    recert_notice_sent_at: Optional[str]
    recert_response_deadline_at: Optional[str]
    recert_last_responded_at: Optional[str]
    recert_evaluated_income_cents: Optional[int]
    recert_income_threshold_cents: Optional[int]
    de_enrollment_reason: Optional[str]
    de_enrolled_at: Optional[str]
    de_enrolled_by_ref: Optional[str]
    appeal_deadline_at: Optional[str]
    last_device_issued_at: Optional[str]
    device_issuance_count: int
    transfer_count: int
    reinstatement_count: int
    audit_risk_score: int


class Device(CommonFields):
    provider_id: str
    imei: str
    model_tier: str
    unit_cost_cents: int
    status: str
    issued_enrollment_id: Optional[str]
    issued_at: Optional[str]
    returned_at: Optional[str]
    return_condition: Optional[str]


class ServiceTransfer(CommonFields):
    enrollment_id: str
    target_provider_id: str
    source_provider_id: str
    subscriber_consent_ref: str
    status: str
    rejection_reason: Optional[str]
    requested_at: str
    completed_at: Optional[str]
    port_freeze_until_snapshot: str


class ReimbursementClaim(CommonFields):
    provider_id: str
    service_month: str
    status: str
    provisional_amount_cents: int
    final_amount_cents: int
    variance_cents: int
    covered_enrollment_count: int
    certifying_officer_ref: Optional[str]
    filed_at: Optional[str]
    audit_sample_count: int
    failed_sample_count: int
    sample_drawn_by_ref: Optional[str]
    recoupment_amount_cents: int
    penalty_cents: int
    net_payable_cents: int


class AuditSample(CommonFields):
    claim_id: str
    enrollment_id: str
    selection_rank: int
    risk_score_at_draw: int
    claimed_line_cents: int
    drawn_by_ref: str
    status: str
    finding: Optional[str]
    finding_note: Optional[str]
    adjudicated_by_ref: Optional[str]
    disallowed_support_cents: int


class SubscriberCase(CommonFields):
    subscriber_id: str
    enrollment_id: str
    case_type: str
    narrative: str
    status: str
    reviewer_ref: Optional[str]
    review_round: int
    decision: Optional[str]
    decision_rationale: Optional[str]
    decided_at: Optional[str]
    decided_by_ref: Optional[str]
    reinstated_enrollment_flag: bool


class SweepResult(TypedDict):
    swept_at: str
    evaluated_enrollment_count: int
    non_usage_flagged_enrollment_ids: List[str]
    cure_expired_de_enrolled_enrollment_ids: List[str]
    recert_noticed_enrollment_ids: List[str]
    recert_non_response_de_enrolled_enrollment_ids: List[str]


JsonDict = Dict[str, Any]
