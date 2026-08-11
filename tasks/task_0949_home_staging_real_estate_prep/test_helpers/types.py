"""Domain types: entity status enums, pipeline enum and the role enum."""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STAGING_COORDINATOR = "StagingCoordinator"
    WAREHOUSE_MANAGER = "WarehouseManager"
    BILLING_CLERK = "BillingClerk"
    LISTING_AGENT = "ListingAgent"
    SELLER = "Seller"
    BROKERAGE_ADMIN = "BrokerageAdmin"
    VENDOR_REP = "VendorRep"


class Pipeline(str, Enum):
    OCCUPIED_PREP = "OCCUPIED_PREP"
    VACANT_STAGING = "VACANT_STAGING"


class ClientType(str, Enum):
    LISTING_AGENT = "LISTING_AGENT"
    SELLER = "SELLER"
    BROKERAGE_ADMIN = "BROKERAGE_ADMIN"


class Occupancy(str, Enum):
    OCCUPIED = "OCCUPIED"
    VACANT = "VACANT"


class PropertyPrepState(str, Enum):
    NEW = "NEW"
    CONSULT_BOOKED = "CONSULT_BOOKED"
    SCOPED = "SCOPED"
    IN_PREP = "IN_PREP"
    STAGED = "STAGED"
    DESTAGED = "DESTAGED"
    CLOSED = "CLOSED"


class ListingState(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    BACK_ON_MARKET = "BACK_ON_MARKET"
    CLOSED_SOLD = "CLOSED_SOLD"
    TERMINATED = "TERMINATED"


class ConsultationState(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    SCOPE_DRAFTED = "SCOPE_DRAFTED"
    SCOPE_SUBMITTED = "SCOPE_SUBMITTED"
    SCOPE_APPROVED = "SCOPE_APPROVED"
    SCOPE_REJECTED = "SCOPE_REJECTED"
    CANCELLED = "CANCELLED"


class ScopeAction(str, Enum):
    EDIT = "EDIT"
    DECLUTTER = "DECLUTTER"
    REFRESH = "REFRESH"
    PACKAGE_ROOM = "PACKAGE_ROOM"
    ACCESSORY_ONLY = "ACCESSORY_ONLY"


class ProjectWorkflowState(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    PULL_OPEN = "PULL_OPEN"
    INSTALL_SCHEDULED = "INSTALL_SCHEDULED"
    VISITS_OPEN = "VISITS_OPEN"
    STAGED = "STAGED"
    RESTAGE_REQUIRED = "RESTAGE_REQUIRED"
    DESTAGE_PENDING = "DESTAGE_PENDING"
    PICKED_UP = "PICKED_UP"
    CLOSEOUT = "CLOSEOUT"
    CLOSED = "CLOSED"


class ProjectPaymentState(str, Enum):
    UNBILLED = "UNBILLED"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    INVOICED = "INVOICED"
    DEFERRED = "DEFERRED"
    ESCALATED = "ESCALATED"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class PayerType(str, Enum):
    AGENT = "AGENT"
    SELLER = "SELLER"
    SPLIT = "SPLIT"
    BROKERAGE = "BROKERAGE"
    PAY_AT_CLOSING = "PAY_AT_CLOSING"


class ItemCategory(str, Enum):
    SOFA = "SOFA"
    BED = "BED"
    TABLE = "TABLE"
    CHAIR = "CHAIR"
    ART = "ART"
    RUG = "RUG"
    LAMP = "LAMP"
    ACCESSORY_SET = "ACCESSORY_SET"


class ItemStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    IN_REPAIR = "IN_REPAIR"
    WRITTEN_OFF = "WRITTEN_OFF"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PullState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class PullLineState(str, Enum):
    REQUESTED = "REQUESTED"
    ALLOCATED = "ALLOCATED"
    UNFILLED = "UNFILLED"
    DEPLOYED = "DEPLOYED"
    RETURNED = "RETURNED"
    SWAPPED = "SWAPPED"
    DROPPED = "DROPPED"


class PullLineSource(str, Enum):
    OWNED = "OWNED"
    VENDOR = "VENDOR"


class RentalOrderState(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"
    CANCELLED_LATE = "CANCELLED_LATE"


class InstallState(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    NO_ACCESS = "NO_ACCESS"
    CANCELLED = "CANCELLED"


class VisitState(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_ACCESS = "NO_ACCESS"
    CANCELLED = "CANCELLED"


class LeaseState(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    ENDING = "ENDING"
    HOLDOVER = "HOLDOVER"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class ExtensionState(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED_FULL = "APPROVED_FULL"
    APPROVED_PARTIAL = "APPROVED_PARTIAL"
    DENIED = "DENIED"
    APPLIED = "APPLIED"


class PickupState(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_ACCESS = "NO_ACCESS"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"


class AssessmentState(str, Enum):
    DRAFT = "DRAFT"
    ASSESSED = "ASSESSED"
    DISPUTED = "DISPUTED"
    UPHELD = "UPHELD"
    REVISED = "REVISED"
    FINAL = "FINAL"


class ConditionAtPickup(str, Enum):
    INTACT = "INTACT"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    MISSING = "MISSING"


class Disposition(str, Enum):
    NO_CHARGE = "NO_CHARGE"
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"


class ShootState(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    DELIVERED = "DELIVERED"
    RESHOOT_REQUESTED = "RESHOOT_REQUESTED"
    CANCELLED = "CANCELLED"


class InvoiceState(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DEFERRED_CLOSING = "DEFERRED_CLOSING"
    ESCALATED = "ESCALATED"
    PAID = "PAID"
    VOID = "VOID"


class DepositState(str, Enum):
    REQUIRED = "REQUIRED"
    HELD = "HELD"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    APPLIED = "APPLIED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


INVOICE_LINE_COMPONENTS = [
    "package",
    "room_overage",
    "accessory_overage",
    "labour",
    "travel",
    "lease",
    "extension",
    "holdover",
    "damage",
    "photo",
    "cancellation",
    "closing_escalation",
]


# Twenty-one of the twenty-two entity types carry updated_at and version.
class CommonRecord(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


# PackageTier is the single exception: id and created_at only.
class PackageTier(TypedDict):
    id: str
    created_at: str
    tier_code: str
    tier_rank: int
    room_cap: int
    included_accessory_sets: int
    included_photo_sessions: int
    base_price: float
    monthly_rent_rate: float


class Project(TypedDict):
    id: str
    property_id: str
    consultation_id: str
    listing_id: str
    package_tier_id: str
    payer_client_id: str
    brokerage_id: Optional[str]
    pipeline: str
    payer_type: str
    workflow_state: str
    payment_state: str
    room_count: int
    accessory_set_count: int
    contract_value: float
    created_at: str
    updated_at: str
    version: int
