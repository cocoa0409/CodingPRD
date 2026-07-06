"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Charitable Gaming PRD (§2.4, §3). Every resource carries the
common system-managed fields id/created_at/updated_at/version.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (§2.1) ────────────────────────────────────────────────
class UserRole(str, Enum):
    REGULATOR = "Regulator"
    ORG_OFFICER = "OrgOfficer"
    SUPPLIER = "Supplier"


# ─── Status enums (§3) ───────────────────────────────────────────────
class LicenseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class OccasionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    REPORTED = "REPORTED"
    CANCELLED = "CANCELLED"


class SupplierStatus(str, Enum):
    PENDING = "PENDING"
    REGISTERED = "REGISTERED"


class EquipmentStatus(str, Enum):
    REGISTERED = "REGISTERED"
    RETIRED = "RETIRED"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class FinancialReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    WAIVED = "WAIVED"


class RenewalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class OrgEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


# ─── Entity TypedDicts (all carry common fields per §2.4) ────────────
class Organization(TypedDict):
    id: str
    legal_name: str
    ein: str
    nonprofit_type: str
    incorporation_date: str
    good_standing: bool
    state_code: str
    months_active: int
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    organization_id: str
    license_type: str
    contact_email: str
    venue_name: str
    status: str
    effective_date: Optional[str]
    expiration_date: Optional[str]
    annual_prize_limit_cents: int
    prize_committed_cents: int
    prize_settled_cents: int
    prize_allowance_remaining_cents: int
    total_violation_points_active: int
    created_at: str
    updated_at: str
    version: int


class Occasion(TypedDict):
    id: str
    license_id: str
    occasion_type: str
    scheduled_start: str
    scheduled_end: str
    venue_name: str
    planned_gross_cents: int
    planned_prize_pool_cents: int
    planned_expenses_cents: int
    gross_receipts_cents: Optional[int]
    prizes_paid_cents: Optional[int]
    expenses_cents: Optional[int]
    net_proceeds_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    business_name: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    supplier_id: str
    equipment_type: str
    serial_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentAllocation(TypedDict):
    id: str
    equipment_id: str
    occasion_id: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancialReport(TypedDict):
    id: str
    license_id: str
    period_start: str
    period_end: str
    charitable_use_cents: int
    status: str
    total_gross_cents: int
    total_prizes_cents: int
    total_expenses_cents: int
    net_proceeds_cents: int
    admin_allowance_cents: int
    regulatory_fee_cents: int
    charitable_minimum_cents: int
    charitable_use_ratio: float
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    license_id: str
    violation_type: str
    points: int
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Renewal(TypedDict):
    id: str
    license_id: str
    requested_term_months: int
    status: str
    created_at: str
    updated_at: str
    version: int
