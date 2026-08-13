"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    DISTRIBUTOR_ADMIN = "DistributorAdmin"
    CONTRACTOR_USER = "ContractorUser"
    WARRANTY_PROCESSOR = "WarrantyProcessor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRAINING_COORDINATOR = "TrainingCoordinator"


class ContractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DealerTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ComplianceStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    HOLD = "HOLD"


class EquipmentType(str, Enum):
    CONDENSER = "CONDENSER"
    HEAT_PUMP = "HEAT_PUMP"
    COIL = "COIL"
    FURNACE = "FURNACE"
    AIR_HANDLER = "AIR_HANDLER"


class RefrigerantType(str, Enum):
    R410A = "R410A"
    R454B = "R454B"
    R32 = "R32"
    NONE = "NONE"


class EquipmentModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"
    ALLOCATED_ONLY = "ALLOCATED_ONLY"


class EfficiencyClass(str, Enum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    PREMIUM = "PREMIUM"


class RatingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class PreBuyProgramStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    BACKORDERED = "BACKORDERED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    DEPOSIT_INVOICED = "DEPOSIT_INVOICED"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    FINAL_INVOICED = "FINAL_INVOICED"
    PAID = "PAID"
    FORFEITED = "FORFEITED"


class AllocationPoolStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RegistrationStatus(str, Enum):
    PENDING_REGISTRATION = "PENDING_REGISTRATION"
    REGISTERED = "REGISTERED"
    LAPSED = "LAPSED"
    VOID = "VOID"


class PartsClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class CylinderStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ISSUED = "ISSUED"
    RETURN_PENDING = "RETURN_PENDING"
    RETURNED = "RETURNED"
    RECLAIMED = "RECLAIMED"


class RefrigerantEventType(str, Enum):
    ISSUE = "ISSUE"
    RECOVERY_IN = "RECOVERY_IN"
    RETURN = "RETURN"
    RECLAIM = "RECLAIM"
    ADJUSTMENT = "ADJUSTMENT"


class RebateStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DOCS_COMPLETE = "DOCS_COMPLETE"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    EXPIRED = "EXPIRED"


class ProgramType(str, Enum):
    FEDERAL_TAX_CREDIT = "FEDERAL_TAX_CREDIT"
    UTILITY_REBATE = "UTILITY_REBATE"


class TrainingCourseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TrainingCreditStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class CoopClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts ---
# Standard entities carry id + created_at + updated_at + version (PRD §2.5).
# RefrigerantEvent is the append-only ledger exception: only id + created_at
# among the system-managed fields; updated_at and version are absent.


class Contractor(TypedDict, total=False):
    id: str
    company_name: str
    license_number: str
    tier: str
    ytd_purchase_cents: int
    coop_accrual_provisional_cents: int
    coop_accrual_final_cents: int
    training_credit_balance_hours: int
    compliance_standing: str
    heel_violation_count_12m: int
    credit_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentModel(TypedDict, total=False):
    id: str
    model_number: str
    equipment_type: str
    refrigerant_type: str
    capacity_btuh: int
    family_code: str
    list_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AHRISystemRating(TypedDict, total=False):
    id: str
    ahri_reference_number: str
    outdoor_unit_id: str
    indoor_unit_id: str
    furnace_id: Optional[str]
    seer2: float
    eer2: float
    hspf2: Optional[float]
    efficiency_class: str
    tax_credit_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PreBuyProgram(TypedDict, total=False):
    id: str
    name: str
    family_code: str
    window_start: str
    window_end: str
    ship_by_date: str
    deposit_pct: float
    discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    contractor_id: str
    prebuy_program_id: Optional[str]
    status: str
    billing_status: str
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    deposit_due_cents: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    ahri_rating_id: Optional[str]
    equipment_model_id: Optional[str]
    quantity: int
    unit_price_cents: int
    line_discount_cents: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class AllocationPool(TypedDict, total=False):
    id: str
    family_code: str
    season_start: str
    season_end: str
    total_qty: int
    reserved_qty: int
    committed_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyRegistration(TypedDict, total=False):
    id: str
    serial_number: str
    equipment_model_id: str
    contractor_id: str
    order_id: str
    install_date: str
    registration_deadline: str
    registered_at: Optional[str]
    extended_coverage_years: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartsClaim(TypedDict, total=False):
    id: str
    claim_number: str
    warranty_registration_id: str
    contractor_id: str
    failure_date: str
    part_cost_cents: int
    labor_cost_cents: int
    covered_part_cents: int
    covered_labor_cents: int
    total_award_cents: int
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RefrigerantCylinder(TypedDict, total=False):
    id: str
    cylinder_tag: str
    refrigerant_type: str
    tare_weight_lbs: float
    full_weight_lbs: float
    current_weight_lbs: float
    holder_contractor_id: Optional[str]
    issued_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RefrigerantEvent(TypedDict, total=False):
    # Append-only ledger entry: id + created_at only among system fields;
    # NO updated_at, NO version (PRD §2.5).
    id: str
    cylinder_id: str
    event_type: str
    weight_delta_lbs: float
    recorded_at: str
    note: Optional[str]
    created_at: str


class RebateSubmission(TypedDict, total=False):
    id: str
    contractor_id: str
    order_id: str
    ahri_rating_id: str
    program_type: str
    homeowner_name: str
    install_address: str
    install_date: str
    docs: List[str]
    qualified_amount_cents: int
    submitted_at: Optional[str]
    decision_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingCourse(TypedDict, total=False):
    id: str
    course_code: str
    title: str
    credit_hours: int
    session_start: str
    session_end: str
    instructor_name: str
    max_seats: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingCredit(TypedDict, total=False):
    id: str
    contractor_id: str
    course_id: str
    credit_hours: int
    earned_at: str
    expires_at: str
    consumed_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CoopClaim(TypedDict, total=False):
    id: str
    contractor_id: str
    invoice_reference: str
    period: str
    spend_cents: int
    eligible_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
