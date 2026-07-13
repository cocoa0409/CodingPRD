"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API carries the four common system fields (id, created_at,
updated_at, version), so every TypedDict lists them.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Status enums ---

class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    TURNOVER = "TURNOVER"


class MasterLeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class StayStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    COMPLETED_EARLY = "COMPLETED_EARLY"
    CANCELLED = "CANCELLED"


class HousekeepingVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VisitType(str, Enum):
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class DamageChargeStatus(str, Enum):
    ASSESSED = "ASSESSED"
    DISPUTED = "DISPUTED"
    CHARGED = "CHARGED"
    WAIVED = "WAIVED"


class InvoiceKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"


class TurnoverStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class UserRole(str, Enum):
    PROPERTY_MANAGER = "PropertyManager"
    CORPORATE_ADMIN = "CorporateAdmin"
    EMPLOYEE = "Employee"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version) ---

class CorporateAccount(TypedDict):
    id: str
    company_name: str
    billing_email: str
    created_at: str
    updated_at: str
    version: int


class RatePlan(TypedDict):
    id: str
    name: str
    monthly_rate_cents: int
    utility_monthly_cents: int
    cleaning_fee_cents: int
    occupancy_tax_rate_bps: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    name: str
    property_name: str
    bedrooms: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MasterLease(TypedDict):
    id: str
    corporate_account_id: str
    committed_units: int
    negotiated_monthly_rate_cents: int
    start_date: str
    end_date: str
    status: str
    units_consumed: int
    units_free: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    corporate_account_id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Stay(TypedDict):
    id: str
    unit_id: str
    rate_plan_id: str
    master_lease_id: Optional[str]
    employee_id: Optional[str]
    move_in: str
    planned_move_out: str
    actual_move_out: Optional[str]
    status: str
    planned_nights: int
    billable_nights: Optional[int]
    deposit_held_cents: int
    deposit_charged_cents: int
    deposit_refundable_cents: int
    created_at: str
    updated_at: str
    version: int


class HousekeepingVisit(TypedDict):
    id: str
    stay_id: str
    scheduled_date: str
    visit_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageCharge(TypedDict):
    id: str
    stay_id: str
    amount_cents: int
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    stay_id: str
    invoice_kind: str
    nights_billed: int
    rate_subtotal_cents: int
    cleaning_fee_cents: int
    occupancy_tax_cents: int
    amount_due_cents: int
    damage_total_cents: int
    total_settlement_cents: int
    deposit_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Turnover(TypedDict):
    id: str
    unit_id: str
    stay_id: str
    scheduled_date: str
    status: str
    created_at: str
    updated_at: str
    version: int
