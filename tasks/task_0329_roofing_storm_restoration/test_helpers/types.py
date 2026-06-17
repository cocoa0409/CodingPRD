"""Domain types: entity TypedDicts, status enums, role enum for the Roofing
Storm Restoration API.

Field sets follow the PRD (§2.4): Job, Crew, Inspection, Estimate,
EstimateLineItem, MaterialOrder, CrewAssignment, Permit, Draw, ChangeOrder,
and Warranty carry the full common set (id, created_at, updated_at, version).
Estimator is immutable reference data carrying only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) -----------------------------------------------------

class UserRole(str, Enum):
    FIELD_ADJUSTER = "FieldAdjuster"
    ESTIMATOR = "Estimator"
    PRODUCTION_MANAGER = "ProductionManager"


# --- Status enums (PRD §3 state machines) -------------------------------------

class JobStatus(str, Enum):
    LEAD = "LEAD"
    INSPECTED = "INSPECTED"
    ESTIMATED = "ESTIMATED"
    CONTRACTED = "CONTRACTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    LOST = "LOST"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class MaterialOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class CrewAssignmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class DrawStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISBURSED = "DISBURSED"
    REJECTED = "REJECTED"


class ChangeOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class WarrantyStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


# --- Domain value enums -------------------------------------------------------

class Peril(str, Enum):
    HAIL = "HAIL"
    WIND = "WIND"
    HURRICANE = "HURRICANE"
    OTHER = "OTHER"


class InspectionKind(str, Enum):
    DAMAGE_ASSESSMENT = "DAMAGE_ASSESSMENT"
    PERMIT_FINAL = "PERMIT_FINAL"


class DamageSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    TOTAL_LOSS = "TOTAL_LOSS"


class SourceKind(str, Enum):
    AERIAL = "AERIAL"
    FIELD = "FIELD"


class Trade(str, Enum):
    SHINGLE = "SHINGLE"
    UNDERLAYMENT = "UNDERLAYMENT"
    RIDGE_VENT = "RIDGE_VENT"
    FLASHING = "FLASHING"
    DECKING = "DECKING"
    GUTTER = "GUTTER"


class CancelBasis(str, Enum):
    PRORATED = "PRORATED"
    SHORT_RATE = "SHORT_RATE"


# --- Entity TypedDicts --------------------------------------------------------
# common_fields: true entities carry id + created_at + updated_at + version.

class Job(TypedDict, total=False):
    id: str
    customer_name: str
    property_address: str
    peril: str
    insurance_carrier: Optional[str]
    status: str
    assigned_estimator_id: str
    bound_estimate_id: Optional[str]
    contract_value_cents: int
    disbursed_gross_cents: int
    retainage_held_cents: int
    disbursed_net_cents: int
    billed_pct: float
    remaining_billable_cents: int
    retainage_pct: float
    lost_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable reference data: ONLY id + created_at.
class Estimator(TypedDict, total=False):
    id: str
    name: str
    license_no: str
    created_at: str


class Crew(TypedDict, total=False):
    id: str
    name: str
    max_squares_per_day: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    job_id: str
    kind: str
    permit_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    damage_severity: Optional[str]
    status: str
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict, total=False):
    id: str
    job_id: str
    source_kind: str
    aerial_contingency_pct: float
    status: str
    line_subtotal_cents: int
    final_total_cents: int
    created_at: str
    updated_at: str
    version: int


class EstimateLineItem(TypedDict, total=False):
    id: str
    estimate_id: str
    trade: str
    squares: float
    waste_factor_pct: float
    unit_price_cents: int
    line_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class MaterialOrder(TypedDict, total=False):
    id: str
    job_id: str
    bundles: int
    total_weight_lbs: int
    freight_cents: int
    status: str
    delivered_short: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    job_id: str
    crew_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    job_id: str
    municipality: str
    permit_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Draw(TypedDict, total=False):
    id: str
    job_id: str
    cumulative_pct: float
    expected_job_version: int
    gross_eligible_cents: int
    retainage_cents: int
    net_disbursed_cents: int
    is_final: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    job_id: str
    reason: str
    delta_cents: int
    extra_shingle_squares: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Warranty(TypedDict, total=False):
    id: str
    job_id: str
    term_months: int
    premium_cents: int
    start_at: str
    status: str
    cancel_basis: Optional[str]
    refund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
