"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    DISTRICT_ADMINISTRATOR = "DistrictAdministrator"
    BOARD_MEMBER = "BoardMember"
    TAX_COLLECTOR = "TaxCollector"
    PROPERTY_OWNER = "PropertyOwner"
    AMBASSADOR = "Ambassador"


class BidStatus(str, Enum):
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    EXPIRED = "EXPIRED"


class ParcelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class UseClass(str, Enum):
    RETAIL = "RETAIL"
    OFFICE = "OFFICE"
    COMMERCIAL = "COMMERCIAL"
    MIXED = "MIXED"
    INDUSTRIAL = "INDUSTRIAL"
    RESIDENTIAL_EXEMPT = "RESIDENTIAL_EXEMPT"
    NONPROFIT_EXEMPT = "NONPROFIT_EXEMPT"


class FiscalYearStatus(str, Enum):
    UPCOMING = "UPCOMING"
    ACTIVE = "ACTIVE"


class BudgetStatus(str, Enum):
    NONE = "NONE"
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    ADOPTED = "ADOPTED"


class CollectionStatus(str, Enum):
    OPEN = "OPEN"
    FULLY_COLLECTED = "FULLY_COLLECTED"


class BudgetState(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    ADOPTED = "ADOPTED"


class WorkPlanCategory(str, Enum):
    CLEAN = "CLEAN"
    SAFE = "SAFE"
    MARKETING = "MARKETING"
    ADMIN = "ADMIN"
    CONTINGENCY = "CONTINGENCY"


class AssessmentStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    CERTIFIED = "CERTIFIED"
    ADJUSTED = "ADJUSTED"
    CANCELLED = "CANCELLED"


class CollectionAccountStatus(str, Enum):
    BILLED = "BILLED"
    DELINQUENT = "DELINQUENT"
    PAID = "PAID"
    CREDIT = "CREDIT"
    WRITTEN_OFF = "WRITTEN_OFF"


class PaymentMethod(str, Enum):
    TAX_ROLL = "TAX_ROLL"
    ACH = "ACH"
    CHECK = "CHECK"
    CARD = "CARD"


class DisputeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    RESOLVED_ADJUSTED = "RESOLVED_ADJUSTED"
    RESOLVED_DENIED = "RESOLVED_DENIED"
    WITHDRAWN = "WITHDRAWN"


class PetitionStatus(str, Enum):
    CIRCULATING = "CIRCULATING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AmbassadorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ServiceRole(str, Enum):
    CLEAN = "CLEAN"
    SAFE = "SAFE"
    OUTREACH = "OUTREACH"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class ServiceRequestStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


# --- Entity shapes (common_fields: true carry id/created_at/updated_at/version) ---

class BusinessImprovementDistrict(TypedDict):
    id: str
    name: str
    boundary_description: str
    authorization_expires_at: str
    assessment_weight_value: float
    assessment_weight_frontage: float
    assessment_weight_sqft: float
    min_assessment_cents: int
    max_assessment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    bid_id: str
    apn: str
    owner_name: str
    use_class: str
    assessed_value_cents: int
    linear_frontage_ft: float
    building_sqft: float
    exempt: bool
    weighted_base: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FiscalYear(TypedDict):
    id: str
    bid_id: str
    year_label: str
    start_date: str
    end_date: str
    assessment_due_date: str
    budget_status: str
    total_certified_levy_cents: int
    collected_to_date_cents: int
    collection_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Budget(TypedDict):
    id: str
    fiscal_year_id: str
    total_expenditure_cents: int
    other_revenue_cents: int
    allocated_total_cents: int
    required_levy_cents: int
    estimate_rate: float
    certified_rate: float
    proposed_at: Optional[str]
    adopted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkPlanLine(TypedDict):
    id: str
    budget_id: str
    category: str
    allocated_amount_cents: int
    spent_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    fiscal_year_id: str
    parcel_id: str
    weighted_base: float
    estimated_amount_cents: int
    certified_amount_cents: Optional[int]
    certified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CollectionAccount(TypedDict):
    id: str
    assessment_id: str
    billed_amount_cents: int
    penalty_accrued_cents: int
    interest_accrued_cents: int
    principal_paid_cents: int
    total_paid_cents: int
    credit_balance_cents: int
    balance_due_cents: int
    due_date: str
    delinquent_since: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger event: id + created_at ONLY
class Payment(TypedDict):
    id: str
    collection_account_id: str
    amount_cents: int
    method: str
    applied_to_interest_cents: int
    applied_to_penalty_cents: int
    applied_to_principal_cents: int
    posted_at: str
    created_at: str


class Dispute(TypedDict):
    id: str
    assessment_id: str
    claimed_value_cents: int
    requested_amount_cents: int
    resolved_amount_cents: Optional[int]
    reason: Optional[str]
    filed_at: str
    resolved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalPetition(TypedDict):
    id: str
    bid_id: str
    required_threshold_pct: float
    circulation_deadline: str
    renewal_term_months: int
    weighted_support_pct: Optional[float]
    verified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only: id + created_at ONLY
class PetitionSignature(TypedDict):
    id: str
    petition_id: str
    parcel_id: str
    support: bool
    signed_at: str
    created_at: str


class Ambassador(TypedDict):
    id: str
    bid_id: str
    name: str
    service_role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AmbassadorShift(TypedDict):
    id: str
    ambassador_id: str
    zone: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict):
    id: str
    bid_id: str
    assigned_ambassador_id: Optional[str]
    category: str
    source: str
    external_ref: Optional[str]
    description: Optional[str]
    logged_cost_cents: int
    work_plan_category: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
