"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ADVISOR = "Advisor"
    BENEFITS_COUNSELOR = "BenefitsCounselor"
    BILLING_SPECIALIST = "BillingSpecialist"
    COMMUNITY_MANAGER = "CommunityManager"
    FAMILY = "Family"


class AdvisorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    INACTIVE = "INACTIVE"


class CommunityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CareLevel(str, Enum):
    INDEPENDENT_LIVING = "INDEPENDENT_LIVING"
    ASSISTED_LIVING = "ASSISTED_LIVING"
    MEMORY_CARE = "MEMORY_CARE"
    SKILLED_NURSING = "SKILLED_NURSING"


class InventoryStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class InquiryStatus(str, Enum):
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    ASSESSED = "ASSESSED"
    MATCHING = "MATCHING"
    TOURING = "TOURING"
    PLACED = "PLACED"
    ON_HOLD = "ON_HOLD"
    CLOSED_LOST = "CLOSED_LOST"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"


class MatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SHORTLISTED = "SHORTLISTED"
    TOUR_SCHEDULED = "TOUR_SCHEDULED"
    TOURED = "TOURED"
    SELECTED = "SELECTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class TourStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class TourMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    VIRTUAL = "VIRTUAL"


class ResidencyStatus(str, Enum):
    PENDING_MOVE_IN = "PENDING_MOVE_IN"
    MOVED_IN = "MOVED_IN"
    RESIDENT_CONFIRMED = "RESIDENT_CONFIRMED"
    MOVED_OUT = "MOVED_OUT"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    NOT_INVOICED = "NOT_INVOICED"
    INVOICE_DRAFTED = "INVOICE_DRAFTED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    ACCEPTED = "ACCEPTED"
    PAID = "PAID"
    VOIDED = "VOIDED"
    CLAWED_BACK = "CLAWED_BACK"


class LedgerEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    ADJUSTMENT = "ADJUSTMENT"
    PAYMENT = "PAYMENT"
    CLAWBACK = "CLAWBACK"
    WRITE_OFF = "WRITE_OFF"


class GuidanceStatus(str, Enum):
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class BenefitType(str, Enum):
    VA_AID_ATTENDANCE = "VA_AID_ATTENDANCE"
    VA_SURVIVOR_PENSION = "VA_SURVIVOR_PENSION"
    LTC_INSURANCE = "LTC_INSURANCE"
    BRIDGE_LOAN = "BRIDGE_LOAN"


class CaseloadStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    REASSIGNED = "REASSIGNED"


# --- Entity TypedDicts (common_fields: true carry updated_at + version) ---

class Family(TypedDict):
    id: str
    primary_contact_name: str
    email: str
    phone: str
    relationship_to_senior: str
    state_code: str
    senior_first_name: str
    senior_age: int
    created_at: str
    updated_at: str
    version: int


class Advisor(TypedDict):
    id: str
    full_name: str
    email: str
    region_code: str
    is_va_certified: bool
    caseload_capacity: int
    status: str
    active_caseload_count: int
    headcount_load_index: float
    weighted_load_index: float
    created_at: str
    updated_at: str
    version: int


class Community(TypedDict):
    id: str
    name: str
    region_code: str
    contract_tier: str
    referral_fee_pct: float
    tour_slot_capacity: int
    quality_rating: float
    status: str
    fee_balance_cents: int
    satisfaction_survey_count: int
    avg_satisfaction_score: float
    created_at: str
    updated_at: str
    version: int


class CommunityInventory(TypedDict):
    id: str
    community_id: str
    care_level: str
    total_units: int
    reserved_units: int
    occupied_units: int
    available_units: int
    monthly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inquiry(TypedDict):
    id: str
    family_id: str
    assigned_advisor_id: Optional[str]
    origin: str
    region_code: str
    requested_care_level: str
    target_move_in_date: str
    declared_budget_monthly_cents: int
    priority_score: float
    status: str
    match_count: int
    hold_reason: Optional[str]
    close_reason_code: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NeedsAssessment(TypedDict):
    id: str
    inquiry_id: str
    author_advisor_id: str
    adl_score: int
    cognitive_score: int
    mobility_score: int
    budget_monthly_cents: int
    gross_monthly_income_cents: int
    va_eligible: bool
    marital_status: str
    recommended_care_level: str
    benefit_offset_cents: int
    affordability_ceiling_cents: int
    status: str
    revision_note: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict):
    id: str
    inquiry_id: str
    community_id: str
    care_level: str
    quoted_monthly_rate_cents: int
    fit_score: float
    status: str
    decline_reason_code: Optional[str]
    tour_round: int
    created_at: str
    updated_at: str
    version: int


class Tour(TypedDict):
    id: str
    match_id: str
    advisor_id: str
    community_id: str
    scheduled_start: str
    scheduled_end: str
    mode: str
    status: str
    outcome_rating: Optional[int]
    cancel_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    match_id: str
    inquiry_id: str
    community_id: str
    inventory_id: str
    care_level: str
    agreed_move_in_date: str
    actual_move_in_date: Optional[str]
    actual_care_level: Optional[str]
    contracted_monthly_rate_cents: int
    estimated_fee_cents: int
    final_fee_cents: Optional[int]
    clawback_amount_cents: int
    residency_status: str
    billing_status: str
    move_out_date: Optional[str]
    days_resided: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ReferralInvoice(TypedDict):
    id: str
    placement_id: str
    community_id: str
    final_fee_cents: int
    paid_amount_cents: int
    net_recognized_fee_cents: int
    status: str
    dispute_reason: Optional[str]
    claimed_rate_cents: Optional[int]
    adjustment_count: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenefitGuidance(TypedDict):
    id: str
    inquiry_id: str
    assessment_id: str
    counselor_advisor_id: str
    benefit_type: str
    unreimbursed_medical_cents: int
    countable_income_cents: int
    estimated_monthly_benefit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CaseloadAssignment(TypedDict):
    id: str
    advisor_id: str
    inquiry_id: str
    assigned_at: str
    released_at: Optional[str]
    release_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only entities (common_fields: false — id + created_at only) ---

class FeeLedgerEntry(TypedDict):
    id: str
    invoice_id: str
    placement_id: str
    community_id: str
    entry_type: str
    amount_cents: int
    balance_after_cents: int
    reason: str
    created_at: str


class SatisfactionSurvey(TypedDict):
    id: str
    placement_id: str
    respondent_family_id: str
    community_id: str
    days_after_move_in: int
    nps_score: int
    care_rating: int
    value_rating: int
    composite_score: float
    created_at: str
