"""Domain types for the DMC Ground Operations API: status enums, role enum, entity TypedDicts.

Field names and status values are taken verbatim from PRD.md.
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    OPERATIONS_COORDINATOR = "OperationsCoordinator"
    SUPPLIER_MANAGER = "SupplierManager"
    SUPPLIER = "Supplier"
    CONTROLLER = "Controller"
    PERMIT_OFFICER = "PermitOfficer"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ProgramExecutionStatus(str, Enum):
    DRAFT = "DRAFT"
    DESIGN_LOCKED = "DESIGN_LOCKED"
    CONFIRMED = "CONFIRMED"
    IN_EXECUTION = "IN_EXECUTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ProgramSettlementStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RECONCILING = "RECONCILING"
    CLIENT_INVOICED = "CLIENT_INVOICED"
    CREDITED = "CREDITED"
    SETTLED = "SETTLED"


class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SupplierStatus(str, Enum):
    PROSPECT = "PROSPECT"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class SupplierType(str, Enum):
    VENUE_SERVICES = "VENUE_SERVICES"
    TRANSPORT = "TRANSPORT"
    ACTIVITY = "ACTIVITY"
    STAFFING = "STAFFING"


class SupplierContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    COUNTERED = "COUNTERED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    CLOSED = "CLOSED"


class CancellationTier(str, Enum):
    STANDARD = "STANDARD"
    STRICT = "STRICT"


class ProgramElementStatus(str, Enum):
    PLANNED = "PLANNED"
    PERMIT_BLOCKED = "PERMIT_BLOCKED"
    READY = "READY"
    DELIVERED = "DELIVERED"
    WEATHER_SWITCHED = "WEATHER_SWITCHED"
    CANCELLED = "CANCELLED"


class ElementType(str, Enum):
    ACTIVITY = "ACTIVITY"
    DINE_AROUND = "DINE_AROUND"
    OFF_PREMISE_EVENT = "OFF_PREMISE_EVENT"
    TRANSFER_BLOCK = "TRANSFER_BLOCK"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CONDITIONS_REQUESTED = "CONDITIONS_REQUESTED"


class PermitType(str, Enum):
    STREET_CLOSURE = "STREET_CLOSURE"
    SPECIAL_VENUE = "SPECIAL_VENUE"
    OFF_PREMISE_ALCOHOL = "OFF_PREMISE_ALCOHOL"


class PermitDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CONDITIONS_REQUESTED = "CONDITIONS_REQUESTED"


class TransportSegmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class SegmentType(str, Enum):
    ARRIVAL_TRANSFER = "ARRIVAL_TRANSFER"
    DEPARTURE_TRANSFER = "DEPARTURE_TRANSFER"
    SHUTTLE_LOOP = "SHUTTLE_LOOP"
    DINE_AROUND_LEG = "DINE_AROUND_LEG"


class ManifestEntryStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CHECKED_IN = "CHECKED_IN"
    RELEASED = "RELEASED"
    NO_SHOW = "NO_SHOW"


class StaffMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class StaffRoleType(str, Enum):
    COORDINATOR = "COORDINATOR"
    GREETER = "GREETER"
    ACTIVITY_LEAD = "ACTIVITY_LEAD"


class CredentialStatus(str, Enum):
    VALID = "VALID"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"


class StaffAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"
    NO_SHOW = "NO_SHOW"


class AssignmentTargetType(str, Enum):
    ELEMENT = "ELEMENT"
    SEGMENT = "SEGMENT"


class ReconciliationLineStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class LineKind(str, Enum):
    DELIVERY = "DELIVERY"
    CANCELLATION_PENALTY = "CANCELLATION_PENALTY"


class SettlementPaymentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOID = "VOID"


# --------------------------------------------------------------------------
# Entity TypedDicts.
# Every persisted resource carries id, created_at, updated_at and version
# (PRD §2.4: "No entity in this system is exempt from `updated_at` or `version`.")
# --------------------------------------------------------------------------
class Program(TypedDict):
    id: str
    client_name: str
    group_name: str
    arrival_date: str
    departure_date: str
    guaranteed_count: int
    markup_pct: float
    execution_status: str
    settlement_status: str
    invoice_issued_at: Optional[str]
    element_count: int
    open_element_count: int
    actual_attendance_total: int
    estimated_client_total_cents: int
    final_subtotal_cents: int
    disclosed_markup_cents: int
    management_fee_cents: int
    final_client_total_cents: int
    supplier_gross_payable_cents: int
    supplier_settled_cents: int
    supplier_open_payable_cents: int
    credit_note_cents: int
    seated_guest_count: int
    staffing_gap_count: int
    unseated_guest_count: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    name: str
    capacity_seated: int
    capacity_reception: int
    turnover_buffer_minutes: int
    requires_special_venue_permit: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    legal_name: str
    supplier_type: str
    insurance_expires_on: str
    insurance_liability_limit_cents: int
    coi_verified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplierContract(TypedDict):
    id: str
    program_id: str
    supplier_id: str
    contract_value_cents: int
    required_liability_limit_cents: int
    deposit_pct: float
    cancellation_tier: str
    status: str
    round_count: int
    deposit_due_cents: int
    deposit_paid_cents: int
    sent_by_user_id: Optional[str]
    countersigned_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramElement(TypedDict):
    id: str
    program_id: str
    supplier_id: str
    venue_id: Optional[str]
    element_type: str
    title: str
    starts_at: str
    ends_at: str
    planned_headcount: int
    guaranteed_headcount: int
    per_person_cost_cents: int
    predecessor_element_id: Optional[str]
    alternative_for_element_id: Optional[str]
    is_weather_dependent: bool
    status: str
    actual_headcount: Optional[int]
    delivered_at: Optional[str]
    cancellation_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    element_id: str
    permit_type: str
    authority_name: str
    lead_time_days_required: int
    status: str
    resubmission_count: int
    submitted_at: Optional[str]
    decision_at: Optional[str]
    conditions_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransportSegment(TypedDict):
    id: str
    program_id: str
    segment_type: str
    vehicle_code: str
    origin: str
    destination: str
    depart_at: str
    arrive_at: str
    seat_capacity: int
    wheelchair_accessible: bool
    status: str
    booked_seat_count: int
    departed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ManifestEntry(TypedDict):
    id: str
    segment_id: str
    guest_ref: str
    guest_name: str
    seat_count: int
    mobility_assist: bool
    status: str
    move_count: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    full_name: str
    role_type: str
    badge_expires_on: str
    first_aid_expires_on: str
    pay_rate_cents_per_hour: int
    min_rest_minutes: int
    max_daily_minutes: int
    status: str
    credential_status: str
    confirmed_minutes_total: int
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict):
    id: str
    staff_id: str
    program_id: str
    target_type: str
    element_id: Optional[str]
    segment_id: Optional[str]
    role_type: str
    starts_at: str
    ends_at: str
    status: str
    check_in_at: Optional[str]
    completed_at: Optional[str]
    planned_labor_cost_cents: int
    actual_labor_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class ReconciliationLine(TypedDict):
    id: str
    program_id: str
    element_id: str
    supplier_id: str
    line_kind: str
    guaranteed_headcount: int
    actual_headcount: int
    billed_headcount: int
    supplier_cost_cents: int
    markup_cents: int
    client_charge_cents: int
    variance_pct: float
    variance_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementPayment(TypedDict):
    id: str
    program_id: str
    supplier_id: str
    contract_id: str
    status: str
    gross_cents: int
    deposit_applied_cents: int
    net_payable_cents: int
    overpayment_credit_cents: int
    approved_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
