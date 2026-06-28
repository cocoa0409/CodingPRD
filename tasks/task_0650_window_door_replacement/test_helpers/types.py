"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry id, created_at, updated_at, and version
(the PRD states there are no immutable-after-creation entities).
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    HOMEOWNER = "Homeowner"
    SALES_CONSULTANT = "SalesConsultant"
    OPERATIONS_COORDINATOR = "OperationsCoordinator"
    SERVICE_TECH = "ServiceTech"
    PLATFORM_ADMIN = "PlatformAdmin"


class AgiBand(str, Enum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class JurisdictionCode(str, Enum):
    WEST_STRICT = "WEST_STRICT"
    NORTHEAST_STD = "NORTHEAST_STD"
    CENTRAL_LIGHT = "CENTRAL_LIGHT"


class ProjectStatus(str, Enum):
    LEAD = "LEAD"
    CONSULTING = "CONSULTING"
    QUOTING = "QUOTING"
    CONTRACTED = "CONTRACTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    INSTALLING = "INSTALLING"
    INSPECTION = "INSPECTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ConsultationStatus(str, Enum):
    BOOKED = "BOOKED"
    MEASURED = "MEASURED"
    CANCELLED = "CANCELLED"


class ProductType(str, Enum):
    DOUBLE_HUNG = "DOUBLE_HUNG"
    CASEMENT = "CASEMENT"
    PICTURE = "PICTURE"
    SLIDING_PATIO_DOOR = "SLIDING_PATIO_DOOR"
    ENTRY_DOOR = "ENTRY_DOOR"


class GlassPackage(str, Enum):
    STANDARD = "STANDARD"
    LOWE_DUAL = "LOWE_DUAL"
    LOWE_TRIPLE = "LOWE_TRIPLE"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class DiscountTier(str, Enum):
    NONE = "NONE"
    TIER1 = "TIER1"
    TIER2 = "TIER2"


class FinancingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class ManufactureStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_BUILD = "IN_BUILD"
    READY = "READY"
    CANCELLED = "CANCELLED"


class InstallJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PermitStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    INSPECTION_PASSED = "INSPECTION_PASSED"
    INSPECTION_FAILED = "INSPECTION_FAILED"


class ServiceTicketStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class ServiceCategory(str, Enum):
    WARRANTY = "WARRANTY"
    BILLABLE = "BILLABLE"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    VOID = "VOID"


# --- Entity TypedDicts (all carry the common fields) ---

class Homeowner(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    email: str
    property_zip: str
    agi_band: str
    referral_credit_cents: int


class Project(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    homeowner_id: str
    jurisdiction_code: str
    status: str
    accepted_quote_id: Optional[str]


class Consultation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    consultant_id: str
    scheduled_at: str
    status: str
    total_opening_count: int


class Opening(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    consultation_id: str
    product_type: str
    width_in: float
    height_in: float
    glass_package: str
    u_factor: float
    energy_qualified: bool
    unit_price_cents: int


class Quote(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    consultation_id: str
    status: str
    discount_tier: str
    openings_subtotal_cents: int
    estimate_total_cents: int
    provisional_rebate_cents: int
    expires_at: Optional[str]


class FinancingApplication(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    quote_id: str
    requested_amount_cents: int
    term_months: int
    status: str
    approved_apr_bps: Optional[int]
    monthly_payment_cents: Optional[int]


class ManufactureOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    quote_id: str
    status: str
    lead_time_days: int
    ready_at: str


class Crew(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    home_jurisdiction: str
    daily_capacity_openings: int


class InstallJob(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    crew_id: str
    window_start: str
    window_end: str
    opening_count: int
    status: str


class Permit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    status: str
    inspection_due_at: Optional[str]


class ServiceTicket(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    opening_id: str
    category: str
    status: str
    charge_cents: int


class Referral(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    referrer_project_id: str
    referred_project_id: str
    status: str
    reward_amount_cents: int
