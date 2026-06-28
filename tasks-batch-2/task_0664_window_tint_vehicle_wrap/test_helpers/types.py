"""Domain types: entity TypedDicts, status enums, role enum.

Field names and enum values mirror the PRD contract exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    INSTALLER = "Installer"
    CUSTOMER = "Customer"
    FLEET_MANAGER = "FleetManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --- Status enums ---
class ShopLocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FilmMaterialCategory(str, Enum):
    TINT_FILM = "TINT_FILM"
    PPF_FILM = "PPF_FILM"
    WRAP_VINYL = "WRAP_VINYL"
    CERAMIC_COATING = "CERAMIC_COATING"


class FilmMaterialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ServiceType(str, Enum):
    TINT = "TINT"
    PPF = "PPF"
    WRAP = "WRAP"
    CERAMIC = "CERAMIC"


class SizeClass(str, Enum):
    SEDAN = "SEDAN"
    SUV = "SUV"
    TRUCK = "TRUCK"


class FleetAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    ACCEPTED = "ACCEPTED"
    CONVERTED = "CONVERTED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class Coverage(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    ACCENT = "ACCENT"


class WindowPosition(str, Enum):
    FRONT_SIDE = "FRONT_SIDE"
    REAR_SIDE = "REAR_SIDE"
    REAR_WINDOW = "REAR_WINDOW"
    WINDSHIELD = "WINDSHIELD"
    BODY_PANEL = "BODY_PANEL"


class QuoteLineStatus(str, Enum):
    INCLUDED = "INCLUDED"
    REMOVED = "REMOVED"


class MedicalExemptionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class BayStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class InstallerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF_DUTY = "OFF_DUTY"


class InstallStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CURING = "CURING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    DEPOSIT_DUE = "DEPOSIT_DUE"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class WrapProofStatus(str, Enum):
    PROOF_SUBMITTED = "PROOF_SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CallbackReason(str, Enum):
    BUBBLING = "BUBBLING"
    PEELING = "PEELING"
    COLOR_MISMATCH = "COLOR_MISMATCH"
    MEASUREMENT_ERROR = "MEASUREMENT_ERROR"


class CallbackOutcome(str, Enum):
    REDO = "REDO"
    DENIED = "DENIED"


class CallbackStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


# --- Entity TypedDicts ---
# Full first-class entities carry id, created_at, updated_at, version (PRD §2.4).
class ShopLocation(TypedDict):
    id: str
    name: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


# StateTintRegulation is the one reference record carrying ONLY id + created_at
# (PRD §2.4): no updated_at, no version.
class StateTintRegulation(TypedDict):
    id: str
    state_code: str
    front_side_min_vlt_pct: int
    windshield_strip_max_inches: float
    medical_exemption_allowed: bool
    created_at: str


class FilmMaterial(TypedDict):
    id: str
    sku: str
    category: str
    cure_hours: int
    price_multiplier_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServicePackage(TypedDict):
    id: str
    name: str
    service_type: str
    base_rate_cents: int
    duration_minutes: int
    cure_buffer_minutes: int
    warranty_days: int
    requires_proof: bool
    created_at: str
    updated_at: str
    version: int


class VehicleProfile(TypedDict):
    id: str
    customer_user_id: str
    vin: str
    size_class: str
    size_surcharge_cents: int
    created_at: str
    updated_at: str
    version: int


class FleetAccount(TypedDict):
    id: str
    company_name: str
    fleet_manager_user_id: str
    discount_bps: int
    credit_limit_cents: int
    held_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    vehicle_profile_id: str
    shop_location_id: str
    fleet_account_id: Optional[str]
    rushed: bool
    status: str
    subtotal_cents: int
    discount_cents: int
    net_cents: int
    rush_fee_cents: int
    total_due_cents: int
    deposit_required_cents: int
    created_at: str
    updated_at: str
    version: int


class QuoteLine(TypedDict):
    id: str
    quote_id: str
    service_package_id: str
    film_material_id: str
    coverage: str
    window_position: str
    requested_vlt_pct: int
    strip_depth_inches: float
    status: str
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class MedicalExemption(TypedDict):
    id: str
    vehicle_profile_id: str
    certificate_ref: str
    exempt_min_vlt_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bay(TypedDict):
    id: str
    shop_location_id: str
    label: str
    reserved_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Installer(TypedDict):
    id: str
    shop_location_id: str
    installer_user_id: str
    full_name: str
    certified_service_types: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    quote_id: str
    bay_id: str
    installer_id: str
    fleet_account_id: Optional[str]
    primary_service_type: str
    scheduled_start: str
    duration_minutes: int
    cure_buffer_minutes: int
    total_due_cents: int
    install_status: str
    payment_status: str
    actual_started_at: Optional[str]
    actual_completed_at: Optional[str]
    cure_complete_at: Optional[str]
    warranty_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WrapProof(TypedDict):
    id: str
    work_order_id: str
    design_ref: str
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CallbackTicket(TypedDict):
    id: str
    work_order_id: str
    reason: str
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
