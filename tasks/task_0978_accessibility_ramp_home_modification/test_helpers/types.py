"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    ASSESSOR = "Assessor"
    PROJECT_MANAGER = "ProjectManager"
    FUNDING_COORDINATOR = "FundingCoordinator"
    CREW_LEAD = "CrewLead"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    INSPECTOR = "Inspector"
    BILLING_COORDINATOR = "BillingCoordinator"
    CLIENT = "Client"
    SYSTEM_ADMIN = "SystemAdmin"


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSESSMENT_SCHEDULED = "ASSESSMENT_SCHEDULED"
    ASSESSED = "ASSESSED"
    QUOTE_DRAFTED = "QUOTE_DRAFTED"
    QUOTE_SUBMITTED = "QUOTE_SUBMITTED"
    FUNDING_PENDING = "FUNDING_PENDING"
    FUNDING_APPROVED = "FUNDING_APPROVED"
    INSTALLATION_SCHEDULED = "INSTALLATION_SCHEDULED"
    INSTALLED = "INSTALLED"
    INSPECTED = "INSPECTED"
    WARRANTY_ACTIVE = "WARRANTY_ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FundingPosture(str, Enum):
    UNFUNDED = "UNFUNDED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"
    FULLY_FUNDED = "FULLY_FUNDED"
    OVERFUNDED = "OVERFUNDED"


class AssessmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class LineType(str, Enum):
    LABOR = "LABOR"
    MATERIAL = "MATERIAL"
    PERMIT = "PERMIT"
    EQUIPMENT_RENTAL = "EQUIPMENT_RENTAL"
    EQUIPMENT_PURCHASE = "EQUIPMENT_PURCHASE"
    DEMOLITION = "DEMOLITION"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"


class FundingSourceStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXHAUSTED = "EXHAUSTED"
    WITHDRAWN = "WITHDRAWN"


class AllocationStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    REVERSED = "REVERSED"


class JobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MATERIALS_ORDERED = "MATERIALS_ORDERED"
    IN_PROGRESS = "IN_PROGRESS"
    PUNCH_LIST = "PUNCH_LIST"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RentalStatus(str, Enum):
    RESERVED = "RESERVED"
    DELIVERED = "DELIVERED"
    INSTALLED = "INSTALLED"
    IN_USE = "IN_USE"
    PICKUP_SCHEDULED = "PICKUP_SCHEDULED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class InspectionOutcome(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    VOID = "VOID"
    DISPUTED = "DISPUTED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class ConsultStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ScheduleStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"


# All entities carry the four system-managed properties of PRD §2.4
# (id, created_at, updated_at, version).

class Case(TypedDict, total=False):
    id: str
    client_name: str
    client_address: str
    client_phone: str
    referral_source: str
    status: str
    funding_posture: str
    total_quoted_cents: int
    total_funded_cents: int
    total_billed_cents: int
    total_paid_cents: int
    balance_due_cents: int
    ada_scope_score: Optional[int]
    caps_scope_score: Optional[int]
    safety_risk_index: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict, total=False):
    id: str
    case_id: str
    assessor_id: str
    assessor_role: str
    assessment_type: str
    scheduled_date: str
    completed_date: Optional[str]
    mobility_score: int
    hazard_count: int
    ada_compliance_pct: Optional[float]
    caps_recommendation_score: Optional[int]
    recommended_modifications: List[str]
    rental_eligible: Optional[bool]
    purchase_required: Optional[bool]
    status: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    case_id: str
    quote_number: str
    revision: int
    status: str
    valid_until: str
    labor_cost_cents: int
    material_cost_cents: int
    permit_fee_cents: int
    equipment_cost_cents: int
    contingency_pct: float
    contingency_cents: int
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    funding_gap_cents: Optional[int]
    superseded_by_id: Optional[str]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuoteLineItem(TypedDict, total=False):
    id: str
    quote_id: str
    line_type: str
    description: str
    quantity: float
    unit: str
    unit_price_cents: int
    extended_price_cents: int
    is_taxable: bool
    tax_rate_pct: float
    tax_cents: int
    funding_eligible: bool
    sort_order: int
    created_at: str
    updated_at: str
    version: int


class FundingSource(TypedDict, total=False):
    id: str
    case_id: str
    source_type: str
    program_name: str
    application_number: Optional[str]
    status: str
    requested_cents: int
    approved_cents: Optional[int]
    remaining_cents: Optional[int]
    decision_date: Optional[str]
    expiration_date: Optional[str]
    priority_rank: int
    restrictions: List[str]
    created_at: str
    updated_at: str
    version: int


class FundingAllocation(TypedDict, total=False):
    id: str
    funding_source_id: str
    quote_id: str
    quote_line_item_id: Optional[str]
    amount_cents: int
    allocation_type: str
    status: str
    committed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstallationJob(TypedDict, total=False):
    id: str
    case_id: str
    quote_id: str
    job_number: str
    status: str
    scheduled_start: str
    scheduled_end: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    crew_lead_id: str
    permit_number: Optional[str]
    permit_status: str
    inspection_required: bool
    inspection_status: str
    warranty_start_date: Optional[str]
    warranty_months: int
    progress_pct: int
    created_at: str
    updated_at: str
    version: int


class RentalRamp(TypedDict, total=False):
    id: str
    case_id: str
    inventory_unit_id: str
    status: str
    rental_start: str
    rental_end: str
    actual_pickup: Optional[str]
    monthly_rate_cents: int
    deposit_cents: int
    deposit_status: str
    billing_cycle_day: int
    last_billed_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryUnit(TypedDict, total=False):
    id: str
    unit_tag: str
    ramp_type: str
    length_feet: int
    width_inches: int
    weight_capacity_lbs: int
    status: str
    condition_grade: str
    monthly_rate_cents: int
    purchase_price_cents: int
    current_case_id: Optional[str]
    total_rental_days: int
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    case_id: str
    installation_job_id: Optional[str]
    inspection_type: str
    inspector_id: str
    scheduled_date: str
    completed_date: Optional[str]
    outcome: str
    deficiencies: List[str]
    correction_deadline: Optional[str]
    reinspection_required: bool
    ada_compliant: bool
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    case_id: str
    invoice_number: str
    invoice_type: str
    status: str
    issue_date: Optional[str]
    due_date: str
    paid_date: Optional[str]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    amount_paid_cents: int
    balance_cents: int
    funding_source_id: Optional[str]
    quote_id: Optional[str]
    rental_ramp_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvoiceLineItem(TypedDict, total=False):
    id: str
    invoice_id: str
    description: str
    quantity: float
    unit_price_cents: int
    extended_price_cents: int
    tax_cents: int
    line_total_cents: int
    period_start: Optional[str]
    period_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    case_id: str
    installation_job_id: str
    claim_number: str
    status: str
    issue_description: str
    severity: str
    reported_date: str
    resolved_date: Optional[str]
    resolution_type: Optional[str]
    cost_cents: int
    covered_by_warranty: bool
    created_at: str
    updated_at: str
    version: int


class OTConsultation(TypedDict, total=False):
    id: str
    case_id: str
    ot_provider_id: str
    consultation_type: str
    scheduled_date: str
    completed_date: Optional[str]
    status: str
    goals: List[str]
    recommendations: List[str]
    clearance_given: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class ReassessmentSchedule(TypedDict, total=False):
    id: str
    case_id: str
    trigger_event: str
    due_date: str
    status: str
    linked_assessment_id: Optional[str]
    priority: str
    auto_generated: bool
    created_at: str
    updated_at: str
    version: int
