"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    STATE_AGENCY = "StateAgency"
    MCO_ENCOUNTER_OPS = "McoEncounterOps"
    MCO_COMPLIANCE = "McoCompliance"
    MCO_FINANCE = "McoFinance"
    DELEGATED_SUBMITTER = "DelegatedSubmitter"


class ProgramPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"


class AidCategory(str, Enum):
    TANF = "TANF"
    SSI = "SSI"
    DUAL = "DUAL"
    EXPANSION = "EXPANSION"
    CHIP = "CHIP"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISENROLLED = "DISENROLLED"


class ProviderContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class QualityTier(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class SubmitterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExtensionStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class EncounterStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    STAGED = "STAGED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DENIED = "DENIED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class FindingTier(str, Enum):
    SYNTAX = "SYNTAX"
    REFERENTIAL = "REFERENTIAL"
    BUSINESS = "BUSINESS"


class FindingSeverity(str, Enum):
    FATAL = "FATAL"
    WARN = "WARN"


class FindingOrigin(str, Enum):
    MCO_EDIT = "MCO_EDIT"
    STATE_ACK = "STATE_ACK"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    TRANSMITTED = "TRANSMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIAL = "PARTIAL"
    REJECTED_BATCH = "REJECTED_BATCH"
    RECONCILED = "RECONCILED"
    DISCARDED = "DISCARDED"


class AuditStatus(str, Enum):
    DRAFT = "DRAFT"
    DETERMINED = "DETERMINED"


class AuditDetermination(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PenaltyReason(str, Enum):
    COMPLETENESS = "COMPLETENESS"
    ACCURACY = "ACCURACY"
    COMBINED = "COMBINED"
    LATE_SUBMISSION = "LATE_SUBMISSION"


class PenaltyStatus(str, Enum):
    ASSESSED = "ASSESSED"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    WAIVED = "WAIVED"
    REDUCED = "REDUCED"
    PAID = "PAID"


class StatementStatus(str, Enum):
    PROVISIONAL_ISSUED = "PROVISIONAL_ISSUED"
    RECONCILED = "RECONCILED"


class SnapshotStatus(str, Enum):
    COMPUTED = "COMPUTED"
    APPLIED = "APPLIED"


class ScorecardStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# --- Entity TypedDicts (primary resources carry common fields) ---


class Program(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    companion_guide_version: str
    completeness_threshold: float
    accuracy_threshold: float
    provider_yellow_threshold: float
    provider_red_threshold: float
    penalty_cap_percent: float
    penalty_threshold_cents: int
    posture: str
    penalties_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    program_id: str
    medicaid_id: str
    aid_category: str
    enrolled_from: str
    enrolled_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    program_id: str
    npi: str
    taxonomy_code: str
    contract_status: str
    quality_tier: str
    created_at: str
    updated_at: str
    version: int


class Submitter(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    trading_partner_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SubmissionCycle(TypedDict, total=False):
    id: str
    program_id: str
    label: str
    window_start_at: str
    window_end_at: str
    submission_deadline_at: str
    effective_deadline_at: str
    extension_status: str
    requested_new_deadline_at: Optional[str]
    status: str
    intake_encounter_count: int
    net_accepted_encounter_count: int
    net_accepted_paid_cents: int
    risk_computed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapitationRateSchedule(TypedDict, total=False):
    id: str
    program_id: str
    aid_category: str
    pmpm_cents: int
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict, total=False):
    id: str
    program_id: str
    member_id: str
    provider_id: str
    submitter_id: Optional[str]
    attributed_cycle_id: str
    batch_id: Optional[str]
    replaces_encounter_id: Optional[str]
    encounter_ref: str
    service_from_date: str
    service_to_date: str
    place_of_service: str
    diagnosis_codes: List[str]
    paid_amount_cents: int
    correction_sequence: int
    validation_run_seq: int
    status: str
    created_at: str
    updated_at: str
    version: int


# EncounterLine: append-only child row — id + created_at only (no updated_at / version)
class EncounterLine(TypedDict, total=False):
    id: str
    encounter_id: str
    line_number: int
    procedure_code: str
    modifiers: List[str]
    units: int
    billed_amount_cents: int
    paid_amount_cents: int
    created_at: str


# ValidationFinding: append-only child row — id + created_at only (no updated_at / version)
class ValidationFinding(TypedDict, total=False):
    id: str
    encounter_id: str
    run_seq: int
    edit_code: str
    tier: str
    severity: str
    origin: str
    field_path: str
    message: str
    created_at: str


class SubmissionBatch(TypedDict, total=False):
    id: str
    cycle_id: str
    status: str
    encounter_count: int
    total_paid_cents: int
    sealed_encounter_count: Optional[int]
    sealed_total_paid_cents: Optional[int]
    sealed_by_user_id: Optional[str]
    transmitted_by_user_id: Optional[str]
    transmitted_at: Optional[str]
    late: bool
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict, total=False):
    id: str
    cycle_id: str
    sample_size: int
    defect_count: int
    completeness_intake_rate: float
    completeness_eligibility_rate: float
    accuracy_rate: float
    determination: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PenaltyAssessment(TypedDict, total=False):
    id: str
    cycle_id: str
    audit_id: Optional[str]
    reason: str
    amount_cents: int
    reduced_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitationStatement(TypedDict, total=False):
    id: str
    cycle_id: str
    member_months: int
    provisional_paid_cents: int
    final_amount_cents: Optional[int]
    adjustment_cents: Optional[int]
    withhold_applied: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RiskScoreSnapshot(TypedDict, total=False):
    id: str
    cycle_id: str
    member_id: str
    raw_score: float
    normalized_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ProviderScorecard(TypedDict, total=False):
    id: str
    cycle_id: str
    provider_id: str
    run_count: int
    fatal_finding_count: int
    error_rate: float
    tier: str
    status: str
    created_at: str
    updated_at: str
    version: int
