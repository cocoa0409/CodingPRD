"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    CENTER_ADMIN = "CenterAdmin"
    PROGRAM_MANAGER = "ProgramManager"
    DESIGN_LEAD = "DesignLead"
    SHOP_TECHNICIAN = "ShopTechnician"
    QUALITY_INSPECTOR = "QualityInspector"
    FINANCE_CLERK = "FinanceClerk"
    CUSTOMER_REP = "CustomerRep"


class CreditStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    CREDIT_HOLD = "CREDIT_HOLD"


class AircraftStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    IN_REFURB = "IN_REFURB"
    RETURNED = "RETURNED"


class ProgramPhase(str, Enum):
    QUOTED = "QUOTED"
    BOOKED = "BOOKED"
    INDUCTED = "INDUCTED"
    SURFACE_REVIEW = "SURFACE_REVIEW"
    IN_WORK = "IN_WORK"
    IN_INSPECTION = "IN_INSPECTION"
    READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class SchemeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class AssessmentStatus(str, Enum):
    PENDING = "PENDING"
    DECIDED = "DECIDED"
    SUPERSEDED = "SUPERSEDED"


class AssessmentDecision(str, Enum):
    STRIP = "STRIP"
    SCUFF = "SCUFF"


class CorrosionSeverity(str, Enum):
    NONE = "NONE"
    LIGHT = "LIGHT"
    HEAVY = "HEAVY"


class DiscoveryStatus(str, Enum):
    OPEN = "OPEN"
    ESTIMATED = "ESTIMATED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


class DiscoverySource(str, Enum):
    MANUAL = "MANUAL"
    INSPECTION_AUTO = "INSPECTION_AUTO"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COUNTERED = "COUNTERED"


class ChangeOrderKind(str, Enum):
    SCOPE = "SCOPE"
    WEIGHT_ACK = "WEIGHT_ACK"


class BayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SlotStatus(str, Enum):
    BOOKED = "BOOKED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LotStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    IN_TEST = "IN_TEST"
    CERTIFIED = "CERTIFIED"
    CERT_FAILED = "CERT_FAILED"
    CERT_QUARANTINED = "CERT_QUARANTINED"


class BurnTestMethod(str, Enum):
    VERTICAL_12S = "VERTICAL_12S"
    VERTICAL_60S = "VERTICAL_60S"
    HORIZONTAL_25 = "HORIZONTAL_25"


class BurnTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class WeightRecordVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class WeightRecordStatus(str, Enum):
    PREPARED = "PREPARED"
    SIGNED_OFF = "SIGNED_OFF"
    SUPERSEDED = "SUPERSEDED"


class InspectionType(str, Enum):
    PREP = "PREP"
    PAINT = "PAINT"
    INTERIOR = "INTERIOR"
    FINAL = "FINAL"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class DelayCategory(str, Enum):
    CUSTOMER_CAUSED = "CUSTOMER_CAUSED"
    CENTER_CAUSED = "CENTER_CAUSED"
    FORCE_MAJEURE = "FORCE_MAJEURE"


class DelayStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"


class DelaySource(str, Enum):
    MANUAL = "MANUAL"
    CHANGE_ORDER = "CHANGE_ORDER"


class InvoiceKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    PROGRESS = "PROGRESS"
    FINAL = "FINAL"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


# --- Entity TypedDicts (common fields per PRD §2.5) ---

class Customer(TypedDict):
    id: str
    name: str
    contact_email: str
    credit_status: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict):
    id: str
    customer_id: str
    tail_number: str
    model: str
    max_delta_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RefurbProgram(TypedDict):
    id: str
    aircraft_id: str
    customer_id: str
    base_price_cents: int
    daily_penalty_rate_cents: int
    penalty_cap_pct: float
    contractual_delivery_date: str
    committed_delivery_date: str
    actual_delivery_date: Optional[str]
    status: str
    total_contract_value_cents: int
    discovery_cost_total_cents: int
    billed_total_cents: int
    penalty_final_cents: int
    projected_penalty_cents: int
    rework_cycles: int
    approved_scheme_id: Optional[str]
    material_estimate_gallons: int
    material_estimate_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class PaintScheme(TypedDict):
    id: str
    program_id: str
    drawing_ref: str
    painted_area_sqft: int
    coat_count: int
    stripe_pct: float
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurfaceAssessment(TypedDict):
    id: str
    program_id: str
    status: str
    decision: Optional[str]
    corrosion_severity: Optional[str]
    findings_note: Optional[str]
    revision: int
    created_at: str
    updated_at: str
    version: int


class DiscoveryItem(TypedDict):
    id: str
    program_id: str
    assessment_id: Optional[str]
    source: str
    description: str
    safety_linked: bool
    status: str
    est_cost_cents: Optional[int]
    est_hours: Optional[int]
    actual_cost_cents: Optional[int]
    defer_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    program_id: str
    kind: str
    delta_price_cents: int
    delta_days: int
    description: str
    acknowledges_weight_record_id: Optional[str]
    status: str
    counter_note: Optional[str]
    negotiation_round: int
    created_at: str
    updated_at: str
    version: int


class HangarBay(TypedDict):
    id: str
    name: str
    daily_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HangarSlot(TypedDict):
    id: str
    bay_id: str
    program_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PaintBooth(TypedDict):
    id: str
    name: str
    hourly_rate_cents: int
    cure_buffer_hours: int
    created_at: str
    updated_at: str
    version: int


class BoothBooking(TypedDict):
    id: str
    booth_id: str
    program_id: str
    start_at: str
    end_at: str
    status: str
    actual_hours: Optional[int]
    scheduled_fee_cents: int
    actual_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SoftGoodLot(TypedDict):
    id: str
    program_id: str
    description: str
    material: str
    quantity: int
    estimated_weight_lbs: float
    status: str
    fail_count: int
    created_at: str
    updated_at: str
    version: int


# Append-only record (PRD §2.5): only id + created_at are system-managed;
# updated_at and version are absent.
class BurnTest(TypedDict):
    id: str
    lot_id: str
    test_method: str
    result: str
    lab_name: str
    test_sequence: int
    created_at: str


class WeightBalanceRecord(TypedDict):
    id: str
    program_id: str
    scheme_id: str
    variant: str
    removal_weight_lbs: float
    installed_weight_lbs: float
    film_lbs: float
    delta_lbs: float
    status: str
    prepared_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class QualityInspection(TypedDict):
    id: str
    program_id: str
    inspection_type: str
    status: str
    major_defects: Optional[int]
    minor_defects: Optional[int]
    rework_of_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DelayEvent(TypedDict):
    id: str
    program_id: str
    category: str
    impact_days: int
    reason: str
    source: str
    status: str
    event_seq: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    program_id: str
    kind: str
    status: str
    lines: list
    total_cents: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
