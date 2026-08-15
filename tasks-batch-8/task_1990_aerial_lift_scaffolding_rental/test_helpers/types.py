"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EquipmentCategory(str, Enum):
    AERIAL_LIFT = "AERIAL_LIFT"
    SCAFFOLD = "SCAFFOLD"


class EquipmentUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_RENT = "ON_RENT"
    QUARANTINED = "QUARANTINED"
    LOST = "LOST"


class RentalContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class RentalLineStatus(str, Enum):
    RESERVED = "RESERVED"
    OUT_ON_RENT = "OUT_ON_RENT"
    OFF_RENT = "OFF_RENT"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class DeliveryTripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TripType(str, Enum):
    DELIVERY = "DELIVERY"
    PICKUP = "PICKUP"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class InspectionRecordStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class ClaimType(str, Enum):
    DAMAGE = "DAMAGE"
    LOST = "LOST"
    STOLEN = "STOLEN"


class DamageClaimStatus(str, Enum):
    OPEN = "OPEN"
    ASSESSED = "ASSESSED"
    CHARGED = "CHARGED"
    DISPUTED = "DISPUTED"
    WAIVED = "WAIVED"


class ClaimDecision(str, Enum):
    UPHOLD = "UPHOLD"
    WAIVE = "WAIVE"


class UserRole(str, Enum):
    BRANCH_MANAGER = "BranchManager"
    RENTAL_COORDINATOR = "RentalCoordinator"
    DRIVER = "Driver"
    YARD_TECHNICIAN = "YardTechnician"
    CUSTOMER = "Customer"


# ─── Entities with the full common field set (PRD §2.5) ─────────────────────

class CustomerAccount(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    credit_limit_cents: int
    status: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class EquipmentClass(TypedDict, total=False):
    id: str
    class_code: str
    category: str
    max_working_height_ft: int
    min_rental_days: int
    daily_rate_cents: int
    weekly_rate_cents: int
    monthly_rate_cents: int
    replacement_value_cents: int
    requires_familiarization: bool
    requires_engineering: bool
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict, total=False):
    id: str
    class_id: str
    serial_number: str
    ansi_standard_ref: str
    status: str
    last_annual_inspection_date: str
    next_inspection_due_date: str
    created_at: str
    updated_at: str
    version: int


class RentalContract(TypedDict, total=False):
    id: str
    customer_id: str
    jobsite_address: str
    damage_waiver_elected: bool
    status: str
    rental_subtotal_cents: int
    logistics_subtotal_cents: int
    damage_subtotal_cents: int
    invoice_total_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RentalLine(TypedDict, total=False):
    id: str
    contract_id: str
    unit_id: str
    class_id: str
    status: str
    requested_start_date: str
    requested_end_date: str
    required_working_height_ft: int
    engineering_plan_ref: Optional[str]
    on_rent_at: Optional[str]
    off_rent_at: Optional[str]
    segment_count: int
    accrued_charge_cents: int
    final_charge_cents: Optional[int]
    provisional_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class DeliveryTrip(TypedDict, total=False):
    id: str
    contract_id: str
    line_id: str
    trip_type: str
    status: str
    driver_id: str
    planned_start_utc: str
    planned_end_utc: str
    standby_minutes: int
    standby_charge_cents: int
    crew_labor_hours: float
    labor_charge_cents: int
    trip_fee_cents: int
    failure_reason: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionRecord(TypedDict, total=False):
    id: str
    unit_id: str
    inspector_id: str
    inspection_date: str
    ansi_standard_ref: str
    result: str
    status: str
    certified_by: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    line_id: str
    contract_id: str
    unit_id: str
    claim_type: str
    description: str
    status: str
    repair_estimate_cents: Optional[int]
    chargeback_cents: Optional[int]
    recovery_credit_cents: Optional[int]
    reported_by: str
    resolved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


# TrainingRecord is the PRD §2.5 exception: created once, never modified —
# it carries only id + created_at; updated_at and version are absent.
class TrainingRecord(TypedDict, total=False):
    id: str
    customer_id: str
    class_id: str
    trainee_name: str
    trained_at: str
    trainer_id: str
    valid_until: str
    is_valid: bool
    created_at: str


class InvoiceView(TypedDict, total=False):
    contract_id: str
    status: str
    rental_subtotal_cents: int
    logistics_subtotal_cents: int
    damage_subtotal_cents: int
    invoice_total_cents: int
