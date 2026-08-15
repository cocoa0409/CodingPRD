"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class DistrictStatus(str, Enum):
    DRAFT = "DRAFT"
    PETITIONING = "PETITIONING"
    SCOPING = "SCOPING"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    OBJECTION_WINDOW = "OBJECTION_WINDOW"
    COUNCIL_REVIEW = "COUNCIL_REVIEW"
    APPROVED = "APPROVED"
    CONSTRUCTION = "CONSTRUCTION"
    TRUE_UP = "TRUE_UP"
    BILLING = "BILLING"
    ACCEPTED = "ACCEPTED"
    ABANDONED = "ABANDONED"


class PetitionStatus(str, Enum):
    CIRCULATING = "CIRCULATING"
    CLOSED_VERIFIED = "CLOSED_VERIFIED"
    CLOSED_INSUFFICIENT = "CLOSED_INSUFFICIENT"
    VOIDED = "VOIDED"


class SignatureStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    VOIDED = "VOIDED"


class EstimateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class ObjectionStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"
    WITHDRAWN = "WITHDRAWN"


class AssessmentStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    SUPERSEDED = "SUPERSEDED"
    LEVIED = "LEVIED"
    PREPAID = "PREPAID"
    SETTLEMENT_DUE = "SETTLEMENT_DUE"
    IN_REPAYMENT = "IN_REPAYMENT"
    DELINQUENT = "DELINQUENT"
    PAID_OFF = "PAID_OFF"
    REMOVED = "REMOVED"


class PhaseStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InvoiceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    CITY_CLERK = "CityClerk"
    CITY_ENGINEER = "CityEngineer"
    FINANCE_OFFICER = "FinanceOfficer"
    COUNCIL_PRESIDENT = "CouncilPresident"
    PROPERTY_OWNER = "PropertyOwner"


# --- Entity TypedDicts (all carry id + created_at + updated_at + version,
#     except the append-only Payment which carries only id + created_at) ---


class District(TypedDict, total=False):
    id: str
    name: str
    methodology: str
    interest_method: str
    annual_interest_rate_bp: int
    season_start_mmdd: str
    season_end_mmdd: str
    status: str
    remand_count: int
    total_frontage_ft: float
    eligible_parcel_count: int
    protest_frontage_pct: Optional[float]
    approved_estimate_id: Optional[str]
    approved_change_total_cents: int
    overrun_flag: bool
    final_total_cost_cents: Optional[int]
    levy_date: Optional[str]
    payment_option_deadline: Optional[str]
    paid_assessment_count: int
    total_assessment_count: int
    all_assessments_paid: bool
    created_at: str
    updated_at: str
    version: int


class PropertyOwner(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    mailing_address: str
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict, total=False):
    id: str
    district_id: str
    owner_id: str
    parcel_number: str
    frontage_ft: float
    exempt: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Petition(TypedDict, total=False):
    id: str
    district_id: str
    status: str
    opened_at: str
    closed_at: Optional[str]
    verified_signature_count: int
    verified_frontage_ft: float
    eligible_parcel_count_snapshot: Optional[int]
    eligible_frontage_snapshot: Optional[float]
    support_count_pct: Optional[float]
    support_frontage_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class PetitionSignature(TypedDict, total=False):
    id: str
    petition_id: str
    parcel_id: str
    owner_id: str
    signed_at: str
    status: str
    rejection_reason: Optional[str]
    verified_by: Optional[str]
    verified_at: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostEstimate(TypedDict, total=False):
    id: str
    district_id: str
    estimate_seq: int
    contract_price_cents: int
    contingency_cents: int
    total_estimated_cost_cents: int
    status: str
    submitted_by: str
    created_at: str
    updated_at: str
    version: int


class PublicHearing(TypedDict, total=False):
    id: str
    district_id: str
    hearing_date: str
    venue: str
    status: str
    objection_window_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Objection(TypedDict, total=False):
    id: str
    district_id: str
    hearing_id: str
    parcel_id: str
    owner_id: str
    grounds: str
    status: str
    filed_at: str
    reviewed_by: Optional[str]
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CouncilResolution(TypedDict, total=False):
    id: str
    district_id: str
    motion: str
    votes_for: int
    votes_against: int
    outcome: str
    protest_pct_snapshot: Optional[float]
    required_votes_snapshot: int
    recorded_by: str
    created_at: str
    updated_at: str
    version: int


class ParcelAssessment(TypedDict, total=False):
    id: str
    district_id: str
    parcel_id: str
    preliminary_amount_cents: int
    final_levy_cents: Optional[int]
    payment_option: str
    term_years: Optional[int]
    principal_balance_cents: int
    total_paid_cents: int
    credit_balance_cents: int
    total_refunded_cents: int
    status: str
    option_selected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConstructionPhase(TypedDict, total=False):
    id: str
    district_id: str
    name: str
    crew_name: str
    start_date: str
    end_date: str
    estimated_cost_cents: int
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    district_id: str
    phase_id: Optional[str]
    description: str
    amount_cents: int
    status: str
    proposed_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstallmentInvoice(TypedDict, total=False):
    id: str
    district_id: str
    parcel_assessment_id: str
    kind: str
    year_index: int
    issue_date: str
    due_date: str
    principal_cents: int
    interest_cents: int
    penalty_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only event: NO updated_at, NO version (PRD: "a payment is an
# append-only event and carries only id and created_at").
class Payment(TypedDict, total=False):
    id: str
    created_at: str
    parcel_assessment_id: str
    amount_cents: int
    method: str
    received_at: str
    applied_penalty_cents: int
    applied_interest_cents: int
    applied_principal_cents: int
