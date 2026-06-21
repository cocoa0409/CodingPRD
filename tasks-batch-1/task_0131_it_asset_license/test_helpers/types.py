"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the IT Asset & License PRD. Entities carrying the common system
fields (id, created_at, updated_at, version) are modeled fully; ComplianceFinding
is the one immutable audit record that carries only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    ASSET_MANAGER = "AssetManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    EMPLOYEE = "Employee"


# ─── Status enums ─────────────────────────────────────
class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class VendorType(str, Enum):
    HARDWARE = "HARDWARE"
    SOFTWARE = "SOFTWARE"
    BOTH = "BOTH"


class LicenseModel(str, Enum):
    PER_SEAT = "PER_SEAT"
    PER_CORE = "PER_CORE"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    OVER_DEPLOYED = "OVER_DEPLOYED"
    UNDER_REVIEW = "UNDER_REVIEW"


class HardwareCategory(str, Enum):
    LAPTOP = "LAPTOP"
    DESKTOP = "DESKTOP"
    SERVER = "SERVER"
    MONITOR = "MONITOR"
    MOBILE = "MOBILE"


class HardwareStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ASSIGNED = "ASSIGNED"
    IN_REPAIR = "IN_REPAIR"
    RETIRED = "RETIRED"
    DISPOSED = "DISPOSED"


class SupportStatus(str, Enum):
    IN_WARRANTY = "IN_WARRANTY"
    LEASED = "LEASED"
    OUT_OF_WARRANTY = "OUT_OF_WARRANTY"
    UNCOVERED = "UNCOVERED"


class CoverageType(str, Enum):
    WARRANTY = "WARRANTY"
    LEASE = "LEASE"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RENEWED = "RENEWED"
    CANCELLED = "CANCELLED"


class EntitlementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    RENEWED = "RENEWED"


class InstallStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    UNINSTALLED = "UNINSTALLED"
    REJECTED = "REJECTED"


class CheckoutStatus(str, Enum):
    OPEN = "OPEN"
    RETURNED = "RETURNED"
    LOST = "LOST"


class DisposalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    REVERSED = "REVERSED"


class DisposalReason(str, Enum):
    END_OF_LIFE = "END_OF_LIFE"
    DAMAGED = "DAMAGED"
    LOST = "LOST"
    SOLD = "SOLD"


class RenewalTargetType(str, Enum):
    ENTITLEMENT = "ENTITLEMENT"
    COVERAGE = "COVERAGE"


class RenewalStatus(str, Enum):
    QUOTED = "QUOTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TrueUpVariant(str, Enum):
    LIVE = "LIVE"
    AUDIT = "AUDIT"


class TrueUpVerdict(str, Enum):
    COMPLIANT = "COMPLIANT"
    OVER_DEPLOYED = "OVER_DEPLOYED"


class TrueUpStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class FindingType(str, Enum):
    OVER_DEPLOYED = "OVER_DEPLOYED"
    EXPIRED_IN_GRACE = "EXPIRED_IN_GRACE"
    NEGATIVE_AVAILABLE = "NEGATIVE_AVAILABLE"


# ─── Entity TypedDicts (common_fields: true) ──────────
class Vendor(TypedDict):
    id: str
    name: str
    vendor_type: str
    support_email: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    full_name: str
    email: str
    department: str
    max_assigned_assets: int
    status: str
    open_checkout_count: int
    created_at: str
    updated_at: str
    version: int


class SoftwareProduct(TypedDict):
    id: str
    vendor_id: str
    name: str
    license_model: str
    core_factor: float
    min_core_units: int
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class HardwareAsset(TypedDict):
    id: str
    vendor_id: str
    asset_tag: str
    category: str
    physical_cores: int
    purchase_cost_cents: int
    in_service_date: str
    useful_life_months: int
    salvage_value_cents: int
    status: str
    support_status: str
    accumulated_depreciation_cents: int
    net_book_value_cents: int
    disposal_proceeds_cents: int
    disposal_gain_loss_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyLease(TypedDict):
    id: str
    hardware_asset_id: str
    vendor_id: str
    coverage_type: str
    coverage_start: str
    coverage_end: str
    monthly_cost_cents: int
    auto_renew: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseEntitlement(TypedDict):
    id: str
    software_product_id: str
    vendor_id: str
    entitled_units: int
    unit_price_cents: int
    term_start: str
    term_end: str
    grace_days: int
    status: str
    consumed_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class InstallationRecord(TypedDict):
    id: str
    software_product_id: str
    hardware_asset_id: str
    license_entitlement_id: str
    required_core_units: int
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssignmentCheckout(TypedDict):
    id: str
    hardware_asset_id: str
    employee_id: str
    checkout_at: str
    expected_return_at: str
    returned_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisposalRequest(TypedDict):
    id: str
    hardware_asset_id: str
    submitted_by_user_id: str
    reason: str
    proposed_proceeds_cents: int
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalOrder(TypedDict):
    id: str
    target_type: str
    license_entitlement_id: Optional[str]
    warranty_lease_id: Optional[str]
    extend_months: int
    added_units: int
    quoted_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrueUpReconciliation(TypedDict):
    id: str
    software_product_id: str
    variant: str
    as_of: str
    total_entitled_units: int
    total_consumed_units: int
    position_units: int
    verdict: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Entity TypedDict (common_fields: false) ──────────
# ComplianceFinding is an immutable audit record: id + created_at only,
# NO updated_at and NO version.
class ComplianceFinding(TypedDict):
    id: str
    true_up_reconciliation_id: str
    software_product_id: str
    finding_type: str
    detail: str
    shortfall_units: int
    created_at: str
