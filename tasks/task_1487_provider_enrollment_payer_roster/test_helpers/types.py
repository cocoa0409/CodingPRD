"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3, §4)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ENROLLMENT_SPECIALIST = "EnrollmentSpecialist"
    PAYER_REPRESENTATIVE = "PayerRepresentative"
    PROVIDER = "Provider"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class CAQHStatus(str, Enum):
    NEVER_ATTESTED = "NEVER_ATTESTED"
    ATTESTED = "ATTESTED"
    DUE = "DUE"
    LAPSED = "LAPSED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDING_INFO = "PENDING_INFO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class RecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING_REVALIDATION = "PENDING_REVALIDATION"
    DEACTIVATED = "DEACTIVATED"
    TERMINATED = "TERMINATED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class RosterFileStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_CONFIRMED = "PARTIALLY_CONFIRMED"
    RECONCILED = "RECONCILED"
    SUPERSEDED = "SUPERSEDED"


class RosterLineStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    DISCREPANCY = "DISCREPANCY"
    SUPERSEDED = "SUPERSEDED"


class ClaimStatus(str, Enum):
    RELEASED = "RELEASED"
    HELD = "HELD"
    DENIED = "DENIED"
    RECOUPED = "RECOUPED"


class DenialReason(str, Enum):
    PAYER_HOLD_DISABLED = "PAYER_HOLD_DISABLED"
    ENROLLMENT_TERMINATED = "ENROLLMENT_TERMINATED"
    ENROLLMENT_DEACTIVATED = "ENROLLMENT_DEACTIVATED"


class EnrollmentScope(str, Enum):
    GROUP_LINK = "GROUP_LINK"
    INDIVIDUAL = "INDIVIDUAL"


class BenefitAssignment(str, Enum):
    GROUP = "GROUP"
    INDIVIDUAL = "INDIVIDUAL"


class EffectiveDatePolicy(str, Enum):
    APPROVAL_DATE = "APPROVAL_DATE"
    RETRO_90 = "RETRO_90"


class RosterLineAction(str, Enum):
    ADD = "ADD"
    TERM = "TERM"


# All ten resources share the common property set of PRD §2.4:
# id, created_at, updated_at, version.


class PracticeGroup(TypedDict):
    id: str
    name: str
    tax_id: str
    group_npi: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    practice_group_id: str
    npi: str
    full_name: str
    specialty: str
    status: str
    termination_date: Optional[str]
    termination_reason: Optional[str]
    recoupment_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Payer(TypedDict):
    id: str
    payer_code: str
    name: str
    is_medicare: bool
    effective_date_policy: str
    claims_hold_enabled: bool
    revalidation_interval_days: int
    created_at: str
    updated_at: str
    version: int


class CAQHProfile(TypedDict):
    id: str
    provider_id: str
    status: str
    last_attested_at: Optional[str]
    due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnrollmentApplication(TypedDict):
    id: str
    provider_id: str
    payer_id: str
    enrollment_scope: str
    requested_effective_date: str
    status: str
    submitted_at: Optional[str]
    approved_at: Optional[str]
    info_request_reason: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnrollmentRecord(TypedDict):
    id: str
    provider_id: str
    payer_id: str
    source_application_id: Optional[str]
    source_roster_line_id: Optional[str]
    enrollment_scope: str
    benefit_assignment: str
    effective_date: str
    termination_date: Optional[str]
    last_revalidation_completed_at: str
    revalidation_due_date: str
    revalidation_window_start: str
    gross_impacted_cents: int
    net_recouped_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DelegatedCredentialingAgreement(TypedDict):
    id: str
    practice_group_id: str
    payer_id: str
    effective_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RosterFile(TypedDict):
    id: str
    agreement_id: str
    submitted_by_user_id: str
    submitted_at: str
    status: str
    total_lines: int
    pending_count: int
    confirmed_count: int
    rejected_count: int
    discrepancy_count: int
    superseded_count: int
    created_at: str
    updated_at: str
    version: int


class RosterLine(TypedDict):
    id: str
    roster_file_id: str
    provider_id: str
    line_index: int
    action: str
    enrollment_scope: Optional[str]
    benefit_assignment: Optional[str]
    expected_effective_date: str
    confirmed_effective_date: Optional[str]
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    provider_id: str
    payer_id: str
    service_date: str
    amount_cents: int
    status: str
    denial_reason: Optional[str]
    recoupment_fee_cents: int
    created_at: str
    updated_at: str
    version: int
