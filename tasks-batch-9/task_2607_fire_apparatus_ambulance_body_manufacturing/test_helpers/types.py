"""Domain types for the Fire Apparatus Body Manufacturing API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them.  Two resources -- the specification clause and the plant bay --
are immutable once created and therefore carry only ``id`` and ``created_at``;
their TypedDicts deliberately omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    PURCHASING_OFFICER = "PurchasingOfficer"
    BODY_ENGINEER = "BodyEngineer"
    THIRD_PARTY_TESTER = "ThirdPartyTester"
    CUSTOMER_COMMITTEE_REP = "CustomerCommitteeRep"


# ─── Status enums ─────────────────────────────────────────────────────────

class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SuspensionReason(str, Enum):
    MANUAL = "MANUAL"
    SOFT_CEILING_BREACH = "SOFT_CEILING_BREACH"


class SpecificationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"


class ClauseCategory(str, Enum):
    CHASSIS = "CHASSIS"
    PUMP = "PUMP"
    AERIAL = "AERIAL"
    PATIENT_COMPARTMENT = "PATIENT_COMPARTMENT"
    ELECTRICAL = "ELECTRICAL"
    PAINT = "PAINT"


class ComplianceResponse(str, Enum):
    COMPLY = "COMPLY"
    EXCEPTION = "EXCEPTION"
    ALTERNATE = "ALTERNATE"


class ComplianceDisposition(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    VOID = "VOID"


class UnitType(str, Enum):
    PUMPER = "PUMPER"
    AERIAL = "AERIAL"
    AMBULANCE = "AMBULANCE"


class BuildStatus(str, Enum):
    SPEC_LOCKED = "SPEC_LOCKED"
    PRE_CON_HELD = "PRE_CON_HELD"
    IN_PRODUCTION = "IN_PRODUCTION"
    MID_CON_HELD = "MID_CON_HELD"
    FINAL_INSPECTED = "FINAL_INSPECTED"
    DELIVERED = "DELIVERED"
    WARRANTY_ACTIVE = "WARRANTY_ACTIVE"
    CANCELLED = "CANCELLED"


class CertificationStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    IN_TESTING = "IN_TESTING"
    CERTIFIED = "CERTIFIED"
    REJECTED_TESTING = "REJECTED_TESTING"


class LongLeadStatus(str, Enum):
    NOT_RESERVED = "NOT_RESERVED"
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    AT_RISK = "AT_RISK"


class WeightStatus(str, Enum):
    WITHIN_LIMITS = "WITHIN_LIMITS"
    OVER_FRONT = "OVER_FRONT"
    OVER_REAR = "OVER_REAR"
    OVER_GVWR = "OVER_GVWR"


class ComponentType(str, Enum):
    CHASSIS = "CHASSIS"
    AERIAL_DEVICE = "AERIAL_DEVICE"
    PATIENT_MODULE = "PATIENT_MODULE"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class TripType(str, Enum):
    PRE_CONSTRUCTION = "PRE_CONSTRUCTION"
    MID_CONSTRUCTION = "MID_CONSTRUCTION"
    FINAL = "FINAL"


class TripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESCINDED = "RESCINDED"


class TestStandard(str, Enum):
    NFPA_1901 = "NFPA_1901"
    NFPA_1911 = "NFPA_1911"
    NFPA_1917 = "NFPA_1917"
    AMD_STD_003 = "AMD_STD_003"


class CertificationTestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    INVALIDATED = "INVALIDATED"


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class InvalidatedReason(str, Enum):
    WEIGHT_STATUS_CHANGE = "WEIGHT_STATUS_CHANGE"
    SPEC_SUPERSEDED = "SPEC_SUPERSEDED"


class WarrantyStatus(str, Enum):
    PENDING_TRAINING = "PENDING_TRAINING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


# ─── Entity shapes ────────────────────────────────────────────────────────

class ApparatusProgram(TypedDict):
    id: str
    name: str
    agency_name: str
    base_year: int
    base_unit_price_cents: int
    escalation_index_pct_per_year: float
    max_option_units: int
    options_exercised_count: int
    contract_ceiling_cents: int
    committed_cents: int
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BidSpecification(TypedDict):
    id: str
    program_id: str
    supersedes_spec_id: Optional[str]
    title: str
    revision_number: int
    authored_by_user_id: str
    released_by_user_id: Optional[str]
    status: str
    clause_count: int
    mandatory_clause_count: int
    compliance_score_strict: float
    compliance_score_provisional: float
    restrictive_clause_ratio_pct: float
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpecClause(TypedDict):
    """Immutable once appended: carries only id and created_at."""
    id: str
    specification_id: str
    clause_code: str
    category: str
    requirement_text: str
    mandatory: bool
    is_restrictive: bool
    created_at: str


class ComplianceMatrixEntry(TypedDict):
    id: str
    specification_id: str
    clause_id: str
    response: str
    exception_text: Optional[str]
    disposition: str
    disposition_note: Optional[str]
    responded_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class UnitOrder(TypedDict):
    id: str
    program_id: str
    specification_id: str
    chassis_reservation_id: Optional[str]
    unit_type: str
    option_unit: bool
    award_year: int
    gvwr_kg: int
    front_axle_rating_kg: int
    rear_axle_rating_kg: int
    base_curb_front_kg: int
    base_curb_rear_kg: int
    crew_seat_count: int
    weight_calc_engineer_user_id: str
    front_axle_load_kg: int
    rear_axle_load_kg: int
    gross_weight_kg: int
    weight_status: str
    price_cents: int
    change_order_total_cents: int
    open_change_order_count: int
    build_status: str
    certification_status: str
    long_lead_status: str
    spec_drift_flag: bool
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplierSlotLine(TypedDict):
    id: str
    supplier_name: str
    component_type: str
    total_slot_count: int
    changeover_buffer_days: int
    reserved_slot_count: int
    available_slot_count: int
    created_at: str
    updated_at: str
    version: int


class ChassisReservation(TypedDict):
    id: str
    program_id: str
    slot_line_id: str
    unit_order_id: Optional[str]
    slot_start_date: str
    slot_end_date: str
    reserved_price_cents: int
    expiry_at: str
    status: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlantBay(TypedDict):
    """Immutable once registered: carries only id and created_at."""
    id: str
    name: str
    max_concurrent_visitors: int
    created_at: str


class InspectionTrip(TypedDict):
    id: str
    unit_order_id: str
    plant_bay_id: str
    trip_type: str
    scheduled_start: str
    scheduled_end: str
    committee_size: int
    status: str
    held_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeOrderLineItem(TypedDict):
    description: str
    quantity: int
    unit_cost_cents: int
    markup_pct: float
    is_taxable: bool


class ChangeOrder(TypedDict):
    id: str
    unit_order_id: str
    inspection_trip_id: str
    line_items: List[ChangeOrderLineItem]
    weight_delta_front_kg: int
    weight_delta_rear_kg: int
    price_delta_cents: int
    revision_count: int
    raised_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificationTest(TypedDict):
    id: str
    unit_order_id: str
    test_standard: str
    submitted_by_user_id: str
    signed_by_user_id: Optional[str]
    result: Optional[str]
    status: str
    tested_at: Optional[str]
    invalidated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyStartup(TypedDict):
    id: str
    unit_order_id: str
    delivery_date: str
    training_hours: float
    warranty_months: int
    warranty_start_date: str
    warranty_end_date: str
    final_price_cents: int
    price_variance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
