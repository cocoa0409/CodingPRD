"""Domain types: entity TypedDicts, status enums, role enum.

All enums and shapes are derived from the Probation & Parole Case Management
API contract (PRD). Append-only entities (Payment) carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ────────────────────────────────────────────────
class UserRole(str, Enum):
    OFFICER = "Officer"
    SUPERVISING_JUDGE = "SupervisingJudge"
    COMPACT_ADMINISTRATOR = "CompactAdministrator"


# ─── Status / level enums ────────────────────────────────────────────────
class SuperviseeStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    ABSCONDED = "ABSCONDED"
    REVOCATION_PENDING = "REVOCATION_PENDING"
    REVOKED = "REVOKED"
    TERMINATED_EARLY = "TERMINATED_EARLY"
    COMPLETED = "COMPLETED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class SupervisionLevel(str, Enum):
    ADMINISTRATIVE = "ADMINISTRATIVE"
    MINIMUM = "MINIMUM"
    MEDIUM = "MEDIUM"
    MAXIMUM = "MAXIMUM"


class SupervisionType(str, Enum):
    PROBATION = "PROBATION"
    PAROLE = "PAROLE"


class RiskAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class ConditionType(str, Enum):
    DRUG_TESTING = "DRUG_TESTING"
    CURFEW = "CURFEW"
    NO_CONTACT = "NO_CONTACT"
    EMPLOYMENT = "EMPLOYMENT"
    TREATMENT = "TREATMENT"
    ELECTRONIC_MONITORING = "ELECTRONIC_MONITORING"
    TRAVEL_RESTRICTION = "TRAVEL_RESTRICTION"


class ConditionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SATISFIED = "SATISFIED"
    WAIVED = "WAIVED"
    SUSPENDED = "SUSPENDED"


class CheckInStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ATTENDED = "ATTENDED"
    MISSED = "MISSED"
    EXCUSED = "EXCUSED"


class Punctuality(str, Enum):
    ON_TIME = "ON_TIME"
    LATE = "LATE"


class DrugTestPanel(str, Enum):
    FIVE_PANEL = "FIVE_PANEL"
    TEN_PANEL = "TEN_PANEL"


class DrugTestResult(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    DILUTE = "DILUTE"
    REFUSED = "REFUSED"


class ViolationClass(str, Enum):
    TECHNICAL = "TECHNICAL"
    MISDEMEANOR = "MISDEMEANOR"
    FELONY = "FELONY"
    ABSCOND = "ABSCOND"


class ViolationStatus(str, Enum):
    FILED = "FILED"
    SUSTAINED = "SUSTAINED"
    DISMISSED = "DISMISSED"
    APPEALED = "APPEALED"


class SanctionType(str, Enum):
    VERBAL_WARNING = "VERBAL_WARNING"
    INCREASED_REPORTING = "INCREASED_REPORTING"
    CURFEW_IMPOSITION = "CURFEW_IMPOSITION"
    JAIL_SHOCK = "JAIL_SHOCK"
    REVOCATION_REFERRAL = "REVOCATION_REFERRAL"


class SanctionStatus(str, Enum):
    IMPOSED = "IMPOSED"
    COMPLETED = "COMPLETED"
    VACATED = "VACATED"


class ObligationType(str, Enum):
    RESTITUTION = "RESTITUTION"
    FEE = "FEE"


class ObligationStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISCHARGED = "DISCHARGED"


class AllocationPolicy(str, Enum):
    RESTITUTION_FIRST = "RESTITUTION_FIRST"
    OLDEST_FIRST = "OLDEST_FIRST"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class EarlyTerminationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class ReportType(str, Enum):
    PROGRESS = "PROGRESS"
    VIOLATION_SUMMARY = "VIOLATION_SUMMARY"
    EARLY_TERMINATION = "EARLY_TERMINATION"
    REVOCATION = "REVOCATION"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"


# ─── Entity TypedDicts (common_fields: true unless noted) ────────────────
class Officer(TypedDict):
    id: str
    full_name: str
    badge_number: str
    role_type: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Supervisee(TypedDict):
    id: str
    full_name: str
    docket_number: str
    supervision_type: str
    assigned_officer_id: str
    sentence_state_code: str
    ordered_term_months: int
    supervision_start_date: str
    status: str
    supervision_level: str
    cumulative_violation_points: int
    restitution_balance_cents: int
    fee_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict):
    id: str
    supervisee_id: str
    instrument: str
    domain_scores: dict
    total_score: int
    derived_level: str
    assessment_status: str
    override_level: Optional[str]
    override_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupervisionCondition(TypedDict):
    id: str
    supervisee_id: str
    condition_type: str
    minimum_level_required: str
    status: str
    description: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CheckIn(TypedDict):
    id: str
    supervisee_id: str
    scheduled_for: str
    window_minutes: int
    requires_drug_test: bool
    status: str
    attended_at: Optional[str]
    punctuality: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DrugTest(TypedDict):
    id: str
    check_in_id: str
    panel: str
    result: str
    substances: List[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    supervisee_id: str
    filed_by_officer_id: str
    violation_class: str
    source_drug_test_id: Optional[str]
    points: int
    status: str
    sustained_by_actor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sanction(TypedDict):
    id: str
    violation_id: str
    sanction_type: str
    imposed_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancialObligation(TypedDict):
    id: str
    supervisee_id: str
    parent_obligation_id: Optional[str]
    obligation_type: str
    principal_cents: int
    monthly_accrual_cents: int
    recurring: bool
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only posting record, NO updated_at, NO version
class Payment(TypedDict):
    id: str
    supervisee_id: str
    amount_cents: int
    allocation_policy: str
    applied_breakdown: dict
    posted_at: str
    created_at: str


class CourtReport(TypedDict):
    id: str
    supervisee_id: str
    report_type: str
    as_of_date: str
    snapshot: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class InterstateTransfer(TypedDict):
    id: str
    supervisee_id: str
    receiving_state_code: str
    expected_supervisee_version: int
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EarlyTermination(TypedDict):
    id: str
    supervisee_id: str
    requested_on: str
    months_served: int
    eligibility: dict
    status: str
    created_at: str
    updated_at: str
    version: int
