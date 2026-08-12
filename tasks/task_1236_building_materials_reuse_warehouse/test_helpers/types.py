"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — nine roles, spelled exactly)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DONOR = "Donor"
    INTAKE_STAFF = "IntakeStaff"
    HAZMAT_TECHNICIAN = "HazmatTechnician"
    CREW_COORDINATOR = "CrewCoordinator"
    CREW_LEAD = "CrewLead"
    STORE_MANAGER = "StoreManager"
    CASHIER = "Cashier"
    CONTRACTOR = "Contractor"
    WAREHOUSE_ADMIN = "WarehouseAdmin"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class DonorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RecognitionTier(str, Enum):
    NONE = "NONE"
    SUPPORTER = "SUPPORTER"
    BUILDER = "BUILDER"
    CORNERSTONE = "CORNERSTONE"


class AcceptanceStatus(str, Enum):
    ACCEPTING = "ACCEPTING"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class PricingModel(str, Enum):
    PER_UNIT = "PER_UNIT"
    PER_SQFT = "PER_SQFT"
    PER_LINEAR_FT = "PER_LINEAR_FT"
    FLAT = "FLAT"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"
    RECEIPTED = "RECEIPTED"
    CANCELLED = "CANCELLED"


class SourceType(str, Enum):
    DROPOFF = "DROPOFF"
    PICKUP = "PICKUP"
    DECONSTRUCTION = "DECONSTRUCTION"


class JobStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCREENING_PENDING = "SCREENING_PENDING"
    CLEARED = "CLEARED"
    HAZMAT_HOLD = "HAZMAT_HOLD"
    REMEDIATION_IN_PROGRESS = "REMEDIATION_IN_PROGRESS"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ScreeningResult(str, Enum):
    NOT_TESTED = "NOT_TESTED"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class ScreeningOutcome(str, Enum):
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    PENDING = "PENDING"


class BatchStatus(str, Enum):
    MANIFESTED = "MANIFESTED"
    WEIGHED = "WEIGHED"
    QUARANTINED = "QUARANTINED"
    SORTED = "SORTED"
    DISPOSED_HAZARD = "DISPOSED_HAZARD"


class PricingStatus(str, Enum):
    UNPRICED = "UNPRICED"
    PRICED = "PRICED"


class SalesStatus(str, Enum):
    BACKROOM = "BACKROOM"
    ON_FLOOR = "ON_FLOOR"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    DONATED_OUT = "DONATED_OUT"
    RECYCLED = "RECYCLED"
    DISPOSED = "DISPOSED"


class Disposition(str, Enum):
    DONATE = "DONATE"
    RECYCLE = "RECYCLE"
    DISPOSE = "DISPOSE"


class DispositionRecommended(str, Enum):
    NONE = "NONE"
    DONATE = "DONATE"
    RECYCLE = "RECYCLE"
    DISPOSE = "DISPOSE"


class ZoneStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AccountStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class DiscountTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class SaleChannel(str, Enum):
    WALK_IN = "WALK_IN"
    CONTRACTOR_ACCOUNT = "CONTRACTOR_ACCOUNT"


class SaleStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"
    CANCELLED = "CANCELLED"


class ReceiptStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID_REQUESTED = "VOID_REQUESTED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class ValuationMethod(str, Enum):
    ESTIMATED_GUIDANCE = "ESTIMATED_GUIDANCE"
    QUALIFIED_APPRAISAL = "QUALIFIED_APPRAISAL"


class CrewType(str, Enum):
    VOLUNTEER = "VOLUNTEER"
    PAID = "PAID"


class CrewMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RoleOnJob(str, Enum):
    LEAD = "LEAD"
    WORKER = "WORKER"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    RETIRED = "RETIRED"


class SubjectType(str, Enum):
    DONATION_OFFER = "DONATION_OFFER"
    DECONSTRUCTION_JOB = "DECONSTRUCTION_JOB"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class MeasureUnit(str, Enum):
    UNIT = "UNIT"
    SQFT = "SQFT"
    LINEAR_FT = "LINEAR_FT"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5 common properties + §3 per-entity fields)
# ---------------------------------------------------------------------------
class Donor(TypedDict, total=False):
    id: str
    full_name: str
    donor_type: str
    email: str
    phone: str
    address_text: str
    status: str
    trailing_receipt_value_cents: int
    recognition_tier: str
    created_at: str
    updated_at: str
    version: int


class Category(TypedDict, total=False):
    id: str
    code: str
    display_name: str
    pricing_model: str
    base_rate_cents: int
    acceptance_status: str
    hazmat_risk_flag: bool
    requires_appraisal_review: bool
    markdown_after_days: int
    markdown_step_pct: float
    markdown_interval_days: int
    max_markdown_steps: int
    floor_price_pct: float
    divertible: bool
    target_turn_days: int
    slow_item_disposition: str
    created_at: str
    updated_at: str
    version: int


