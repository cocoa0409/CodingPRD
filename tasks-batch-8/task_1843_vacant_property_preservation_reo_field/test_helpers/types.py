"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the common system fields id, created_at,
updated_at, and version (PRD: "Resource Identity, Timestamps, and Versioning").
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SERVICER = "Servicer"
    VENDOR_ADMIN = "VendorAdmin"
    DISPATCHER = "Dispatcher"
    FIELD_CREW = "FieldCrew"
    QUALITY_REVIEWER = "QualityReviewer"


class PropertyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONVEYED = "CONVEYED"


class OccupancyStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    VACANT = "VACANT"
    OCCUPIED_PENDING_VERIFICATION = "OCCUPIED_PENDING_VERIFICATION"
    OCCUPIED = "OCCUPIED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    AT_RISK = "AT_RISK"
    NON_COMPLIANT = "NON_COMPLIANT"


class WorkOrderStatus(str, Enum):
    ISSUED = "ISSUED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"


class DispositionStatus(str, Enum):
    IN_HOLD = "IN_HOLD"
    RELEASE_ELIGIBLE = "RELEASE_ELIGIBLE"
    DISPOSAL_AUTHORIZED = "DISPOSAL_AUTHORIZED"
    DISPOSED = "DISPOSED"
    DONATED = "DONATED"
    RETURNED = "RETURNED"


class RecurringPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"


class CodeViolationStatus(str, Enum):
    OPEN = "OPEN"
    CURE_IN_PROGRESS = "CURE_IN_PROGRESS"
    CURE_SUBMITTED = "CURE_SUBMITTED"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    ESCALATED = "ESCALATED"


class RegistrationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"


class DamageReportStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    BID_REQUESTED = "BID_REQUESTED"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"


class BidStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class Servicer(TypedDict, total=False):
    id: str
    name: str
    code: str
    active: bool
    prior_month_gross_cents: int
    volume_rebate_cents: int
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    name: str
    crew_code: str
    region_state_codes: List[str]
    daily_capacity_jobs: int
    created_at: str
    updated_at: str
    version: int


class InvestorAllowable(TypedDict, total=False):
    id: str
    investor_type: str
    item_code: str
    max_per_occurrence_cents: int
    max_occurrences_per_calendar_year: int
    aggregate_cap_cents_per_property_year: int
    requires_bid_over_cents: int
    effective_from: str
    is_current: bool
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    servicer_id: str
    address_line1: str
    municipality_code: str
    state_code: str
    zip: str
    investor_type: str
    lot_size_sqft: int
    heating_system: str
    has_pool: bool
    fixture_count: int
    status: str
    occupancy_status: str
    condition_score: int
    compliance_posture: str
    ytd_investor_approved_cents: int
    ytd_calendar_year: int
    financial_review_required: bool
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    property_id: str
    servicer_id: str
    order_type: str
    item_code: str
    source: str
    status: str
    due_date: str
    scheduled_date: Optional[str]
    assigned_crew_id: Optional[str]
    bid_id: Optional[str]
    damage_report_id: Optional[str]
    code_violation_id: Optional[str]
    recurring_plan_id: Optional[str]
    investor_allowable_id: str
    investor_allowable_version: int
    allowable_cap_cents: int
    requires_bid_over_cents: int
    estimated_cost_cents: int
    submitted_cost_cents: Optional[int]
    approved_cost_cents: Optional[int]
    rework_count: int
    evidence_complete: bool
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    property_id: str
    work_order_id: Optional[str]
    cycle_index: int
    due_date: str
    status: str
    occupancy_determination: Optional[str]
    interior_access: Optional[bool]
    personal_property_present: Optional[bool]
    personal_property_value_estimate_cents: Optional[int]
    condition_notes: Optional[str]
    recorded_at: Optional[str]
    verified_occupancy: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PersonalPropertyDisposition(TypedDict, total=False):
    id: str
    property_id: str
    work_order_id: Optional[str]
    inspection_id: Optional[str]
    description: str
    valuation_cents: int
    documented_date: str
    hold_until_date: str
    status: str
    authorized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecurringServicePlan(TypedDict, total=False):
    id: str
    property_id: str
    service_type: str
    season_start_md: str
    season_end_md: str
    interval_days: int
    max_per_season: int
    generated_this_season: int
    last_generated_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CodeViolation(TypedDict, total=False):
    id: str
    property_id: str
    citation_number: str
    violation_class: str
    daily_fine_cents: int
    fine_cap_cents: int
    cure_deadline: str
    accrued_fine_cents: int
    cure_work_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MunicipalRegistration(TypedDict, total=False):
    id: str
    property_id: str
    municipality_code: str
    registration_number: str
    fee_cents: int
    valid_from: str
    valid_to: str
    renewal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageReport(TypedDict, total=False):
    id: str
    property_id: str
    work_order_id: Optional[str]
    reported_by_crew_id: str
    damage_type: str
    severity: str
    is_interior: bool
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    damage_report_id: str
    property_id: str
    submitted_by_crew_id: str
    amount_cents: int
    round_number: int
    counter_amount_cents: Optional[int]
    status: str
    approved_work_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PhotoEvidence(TypedDict, total=False):
    id: str
    work_order_id: Optional[str]
    inspection_id: Optional[str]
    bid_id: Optional[str]
    damage_report_id: Optional[str]
    category: str
    taken_at: str
    content_hash: str
    captured_by_crew_id: str
    flagged: bool
    flagged_by_user_id: Optional[str]
    flag_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    work_order_id: str
    property_id: str
    investor_type: str
    status: str
    claimed_total_cents: int
    provisional_allowed_cents: Optional[int]
    approved_amount_cents: Optional[int]
    prompt_pay_discount_cents: int
    payable_amount_cents: Optional[int]
    appeal_round: int
    submitted_at: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExpenseLine(TypedDict, total=False):
    id: str
    invoice_id: str
    item_code: str
    description: Optional[str]
    quantity: int
    unit_price_cents: int
    claimed_cents: int
    allowed_cents: Optional[int]
    line_discount_cents: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
