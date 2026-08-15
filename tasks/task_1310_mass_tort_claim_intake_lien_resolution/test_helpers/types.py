"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    INTAKE_SPECIALIST = "IntakeSpecialist"
    RECORDS_ANALYST = "RecordsAnalyst"
    LIEN_ANALYST = "LienAnalyst"
    DISBURSEMENT_APPROVER = "DisbursementApprover"
    CLAIMANT_ROLE = "ClaimantRole"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ELIGIBILITY_PASSED = "ELIGIBILITY_PASSED"
    RECORDS_PENDING = "RECORDS_PENDING"
    INJURY_VERIFIED = "INJURY_VERIFIED"
    TIER_ASSIGNED = "TIER_ASSIGNED"
    LIENS_PENDING = "LIENS_PENDING"
    LIENS_RESOLVED = "LIENS_RESOLVED"
    READY_FOR_DISBURSEMENT = "READY_FOR_DISBURSEMENT"
    DISBURSED = "DISBURSED"
    CLOSED = "CLOSED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class InjuryVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class LienPosture(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IDENTIFYING = "IDENTIFYING"
    NEGOTIATING = "NEGOTIATING"
    ALL_RESOLVED = "ALL_RESOLVED"


class InjuryCategory(str, Enum):
    QUALIFYING_CAT_A = "QUALIFYING_CAT_A"
    QUALIFYING_CAT_B = "QUALIFYING_CAT_B"
    NON_QUALIFYING = "NON_QUALIFYING"


class MatrixState(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class RecordType(str, Enum):
    DIAGNOSTIC = "DIAGNOSTIC"
    TREATMENT = "TREATMENT"
    PHARMACY = "PHARMACY"
    HOSPITALIZATION = "HOSPITALIZATION"


class ReviewState(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class LienType(str, Enum):
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    PRIVATE_INSURER = "PRIVATE_INSURER"
    MEDICAL_PROVIDER = "MEDICAL_PROVIDER"
    VA_TRICARE = "VA_TRICARE"


class LienState(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    NOTIFIED = "NOTIFIED"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"
    DISPUTED = "DISPUTED"


class AppealState(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class DisbursementState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class PayeeRole(str, Enum):
    CLAIMANT = "CLAIMANT"
    ATTORNEY = "ATTORNEY"
    LIEN_HOLDER = "LIEN_HOLDER"


# common_fields: true — carries id + created_at + updated_at + version (PRD §2.4)
class SettlementProgram(TypedDict):
    id: str
    program_code: str
    tort_name: str
    current_utc: str
    qsf_principal_cents: int
    qsf_remaining_cents: int
    matrix_published: bool
    created_at: str
    updated_at: str
    version: int


class Claimant(TypedDict):
    id: str
    settlement_program_id: str
    full_name: str
    date_of_birth: str
    ssn_last4: str
    date_of_exposure_start: str
    date_of_exposure_end: str
    date_of_diagnosis: str
    injury_category: str
    represented_by_counsel: bool
    duplicate_of_claimant_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    settlement_program_id: str
    claimant_id: str
    claim_number: str
    status: str
    eligibility_status: str
    injury_verification_status: str
    lien_posture: str
    denied_reason: Optional[str]
    gross_award_cents: int
    total_lien_cents: int
    attorney_fee_cents: int
    net_award_cents: int
    qsf_reservation_cents: int
    active_appeal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TierMatrix(TypedDict):
    id: str
    settlement_program_id: str
    injury_category: str
    severity_score_min: int
    severity_score_max: int
    base_award_cents: int
    matrix_state: str
    created_at: str
    updated_at: str
    version: int


class MedicalRecord(TypedDict):
    id: str
    claim_id: str
    provider_name: str
    record_type: str
    received_at: str
    severity_score: int
    confirms_qualifying_injury: bool
    review_state: str
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict):
    id: str
    claim_id: str
    lien_type: str
    holder_name: str
    asserted_amount_cents: int
    provisional_demand_cents: int
    final_demand_cents: int
    holder_response_due_at: str
    resolution_notes: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    claim_id: str
    appealed_tier_matrix_id: str
    requested_tier_matrix_id: str
    grounds: str
    state: str
    resolution_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    claim_id: str
    payee_name: str
    payee_role: str
    amount_cents: int
    state: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only artifact; carries ONLY id + created_at (PRD §2.4)
class ClosingStatement(TypedDict):
    id: str
    claim_id: str
    gross_award_cents: int
    total_lien_cents: int
    attorney_fee_cents: int
    net_award_cents: int
    statement_body: str
    sealed_at: str
    created_at: str