class DonationOffer(TypedDict, total=False):
    id: str
    donor_id: str
    source_type: str
    category_id: str
    description_text: str
    estimated_quantity: float
    quantity_unit: str
    condition_grade: str
    pre_1978_flag: bool
    deconstruction_job_id: Optional[str]
    status: str
    review_notes: str
    decision_reason: str
    received_by_user_id: str
    estimated_value_cents: int
    final_value_cents: int
    created_at: str
    updated_at: str
    version: int


class DeconstructionJob(TypedDict, total=False):
    id: str
    title: str
    site_address_text: str
    donor_id: Optional[str]
    quoted_fee_cents: int
    included_labor_cents: int
    status: str
    lead_crew_member_id: Optional[str]
    vehicle_id: Optional[str]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    clearing_screening_id: Optional[str]
    estimated_diverted_weight_lbs: float
    certified_diverted_weight_lbs: float
    actual_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class HazmatScreening(TypedDict, total=False):
    # Lean record (PRD §2.5): only id + created_at; no updated_at / version.
    id: str
    job_id: str
    performed_by_crew_id: str
    screening_round: int
    lead_result: str
    asbestos_result: str
    notes: str
    outcome: str
    created_at: str


class SalvageBatch(TypedDict, total=False):
    id: str
    job_id: str
    offer_id: Optional[str]
    category_id: str
    status: str
    estimated_weight_lbs: float
    scale_weight_lbs: float
    contamination_weight_lbs: float
    diverted_weight_lbs: float
    weighed_at: Optional[str]
    report_period: str
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict, total=False):
    id: str
    category_id: str
    batch_id: Optional[str]
    offer_id: Optional[str]
    screening_id: Optional[str]
    parent_item_id: Optional[str]
    description_text: str
    condition_grade: str
    measure_qty: float
    measure_unit: str
    pre_1978_flag: bool
    estimated_weight_lbs: float
    pricing_status: str
    sales_status: str
    list_price_cents: int
    current_price_cents: int
    markdown_step: int
    price_override_cents: Optional[int]
    priced_by_user_id: str
    zone_id: Optional[str]
    floor_since: Optional[str]
    days_on_floor: int
    disposition_recommended: str
    sold_via_sale_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StoreZone(TypedDict, total=False):
    id: str
    code: str
    display_name: str
    capacity: int
    current_count: int
    allowed_category_id: Optional[str]
    restock_threshold: int
    restock_recommended: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MarkdownRun(TypedDict, total=False):
    # Lean record (PRD §2.5): only id + created_at; no updated_at / version.
    id: str
    as_of_date: str
    items_evaluated: int
    items_marked_down: int
    items_flagged_disposition: int
    notes: str
    created_at: str


class ContractorAccount(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    status: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    trailing_volume_cents: int
    discount_tier: str
    payment_terms_days: int
    suspension_reason: str
    approved_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class BulkPurchaseAgreement(TypedDict, total=False):
    id: str
    contractor_id: str
    category_id: str
    discount_pct: float
    min_quantity: float
    quantity_unit: str
    valid_from: str
    valid_until: str
    status: str
    supersedes_agreement_id: Optional[str]
    fulfilled_quantity: float
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict, total=False):
    id: str
    sale_channel: str
    contractor_id: Optional[str]
    agreement_id: Optional[str]
    status: str
    tier_snapshot: Optional[str]
    discount_pct_applied: float
    subtotal_cents: int
    bulk_discount_cents: int
    tax_cents: int
    total_cents: int
    payment_amount_cents: int
    finalized_at: Optional[str]
    void_reason: str
    created_at: str
    updated_at: str
    version: int


class SaleLineItem(TypedDict, total=False):
    # Lean record (PRD §2.5): only id + created_at; no updated_at / version.
    id: str
    sale_id: str
    item_id: str
    quantity: float
    unit_price_cents: int
    line_total_cents: int
    created_at: str


class TaxReceipt(TypedDict, total=False):
    id: str
    donor_id: str
    offer_id: str
    receipt_number: str
    status: str
    valuation_method: Optional[str]
    valued_total_cents: int
    appraisal_reference: Optional[str]
    appraisal_value_cents: Optional[int]
    received_by_user_id: str
    issued_by_user_id: str
    issued_at: Optional[str]
    supersedes_receipt_id: Optional[str]
    void_reason: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    full_name: str
    crew_type: str
    hourly_rate_cents: int
    hazmat_certified: bool
    lead_certified: bool
    status: str
    cumulative_job_hours: float
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    job_id: str
    crew_member_id: str
    role_on_job: str
    start_at: str
    end_at: str
    status: str
    hours_worked: float
    labor_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    plate_code: str
    capacity_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupAppointment(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    vehicle_id: str
    window_start: str
    window_end: str
    status: str
    fee_cents: int
    completion_notes: str
    created_at: str
    updated_at: str
    version: int


class DiversionReport(TypedDict, total=False):
    id: str
    period: str
    status: str
    total_diverted_lbs: float
    sold_lbs: float
    donated_lbs: float
    recycled_lbs: float
    landfill_lbs: float
    closed_by_user_id: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
