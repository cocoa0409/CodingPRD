"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, List, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ELIGIBILITY_ANALYST = "EligibilityAnalyst"
    COB_ANALYST = "COBAnalyst"
    CLAIMS_EXAMINER = "ClaimsExaminer"
    RECOVERY_SPECIALIST = "RecoverySpecialist"
    COB_AUDITOR = "COBAuditor"
    MEMBER_SELF = "MemberSelf"


class COBRuleConfigStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class MemberStatus(str, Enum):
    ENROLLED = "ENROLLED"
    DISENROLLED = "DISENROLLED"


class CoverageVerificationStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class LeadDisposition(str, Enum):
    RECEIVED = "RECEIVED"
    VERIFIED_COVERAGE = "VERIFIED_COVERAGE"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_NO_COVERAGE = "REJECTED_NO_COVERAGE"


class DeterminationStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class MSPQuestionnaireStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    VOIDED = "VOIDED"


class MSPResult(str, Enum):
    MEDICARE_PRIMARY = "MEDICARE_PRIMARY"
    MEDICARE_SECONDARY = "MEDICARE_SECONDARY"
    MSP_EXEMPT = "MSP_EXEMPT"


class ClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ADJUDICATED = "ADJUDICATED"
    PAID = "PAID"
    REOPENED = "REOPENED"
    READJUDICATED = "READJUDICATED"
    REPAID = "REPAID"
    CLOSED = "CLOSED"


class ClaimAdjustmentStatus(str, Enum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class RecoveryRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    FULLY_RECOVERED = "FULLY_RECOVERED"
    ESCALATED = "ESCALATED"
    WRITTEN_OFF = "WRITTEN_OFF"


class SavingsPeriodPosture(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MemberSurveyStatus(str, Enum):
    SENT = "SENT"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"


class DecidingRule(str, Enum):
    NONE = "NONE"
    BIRTHDAY_RULE = "BIRTHDAY_RULE"
    GENDER_RULE = "GENDER_RULE"
    CUSTODIAL_DECREE = "CUSTODIAL_DECREE"
    ACTIVE_VS_RETIRED = "ACTIVE_VS_RETIRED"
    MEDICARE_MSP = "MEDICARE_MSP"
    COURT_ORDER = "COURT_ORDER"
    LONGER_ENROLLMENT = "LONGER_ENROLLMENT"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version except Reimbursement) ---


class COBRuleConfig(TypedDict, total=False):
    id: str
    config_name: str
    dependent_primacy_rule: str
    msp_employer_size_threshold: int
    esrd_coordination_months: int
    retroactive_lookback_months: int
    recovery_window_days: int
    savings_period_length_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    member_external_id: str
    full_name: str
    date_of_birth: str
    gender: str
    relation_to_subscriber: str
    subscriber_member_id: Optional[str]
    employment_status: str
    employer_size: int
    custodial_decree_on_file: bool
    medicare_entitlement_reason: str
    esrd_onset_date: Optional[str]
    other_coverage_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Coverage(TypedDict, total=False):
    id: str
    member_id: str
    payer_id: str
    plan_name: str
    coverage_kind: str
    subscriber_relationship: str
    policy_holder_dob: str
    policy_holder_gender: str
    effective_from: str
    effective_to: Optional[str]
    verification_source: str
    verification_status: str
    is_ours: bool
    created_at: str
    updated_at: str
    version: int


class OtherCoverageLead(TypedDict, total=False):
    id: str
    member_id: str
    source: str
    raw_payload: str
    received_at: str
    disposition: str
    created_at: str
    updated_at: str
    version: int


class PrimacyDetermination(TypedDict, total=False):
    id: str
    member_id: str
    as_of_service_date: str
    deciding_rule: str
    ordered_coverage_ids: List[str]
    msp_questionnaire_id: Optional[str]
    superseded_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MSPQuestionnaire(TypedDict, total=False):
    id: str
    member_id: str
    respondent_role: str
    age_at_submission: int
    is_age_65_plus: bool
    has_employer_group_health: bool
    employer_size: int
    disability_flag: bool
    esrd_flag: bool
    esrd_onset_date: Optional[str]
    msp_result: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    member_id: str
    provider_id: str
    claim_external_id: str
    service_date: str
    received_date: str
    total_billed_cents: int
    total_allowed_cents: int
    total_paid_cents: int
    total_primary_paid_cents: int
    primacy_determination_id: Optional[str]
    rework_cycle_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    id: str
    claim_id: str
    line_number: int
    procedure_code: str
    billed_cents: int
    allowed_cents: int
    primary_paid_cents: int
    paid_cents: int
    created_at: str
    updated_at: str
    version: int


class ClaimAdjustment(TypedDict, total=False):
    id: str
    claim_id: str
    cause: str
    triggering_determination_id: Optional[str]
    pre_paid_cents: int
    post_paid_cents: int
    overpayment_cents: int
    underpayment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    npi: str
    legal_name: str
    tin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryRequest(TypedDict, total=False):
    id: str
    claim_id: str
    provider_id: str
    amount_cents: int
    issued_at: str
    due_date: str
    amount_recovered_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reimbursement(TypedDict, total=False):
    # Immutable ledger posting (PRD §2.4): carries ONLY id and created_at —
    # no updated_at, no version.
    id: str
    recovery_request_id: str
    amount_cents: int
    received_at: str
    method: str
    created_at: str


class COBSavingsPeriod(TypedDict, total=False):
    id: str
    period_start_date: str
    period_end_date: str
    total_avoided_cents: int
    total_recovered_cents: int
    total_claims_adjusted: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class MemberSurvey(TypedDict, total=False):
    id: str
    member_id: str
    sent_at: str
    due_at: str
    response_payload: Optional[str]
    responded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
