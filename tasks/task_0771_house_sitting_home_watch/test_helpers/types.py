"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COORDINATOR = "Coordinator"
    CLIENT = "Client"
    SITTER = "Sitter"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"


class SitterStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BackgroundCheckStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class SitterBackgroundStatus(str, Enum):
    NONE = "NONE"
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class PolicyType(str, Enum):
    BOND = "BOND"
    LIABILITY = "LIABILITY"


class CoveragePolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXHAUSTED = "EXHAUSTED"


class SizeTier(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class ChecklistTask(str, Enum):
    MAIL = "MAIL"
    PLANTS = "PLANTS"
    SECURITY = "SECURITY"


class BillingTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class BookingType(str, Enum):
    RECURRING = "RECURRING"
    VACATION = "VACATION"


class Frequency(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"


class BookingStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ASSIGNMENT = "PENDING_ASSIGNMENT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FLAGGED = "FLAGGED"
    DONE = "DONE"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class VisitLogEntryType(str, Enum):
    PHOTO = "PHOTO"
    GPS_PING = "GPS_PING"
    NOTE = "NOTE"


class KeyAssignmentStatus(str, Enum):
    AT_OFFICE = "AT_OFFICE"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED = "RETURNED"
    LOST = "LOST"


class IncidentCategory(str, Enum):
    BREAK_IN = "BREAK_IN"
    WATER_LEAK = "WATER_LEAK"
    FIRE = "FIRE"
    MEDICAL = "MEDICAL"
    OTHER = "OTHER"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    EMERGENCY = "EMERGENCY"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Client(TypedDict):
    id: str
    full_name: str
    email: str
    billing_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    client_id: str
    label: str
    address: str
    size_tier: str
    has_pets: bool
    checklist_config: List[str]
    center_lat: float
    center_lng: float
    geofence_radius_m: int
    key_copies_total: int
    available_key_copies: int
    created_at: str
    updated_at: str
    version: int


class Sitter(TypedDict):
    id: str
    full_name: str
    email: str
    background_check_status: str
    missed_visit_count: int
    escalated_incident_count: int
    reliability_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict):
    id: str
    sitter_id: str
    provider_ref: str
    expires_at: str
    cleared_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CoveragePolicy(TypedDict):
    id: str
    sitter_id: str
    policy_type: str
    coverage_amount_cents: int
    effective_from: str
    expires_at: str
    reserved_exposure_cents: int
    paid_out_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    property_id: str
    client_id: str
    sitter_id: Optional[str]
    booking_type: str
    frequency: Optional[str]
    start_date: str
    end_date: str
    base_visit_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    booking_id: str
    sitter_id: str
    property_id: str
    scheduled_start: str
    scheduled_end: str
    check_in_at: Optional[str]
    check_out_at: Optional[str]
    completed_tasks: List[str]
    is_weekend: bool
    provisional_charge_cents: int
    final_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only evidence: ONLY id + created_at
class VisitLogEntry(TypedDict):
    id: str
    visit_id: str
    entry_type: str
    photo_url: Optional[str]
    gps_lat: float
    gps_lng: float
    captured_at: str
    created_at: str


class KeyAssignment(TypedDict):
    id: str
    property_id: str
    sitter_id: str
    booking_id: str
    checked_out_at: Optional[str]
    returned_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    visit_id: str
    booking_id: str
    reported_by_sitter_id: str
    category: str
    severity: str
    assessed_damage_cents: Optional[int]
    estimated_exposure_cents: int
    settled_payout_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    booking_id: str
    client_id: str
    billed_visit_count: int
    subtotal_cents: int
    discount_cents: int
    service_fee_cents: int
    tax_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
