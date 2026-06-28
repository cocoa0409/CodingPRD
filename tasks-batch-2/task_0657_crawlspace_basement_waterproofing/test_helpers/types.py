"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────

class JobLifecycleStatus(str, Enum):
    LEAD = "LEAD"
    INSPECTED = "INSPECTED"
    QUOTED = "QUOTED"
    SOLD = "SOLD"
    SCHEDULED = "SCHEDULED"
    INSTALLED = "INSTALLED"
    WARRANTED = "WARRANTED"
    CLOSED = "CLOSED"
    LOST = "LOST"


class JobFinancingStatus(str, Enum):
    NONE = "NONE"
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CASH = "CASH"


class AssessmentSeverity(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class InspectionStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REVISED = "REVISED"
    EXPIRED = "EXPIRED"
    DECLINED = "DECLINED"


class FinancingApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class InstallOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CrewBookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class WarrantyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRANSFERRED = "TRANSFERRED"
    VOID = "VOID"
    LAPSED = "LAPSED"


class ServiceVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServiceVisitType(str, Enum):
    ANNUAL = "ANNUAL"
    CLAIM_REPAIR = "CLAIM_REPAIR"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"
    REOPENED = "REOPENED"


class ClaimCategory(str, Enum):
    WATER_INTRUSION = "WATER_INTRUSION"
    PUMP_FAILURE = "PUMP_FAILURE"
    STRUCTURAL = "STRUCTURAL"


class FoundationReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class StructureType(str, Enum):
    CRAWLSPACE = "CRAWLSPACE"
    BASEMENT = "BASEMENT"
    COMBINED = "COMBINED"


class CreditBand(str, Enum):
    PRIME = "PRIME"
    NEAR_PRIME = "NEAR_PRIME"
    SUBPRIME = "SUBPRIME"


class UserRole(str, Enum):
    HOMEOWNER = "Homeowner"
    ESTIMATOR = "Estimator"
    INSPECTOR = "Inspector"
    SCHEDULER = "Scheduler"
    WARRANTY_ADMIN = "WarrantyAdmin"
    FINANCE_PARTNER = "FinancePartner"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────

class Job(TypedDict):
    id: str
    homeowner_id: str
    property_address: str
    structure_type: str
    footprint_sqft: int
    lifecycle_status: str
    financing_status: str
    accepted_quote_id: Optional[str]
    install_order_id: Optional[str]
    assessment_severity: str
    open_claim_count: int
    created_at: str
    updated_at: str
    version: int


# Homeowner: common_fields false — only id + created_at (no updated_at, no version)
class Homeowner(TypedDict):
    id: str
    full_name: str
    email: str
    credit_band: str
    created_at: str


class Inspection(TypedDict):
    id: str
    job_id: str
    moisture_pct: float
    structural_findings_count: int
    standing_water: bool
    status: str
    severity: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    job_id: str
    revision: int
    includes_vapor_barrier: bool
    includes_sump: bool
    includes_dehumidifier: bool
    includes_drain: bool
    includes_battery_backup: bool
    drain_linear_ft: int
    discount_code: str
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int
    status: str
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict):
    id: str
    job_id: str
    quote_id: str
    term_months: int
    amount_financed_cents: int
    apr_bps: int
    monthly_payment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallOrder(TypedDict):
    id: str
    job_id: str
    quote_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    actual_drain_linear_ft: int
    final_total_cents: Optional[int]
    variance_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CrewBooking(TypedDict):
    id: str
    crew_id: str
    install_order_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    home_region: str
    daily_capacity: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Warranty(TypedDict):
    id: str
    job_id: str
    install_order_id: str
    holder_homeowner_id: str
    coverage_years: int
    status: str
    transfer_count: int
    next_service_due: Optional[str]
    last_service_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    warranty_id: str
    visit_type: str
    claim_id: Optional[str]
    scheduled_for: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    job_id: str
    warranty_id: str
    category: str
    description: str
    status: str
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class FoundationReferral(TypedDict):
    id: str
    job_id: str
    inspection_id: str
    partner_name: str
    status: str
    created_at: str
    updated_at: str
    version: int
