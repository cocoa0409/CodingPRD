"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this PRD carry the four server-managed common properties
(id, created_at, updated_at, version) per PRD section 2.4.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LANDLORD_PM = "LandlordPM"
    LANDLORD_APPROVER = "LandlordApprover"
    TENANT_REP = "TenantRep"
    CONTRACTOR_REP = "ContractorRep"
    BUILDING_ENGINEER = "BuildingEngineer"


class LeaseSpaceStatus(str, Enum):
    VACANT = "VACANT"
    LEASED = "LEASED"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class AbatementBasis(str, Enum):
    CALENDAR = "CALENDAR"
    BUSINESS = "BUSINESS"


class DelayResponsibility(str, Enum):
    NONE = "NONE"
    LANDLORD = "LANDLORD"
    TENANT = "TENANT"


class TIProjectStatus(str, Enum):
    INITIATED = "INITIATED"
    WORK_LETTER_NEGOTIATION = "WORK_LETTER_NEGOTIATION"
    PLAN_REVIEW = "PLAN_REVIEW"
    PRE_CONSTRUCTION = "PRE_CONSTRUCTION"
    CONSTRUCTION = "CONSTRUCTION"
    PUNCH = "PUNCH"
    CLOSEOUT = "CLOSEOUT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TIProjectPosture(str, Enum):
    OPEN = "OPEN"
    ON_HOLD = "ON_HOLD"
    ALLOWANCE_EXHAUSTED = "ALLOWANCE_EXHAUSTED"


class WorkLetterStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    EXECUTED = "EXECUTED"
    WITHDRAWN = "WITHDRAWN"


class WorkDelineation(str, Enum):
    LANDLORD = "LANDLORD"
    TENANT = "TENANT"
    SPLIT = "SPLIT"


class PlanSubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    REJECTED_FINAL = "REJECTED_FINAL"
    SUPERSEDED = "SUPERSEDED"


class CommentSeverity(str, Enum):
    INFO = "INFO"
    REQUIRED = "REQUIRED"
    BLOCKING = "BLOCKING"


class CommentStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ContractorStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class EngagementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"


class MilestoneWorkType(str, Enum):
    STANDARD = "STANDARD"
    NOISY = "NOISY"
    HOT_WORK = "HOT_WORK"
    FREIGHT = "FREIGHT"


class MilestoneStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class DrawStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ON_HOLD = "ON_HOLD"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class WaiverType(str, Enum):
    CONDITIONAL_PROGRESS = "CONDITIONAL_PROGRESS"
    UNCONDITIONAL_PROGRESS = "UNCONDITIONAL_PROGRESS"
    CONDITIONAL_FINAL = "CONDITIONAL_FINAL"
    UNCONDITIONAL_FINAL = "UNCONDITIONAL_FINAL"


class WaiverStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class PunchSeverity(str, Enum):
    COSMETIC = "COSMETIC"
    STANDARD = "STANDARD"
    LIFE_SAFETY = "LIFE_SAFETY"


class PunchItemStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class Property(TypedDict, total=False):
    id: str
    name: str
    address: str
    max_concurrent_construction_projects: int
    created_at: str
    updated_at: str
    version: int


class LeaseSpace(TypedDict, total=False):
    id: str
    property_id: str
    suite_number: str
    floor: int
    rentable_sqft: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    tax_id: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    space_id: str
    tenant_id: str
    base_rent_annual_cents: int
    scheduled_rent_commencement_date: str
    actual_rent_commencement_date: Optional[str]
    abatement_basis: str
    delay_responsibility: str
    rent_abatement_credit_cents: int
    lease_term_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TIProject(TypedDict, total=False):
    id: str
    lease_id: str
    project_name: str
    base_contract_cents: int
    allowance_total_cents: int
    status: str
    posture: str
    construction_start_date: Optional[str]
    construction_end_date: Optional[str]
    substantial_completion_date: Optional[str]
    occupancy_certificate_ref: Optional[str]
    total_cost_cents: int
    allowance_consumed_cents: int
    provisional_allowance_consumed_cents: int
    allowance_remaining_cents: int
    overage_cents: int
    retainage_held_cents: int
    retainage_released_cents: int
    created_at: str
    updated_at: str
    version: int


class WorkLetter(TypedDict, total=False):
    id: str
    project_id: str
    version_no: int
    scope_description: str
    allowance_offer_cents: int
    work_delineation: str
    proposed_by: str
    round_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanSubmission(TypedDict, total=False):
    id: str
    project_id: str
    revision_no: int
    drawing_set_ref: str
    review_round: int
    submitted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanReviewComment(TypedDict, total=False):
    id: str
    submission_id: str
    comment_text: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict, total=False):
    id: str
    company_name: str
    license_number: str
    insurance_expiry_date: str
    qualification_status: str
    created_at: str
    updated_at: str
    version: int


class ContractorEngagement(TypedDict, total=False):
    id: str
    project_id: str
    contractor_id: str
    building_rules_acknowledged: bool
    scope_note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScheduleMilestone(TypedDict, total=False):
    id: str
    engagement_id: str
    milestone_name: str
    window_start: str
    window_end: str
    work_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrderLine(TypedDict):
    description: str
    amount_cents: int


class ChangeOrder(TypedDict, total=False):
    id: str
    project_id: str
    co_number: int
    description: str
    lines: List[ChangeOrderLine]
    submitted_by: Optional[str]
    total_cost_cents: int
    markup_cents: int
    total_with_markup_cents: int
    tenant_overage_share_cents: int
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisbursementRequest(TypedDict, total=False):
    id: str
    project_id: str
    draw_number: int
    period_end_date: str
    requested_amount_cents: int
    is_final_draw: bool
    approved_amount_cents: int
    retainage_held_cents: int
    net_payment_cents: int
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LienWaiver(TypedDict, total=False):
    id: str
    disbursement_id: str
    contractor_id: str
    waiver_type: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchItem(TypedDict, total=False):
    id: str
    project_id: str
    assigned_engagement_id: str
    description: str
    location: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OverageInvoice(TypedDict, total=False):
    id: str
    project_id: str
    invoice_number: int
    line_total_cents: int
    due_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
