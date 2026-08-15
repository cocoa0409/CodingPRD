"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3).

All resources carry the PRD §2.5 common fields (id, created_at, updated_at,
version). Nullable system fields are marked Optional.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CLIENT = "Client"
    ENGAGEMENT_MANAGER = "EngagementManager"
    STAFF_APPRAISER = "StaffAppraiser"
    REVIEW_APPRAISER = "ReviewAppraiser"
    MAI_SIGNER = "MAISigner"
    RECORDS_MANAGER = "RecordsManager"
    LEGAL_COUNSEL = "LegalCounsel"


class ClientType(str, Enum):
    LENDER = "LENDER"
    LAW_FIRM = "LAW_FIRM"
    INVESTOR = "INVESTOR"
    GOVERNMENT_AGENCY = "GOVERNMENT_AGENCY"


class VolumeDiscountTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class AppraiserDesignation(str, Enum):
    TRAINEE = "TRAINEE"
    CERTIFIED_GENERAL = "CERTIFIED_GENERAL"
    MAI = "MAI"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class PropertyType(str, Enum):
    OFFICE = "OFFICE"
    RETAIL = "RETAIL"
    INDUSTRIAL = "INDUSTRIAL"
    MULTIFAMILY = "MULTIFAMILY"
    SPECIAL_PURPOSE = "SPECIAL_PURPOSE"


class IntendedUse(str, Enum):
    FINANCING = "FINANCING"
    LITIGATION = "LITIGATION"
    FINANCIAL_REPORTING = "FINANCIAL_REPORTING"
    TAX_APPEAL = "TAX_APPEAL"


class FeeSchedule(str, Enum):
    TIERED = "TIERED"
    PER_SF = "PER_SF"


class ComplexityTier(str, Enum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class EngagementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE"
    IN_PROGRESS = "IN_PROGRESS"
    LITIGATION_HOLD = "LITIGATION_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class SubmissionType(str, Enum):
    RENT_ROLL = "RENT_ROLL"
    OPERATING_STATEMENT = "OPERATING_STATEMENT"
    TAX_BILL = "TAX_BILL"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    LOCKED = "LOCKED"


class ApproachType(str, Enum):
    INCOME = "INCOME"
    SALES_COMPARISON = "SALES_COMPARISON"
    COST = "COST"


class ApproachStatus(str, Enum):
    SELECTED = "SELECTED"
    COMPLETE = "COMPLETE"
    EXCLUDED = "EXCLUDED"


class ReportStatus(str, Enum):
    DRAFTING = "DRAFTING"
    INTERNAL_REVIEW = "INTERNAL_REVIEW"
    REVIEWED = "REVIEWED"
    CLIENT_REVIEW = "CLIENT_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    FINAL = "FINAL"
    SIGNED = "SIGNED"
    DELIVERED = "DELIVERED"
    SUPERSEDED = "SUPERSEDED"
    SUSPENDED = "SUSPENDED"


class RevisionCategory(str, Enum):
    FACTUAL_CORRECTION = "FACTUAL_CORRECTION"
    CLARIFICATION = "CLARIFICATION"
    METHODOLOGY_QUESTION = "METHODOLOGY_QUESTION"
    VALUE_PRESSURE = "VALUE_PRESSURE"


class RevisionStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    ESCALATED = "ESCALATED"
    WITHDRAWN = "WITHDRAWN"


class RetentionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LITIGATION_HOLD = "LITIGATION_HOLD"
    RELEASED_PENDING_DESTRUCTION = "RELEASED_PENDING_DESTRUCTION"
    DESTROYED = "DESTROYED"


class Client(TypedDict, total=False):
    id: str
    name: str
    client_type: str
    total_billed_cents: int
    volume_discount_tier: str
    created_at: str
    updated_at: str
    version: int


class Appraiser(TypedDict, total=False):
    id: str
    full_name: str
    designation: str
    license_status: str
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict, total=False):
    id: str
    client_id: str
    author_appraiser_id: str
    reviewer_appraiser_id: str
    property_address: str
    property_type: str
    building_sf: int
    intended_use: str
    intended_users: List[str]
    requested_turnaround_days: int
    planned_approach_count: int
    fee_schedule: str
    is_contingent_fee: bool
    complexity_tier: str
    minimum_turnaround_days: int
    quoted_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    fee_written_off: bool
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    due_date: Optional[str]
    litigation_matter_reference: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DataSubmission(TypedDict, total=False):
    id: str
    engagement_id: str
    submission_type: str
    period_start: str
    period_end: str
    scheduled_gross_rent_cents: int
    vacancy_loss_cents: int
    expense_reimbursements_cents: int
    operating_expenses_cents: int
    noi_trailing_cents: Optional[int]
    noi_stabilized_cents: Optional[int]
    review_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ValuationApproach(TypedDict, total=False):
    id: str
    engagement_id: str
    approach_type: str
    cap_rate_bps: Optional[int]
    dcf_holding_period_years: Optional[int]
    dcf_discount_rate_bps: Optional[int]
    dcf_exit_cap_bps: Optional[int]
    revenue_growth_bps_annual: Optional[int]
    land_value_cents: Optional[int]
    replacement_cost_cents: Optional[int]
    depreciation_pct: Optional[float]
    indicated_value_cents: Optional[int]
    weight_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ComparableSale(TypedDict, total=False):
    id: str
    engagement_id: str
    address: str
    sale_date: str
    sale_price_cents: int
    noi_at_sale_cents: int
    size_sf: int
    adjustment_pct: float
    selected_for_support: bool
    implied_cap_rate_bps: int
    adjusted_cap_rate_bps: int
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict, total=False):
    id: str
    engagement_id: str
    report_version_no: int
    supersedes_report_id: Optional[str]
    value_conclusion_cents: Optional[int]
    review_cycle_count: int
    signer_appraiser_id: Optional[str]
    pre_hold_status: Optional[str]
    issued_to_client_at: Optional[str]
    signed_at: Optional[str]
    delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RevisionRequest(TypedDict, total=False):
    id: str
    report_id: str
    category: str
    requested_change: str
    proposed_value_cents: Optional[int]
    value_adjustment_cents: Optional[int]
    resolution_note: Optional[str]
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RetentionRecord(TypedDict, total=False):
    id: str
    engagement_id: str
    completed_date: str
    base_retain_until_date: str
    litigation_hold_placed_at: Optional[str]
    litigation_released_at: Optional[str]
    litigation_matter_reference: Optional[str]
    retain_until_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
