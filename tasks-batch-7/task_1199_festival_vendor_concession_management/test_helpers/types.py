"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    FESTIVAL_DIRECTOR = "FestivalDirector"
    VENDOR_MANAGER = "VendorManager"
    OPERATIONS_LEAD = "OperationsLead"
    HEALTH_INSPECTOR = "HealthInspector"
    SUSTAINABILITY_OFFICER = "SustainabilityOfficer"
    FINANCE_LEAD = "FinanceLead"
    VENDOR = "Vendor"


class FestivalStatus(str, Enum):
    PLANNING = "PLANNING"
    APPLICATIONS_OPEN = "APPLICATIONS_OPEN"
    CURATED = "CURATED"
    LIVE = "LIVE"
    SETTLEMENT = "SETTLEMENT"
    CLOSED = "CLOSED"


class VendorStatus(str, Enum):
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class ApplicationCategory(str, Enum):
    FOOD_HOT = "FOOD_HOT"
    FOOD_COLD = "FOOD_COLD"
    BEVERAGE_ALCOHOL = "BEVERAGE_ALCOHOL"
    BEVERAGE_NA = "BEVERAGE_NA"
    DESSERT = "DESSERT"
    MERCHANDISE = "MERCHANDISE"


class FeeModel(str, Enum):
    FLAT_FEE = "FLAT_FEE"
    REVENUE_SHARE = "REVENUE_SHARE"
    HYBRID = "HYBRID"


class TierMode(str, Enum):
    MARGINAL = "MARGINAL"
    WHOLE_TIER = "WHOLE_TIER"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WAITLISTED = "WAITLISTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class BoothStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    ASSIGNED = "ASSIGNED"


class AssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"


class UtilityStatus(str, Enum):
    PENDING = "PENDING"
    PROVISIONED = "PROVISIONED"


class InspectionType(str, Enum):
    HEALTH_PREOPEN = "HEALTH_PREOPEN"
    HEALTH_SPOT = "HEALTH_SPOT"
    FIRE_SAFETY = "FIRE_SAFETY"


class InspectionResult(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class Gate(str, Enum):
    GATE_A = "GATE_A"
    GATE_B = "GATE_B"
    GATE_C = "GATE_C"


class ReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class TransactionStatus(str, Enum):
    REPORTED = "REPORTED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILING = "RECONCILING"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    PAID = "PAID"


class FineType(str, Enum):
    WASTE_SORTING = "WASTE_SORTING"
    COMPOST_CONTAMINATION = "COMPOST_CONTAMINATION"
    GREASE_DISPOSAL = "GREASE_DISPOSAL"
    HEALTH_VIOLATION = "HEALTH_VIOLATION"
    NO_SHOW_PENALTY = "NO_SHOW_PENALTY"


class FineStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    SCORED = "SCORED"
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    INELIGIBLE = "INELIGIBLE"


# --- Entity TypedDicts (common_fields: id + created_at + updated_at + version) ---

class Festival(TypedDict):
    id: str
    name: str
    event_start: str
    event_end: str
    category_cap_per_category: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    status: str
    compliance_strikes: int
    created_at: str
    updated_at: str
    version: int


class VendorApplication(TypedDict):
    id: str
    vendor_id: str
    festival_id: str
    category: str
    fee_model: str
    proposed_flat_fee_cents: Optional[int]
    proposed_revenue_share_pct_bp: Optional[int]
    power_needed_amps: int
    requires_water: bool
    supersedes_application_id: Optional[str]
    review_round: int
    curated_fee_model: Optional[str]
    curated_flat_fee_cents: Optional[int]
    curated_revenue_share_pct_bp: Optional[int]
    curated_tier_mode: Optional[str]
    curated_minimum_guarantee_cents: Optional[int]
    curated_free_allowance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict):
    id: str
    festival_id: str
    name: str
    power_capacity_amps: int
    water_hookup_total: int
    reserved_power_amps: int
    reserved_water_hookups: int
    created_at: str
    updated_at: str
    version: int


class Booth(TypedDict):
    id: str
    zone_id: str
    label: str
    power_outlet_max_amps: int
    has_water_hookup: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BoothAssignment(TypedDict):
    id: str
    application_id: str
    booth_id: str
    festival_id: str
    zone_id: str
    status: str
    utility_status: str
    power_draw_amps: int
    requires_water: bool
    fee_model: Optional[str]
    flat_fee_cents: Optional[int]
    revenue_share_pct_bp: Optional[int]
    tier_mode: Optional[str]
    minimum_guarantee_cents: Optional[int]
    free_allowance_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InspectionRecord(TypedDict):
    # Immutable event: id + created_at only; NO updated_at, NO version.
    id: str
    assignment_id: str
    festival_id: str
    type: str
    result: str
    notes: Optional[str]
    status: str
    created_at: str


class LoadInSlot(TypedDict):
    id: str
    festival_id: str
    gate: str
    window_start: str
    window_end: str
    max_vehicles: int
    reserved_vehicle_count: int
    created_at: str
    updated_at: str
    version: int


class LoadInReservation(TypedDict):
    id: str
    assignment_id: str
    slot_id: str
    festival_id: str
    vehicle_count: int
    status: str
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PosTransaction(TypedDict):
    id: str
    assignment_id: str
    festival_id: str
    amount_cents: int
    occurred_at: str
    idempotency_key: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    assignment_id: str
    festival_id: str
    status: str
    provisional_gross_cents: Optional[int]
    provisional_share_cents: Optional[int]
    provisional_payout_cents: Optional[int]
    gross_sales_cents: Optional[int]
    festival_share_cents: Optional[int]
    fine_deduction_cents: Optional[int]
    vendor_payout_cents: Optional[int]
    vendor_balance_due_cents: Optional[int]
    reconciled_by_user_id: Optional[str]
    finalized_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceFine(TypedDict):
    id: str
    assignment_id: str
    festival_id: str
    type: str
    amount_cents: int
    description: Optional[str]
    status: str
    created_by_user_id: str
    waived_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceReview(TypedDict):
    id: str
    assignment_id: str
    festival_id: str
    vendor_id: str
    status: str
    sales_percentile: Optional[int]
    compliance_component: Optional[int]
    operations_component: Optional[int]
    official_score: Optional[int]
    strict_score: Optional[int]
    created_at: str
    updated_at: str
    version: int
