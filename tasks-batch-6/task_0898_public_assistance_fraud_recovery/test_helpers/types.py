"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    INTAKE = "Intake"
    INVESTIGATOR = "Investigator"
    ADJUDICATOR = "Adjudicator"
    RECOVERY_OFFICER = "RecoveryOfficer"
    SUPERVISOR = "Supervisor"


class Program(str, Enum):
    SNAP = "SNAP"
    TANF = "TANF"
    MEDICAID = "MEDICAID"


class ReferralSource(str, Enum):
    HOTLINE = "HOTLINE"
    DATA_MATCH = "DATA_MATCH"
    CASEWORKER = "CASEWORKER"
    PUBLIC = "PUBLIC"


class ReferralStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CONVERTED = "CONVERTED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATION = "INVESTIGATION"
    PENDING_REVIEW = "PENDING_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class EvidenceKind(str, Enum):
    DOCUMENT = "DOCUMENT"
    INTERVIEW = "INTERVIEW"
    DATA_MATCH = "DATA_MATCH"
    SURVEILLANCE = "SURVEILLANCE"


class ClaimType(str, Enum):
    IPV = "IPV"
    IHE = "IHE"
    AE = "AE"


class OverpaymentStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    ESTABLISHED = "ESTABLISHED"
    DEMANDED = "DEMANDED"
    IN_RECOVERY = "IN_RECOVERY"
    SATISFIED = "SATISFIED"
    WRITTEN_OFF = "WRITTEN_OFF"
    TERMINATED = "TERMINATED"


class DisqualificationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ADH_REFERRED = "ADH_REFERRED"
    IMPOSED = "IMPOSED"
    DECLINED = "DECLINED"
    RESCINDED = "RESCINDED"


class SubjectDisqualificationStatus(str, Enum):
    NONE = "NONE"
    DISQUALIFIED = "DISQUALIFIED"
    PERMANENTLY_DISQUALIFIED = "PERMANENTLY_DISQUALIFIED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    DECIDED_IPV = "DECIDED_IPV"
    DECIDED_NO_IPV = "DECIDED_NO_IPV"
    DISMISSED = "DISMISSED"


class HearingOutcome(str, Enum):
    IPV = "IPV"
    NO_IPV = "NO_IPV"
    DISMISSED = "DISMISSED"


class RecoveryMethod(str, Enum):
    RECOUPMENT = "RECOUPMENT"
    OFFSET = "OFFSET"
    COLLECTION = "COLLECTION"


class RecoveryPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class TransactionMethod(str, Enum):
    PAYMENT = "PAYMENT"
    OFFSET = "OFFSET"
    RECOUPMENT = "RECOUPMENT"


class TransactionStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


# ---- Entity TypedDicts ----

# common_fields: true
class Subject(TypedDict):
    id: str
    name: str
    ssn_last4: str
    primary_program: str
    prior_ipv_count: int
    disqualification_status: str
    disqualified_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    subject_id: str
    program: str
    source: str
    allegation_summary: str
    priority_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    referral_id: str
    subject_id: str
    program: str
    assigned_investigator_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only (id + created_at only)
class Evidence(TypedDict):
    id: str
    case_id: str
    kind: str
    description: str
    document_ref: Optional[str]
    submitted_by_user_id: str
    created_at: str


class Overpayment(TypedDict):
    id: str
    case_id: str
    claim_type: str
    status: str
    provisional_amount_cents: int
    final_amount_cents: int
    total_adjustments_cents: int
    accrued_interest_cents: int
    outstanding_principal_cents: int
    outstanding_interest_cents: int
    demand_date: Optional[str]
    due_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable line item (id + created_at only)
class OverpaymentMonth(TypedDict):
    id: str
    overpayment_id: str
    benefit_month: str
    benefits_issued_cents: int
    benefits_entitled_reported_cents: int
    benefits_entitled_verified_cents: int
    over_issuance_reported_cents: int
    over_issuance_verified_cents: int
    created_at: str


class Disqualification(TypedDict):
    id: str
    case_id: str
    subject_id: str
    status: str
    penalty_months: Optional[int]
    is_permanent: Optional[bool]
    imposed_at: Optional[str]
    disqualified_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    disqualification_id: str
    scheduled_date: str
    status: str
    outcome: Optional[str]
    held_at: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecoveryPlan(TypedDict):
    id: str
    overpayment_id: str
    subject_id: str
    method: str
    start_date: str
    end_date: Optional[str]
    monthly_allotment_cents: Optional[int]
    scheduled_monthly_cents: Optional[int]
    monthly_recoupment_cents: Optional[int]
    projected_months_regulatory: Optional[int]
    projected_months_scheduled: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryTransaction(TypedDict):
    id: str
    recovery_plan_id: str
    overpayment_id: str
    amount_cents: int
    transaction_date: str
    method: str
    applied_to_interest_cents: int
    applied_to_principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
