"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class ProductGrade(str, Enum):
    GASOLINE = "GASOLINE"
    DIESEL = "DIESEL"
    JET = "JET"
    ETHANOL = "ETHANOL"
    CRUDE = "CRUDE"


class UserRole(str, Enum):
    TERMINAL_MANAGER = "TerminalManager"
    TERMINAL_OPERATOR = "TerminalOperator"
    SCHEDULER = "Scheduler"
    GAUGER = "Gauger"
    QUALITY_INSPECTOR = "QualityInspector"
    BILLING_CLERK = "BillingClerk"
    CUSTOMER_REP = "CustomerRep"


class TankStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    RESTRICTED = "RESTRICTED"


class VaporControlClass(str, Enum):
    NONE = "NONE"
    VRU_REQUIRED = "VRU_REQUIRED"


class ResourceType(str, Enum):
    DOCK = "DOCK"
    RAIL_RACK = "RAIL_RACK"
    TRUCK_BAY = "TRUCK_BAY"


class ResourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class SuspensionReason(str, Enum):
    MANUAL = "MANUAL"
    LOSS_CONTROL = "LOSS_CONTROL"


class AmendmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class PermitType(str, Enum):
    VAPOR_CONTROL = "VAPOR_CONTROL"
    HOT_WORK = "HOT_WORK"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class MovementDirection(str, Enum):
    RECEIPT = "RECEIPT"
    DISCHARGE = "DISCHARGE"


class MovementMode(str, Enum):
    VESSEL = "VESSEL"
    RAIL = "RAIL"
    TRUCK = "TRUCK"


class MovementStatus(str, Enum):
    NOMINATED = "NOMINATED"
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    ACCRUED = "ACCRUED"
    INVOICED = "INVOICED"


class TicketType(str, Enum):
    OPENING = "OPENING"
    CLOSING = "CLOSING"


class SampleType(str, Enum):
    FIRST_FOOT = "FIRST_FOOT"
    INLINE = "INLINE"
    ALL_LEVELS = "ALL_LEVELS"


class LabResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class RetainStatus(str, Enum):
    RETAINED = "RETAINED"
    RELEASED = "RELEASED"


class CustodyStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    INVOICED = "INVOICED"


class Customer(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Tank(TypedDict, total=False):
    id: str
    tank_code: str
    product_grade: str
    capacity_bbl: float
    safe_fill_pct: float
    heel_bbl: float
    vapor_control_class: str
    working_capacity_bbl: float
    current_inventory_bbl: float
    provisional_inventory_bbl: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TerminalResource(TypedDict, total=False):
    id: str
    resource_code: str
    resource_type: str
    concurrent_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseAgreement(TypedDict, total=False):
    id: str
    customer_id: str
    product_grade: str
    committed_capacity_bbl: float
    min_monthly_throughput_bbl: float
    throughput_fee_per_bbl: float
    shortfall_fee_per_bbl: float
    loss_allowance_pct: float
    excess_loss_rate_per_bbl: float
    start_date: str
    end_date: str
    reserved_capacity_bbl: float
    suspension_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseAmendment(TypedDict, total=False):
    id: str
    lease_id: str
    proposed_committed_capacity_bbl: Optional[float]
    proposed_throughput_fee_per_bbl: Optional[float]
    proposed_min_monthly_throughput_bbl: Optional[float]
    base_lease_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TankAllocation(TypedDict, total=False):
    id: str
    lease_id: str
    tank_id: str
    allocated_bbl: float
    period_start: str
    period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    permit_type: str
    tank_id: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Movement(TypedDict, total=False):
    id: str
    sequence_no: int
    lease_id: str
    tank_id: str
    resource_id: Optional[str]
    direction: str
    mode: str
    product_grade: str
    declared_volume_bbl: float
    window_start: str
    window_end: str
    actual_arrival_at: Optional[str]
    actual_start_at: Optional[str]
    actual_complete_at: Optional[str]
    demurrage_estimated_amount: Optional[float]
    demurrage_actual_amount: Optional[float]
    status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


# Append-only measurement record (PRD §2.5): carries ONLY id + created_at;
# neither updated_at nor version exists on a gauge ticket.
class GaugeTicket(TypedDict, total=False):
    id: str
    movement_id: str
    ticket_type: str
    observed_volume_bbl: float
    observed_temp_f: float
    observed_at: str
    recorded_by_user_id: str
    created_at: str


class QualitySample(TypedDict, total=False):
    id: str
    movement_id: str
    sample_type: str
    collected_by_user_id: str
    lab_result: str
    specific_gravity: Optional[float]
    result_recorded_by_user_id: Optional[str]
    retain_until: str
    retain_status: str
    created_at: str
    updated_at: str
    version: int


class CustodyTransfer(TypedDict, total=False):
    id: str
    movement_id: str
    provisional_volume_bbl: Optional[float]
    certified_volume_bbl: Optional[float]
    shrinkage_bbl: Optional[float]
    allowed_loss_bbl: Optional[float]
    excess_loss_bbl: Optional[float]
    excess_loss_charge: Optional[float]
    certified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MonthlyStatement(TypedDict, total=False):
    id: str
    lease_id: str
    period: str
    period_start: str
    period_end_exclusive: str
    total_throughput_bbl: float
    throughput_fee_amount: float
    shortfall_bbl: float
    shortfall_fee_amount: float
    total_excess_loss_bbl: float
    excess_loss_amount: float
    total_demurrage_amount: float
    total_dwell_amount: float
    statement_total_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int
