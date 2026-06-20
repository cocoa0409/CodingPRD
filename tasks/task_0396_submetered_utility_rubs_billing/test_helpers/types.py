"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the standard mutation accounting fields
(id, created_at, updated_at, version), so every TypedDict includes them.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PROPERTY_MANAGER = "PropertyManager"
    METER_TECH = "MeterTech"
    TENANT = "Tenant"
    AUDITOR = "Auditor"


class PropertyIntegrityStatus(str, Enum):
    OK = "OK"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class UtilityType(str, Enum):
    WATER = "WATER"
    ELECTRIC = "ELECTRIC"
    GAS = "GAS"


class AllocationMethod(str, Enum):
    CONSUMPTION = "CONSUMPTION"
    RUBS = "RUBS"


class UtilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class UnitStatus(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"
    ARCHIVED = "ARCHIVED"


class MeterStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    RETIRED = "RETIRED"


class LeaseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    NOTICE_GIVEN = "NOTICE_GIVEN"
    MOVED_OUT = "MOVED_OUT"
    CLOSED = "CLOSED"


class VendorBillStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPROVED = "APPROVED"
    ALLOCATED = "ALLOCATED"
    VOIDED = "VOIDED"


class MeterReadStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    FLAGGED = "FLAGGED"
    RE_READ_REQUESTED = "RE_READ_REQUESTED"
    SUPERSEDED = "SUPERSEDED"


class BillingCycleStatus(str, Enum):
    OPEN = "OPEN"
    READS_LOCKED = "READS_LOCKED"
    ALLOCATED = "ALLOCATED"
    STATEMENTS_ISSUED = "STATEMENTS_ISSUED"
    CLOSED = "CLOSED"


class DeliveryStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DELIVERED = "DELIVERED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"
    IN_COLLECTIONS = "IN_COLLECTIONS"


class DisputeReason(str, Enum):
    HIGH_READING = "HIGH_READING"
    WRONG_METER = "WRONG_METER"
    RATIO_ERROR = "RATIO_ERROR"
    DOUBLE_BILLED = "DOUBLE_BILLED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class PostedPaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class Property(TypedDict):
    id: str
    name: str
    state_code: str
    recovery_cap_pct: float
    common_area_pct: float
    current_period_label: Optional[str]
    integrity_status: str
    created_at: str
    updated_at: str
    version: int


class Utility(TypedDict):
    id: str
    property_id: str
    utility_type: str
    allocation_method: str
    unit_of_measure: str
    monthly_admin_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    property_id: str
    unit_number: str
    square_feet: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Meter(TypedDict):
    id: str
    property_id: str
    utility_id: str
    serial_number: str
    assigned_unit_id: Optional[str]
    assignment_effective_from: Optional[str]
    assignment_effective_to: Optional[str]
    last_validated_reading: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    unit_id: str
    property_id: str
    tenant_user_id: str
    occupant_count: int
    move_in_date: str
    notice_date: Optional[str]
    move_out_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorBill(TypedDict):
    id: str
    property_id: str
    utility_id: str
    period_label: str
    total_cost_cents: int
    common_area_cents: int
    cap_cents: int
    recoverable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MeterRead(TypedDict):
    id: str
    meter_id: str
    property_id: str
    period_label: str
    reading_value: float
    consumption: float
    re_read_count: int
    flag_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict):
    id: str
    property_id: str
    utility_id: str
    vendor_bill_id: str
    period_label: str
    period_start: str
    period_end: str
    allocated_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TenantStatement(TypedDict):
    id: str
    billing_cycle_id: str
    lease_id: str
    unit_id: str
    property_id: str
    utility_charge_cents: int
    admin_fee_cents: int
    late_fee_cents: int
    total_due_cents: int
    credit_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    due_date: Optional[str]
    delivery_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    statement_id: str
    property_id: str
    tenant_user_id: str
    reason: str
    requested_re_read: bool
    credit_amount_cents: int
    reopen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    statement_id: str
    property_id: str
    tenant_user_id: str
    amount_cents: int
    expected_statement_version: int
    status: str
    created_at: str
    updated_at: str
    version: int
