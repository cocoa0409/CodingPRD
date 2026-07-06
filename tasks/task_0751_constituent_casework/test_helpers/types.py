"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    OFFICE_ADMIN = "OfficeAdmin"
    CASEWORKER = "Caseworker"
    CONSTITUENT = "Constituent"
    ANONYMOUS = "Anonymous"


class Chamber(str, Enum):
    HOUSE = "HOUSE"
    SENATE = "SENATE"


class Category(str, Enum):
    IMMIGRATION = "IMMIGRATION"
    HEALTHCARE = "HEALTHCARE"
    HOUSING = "HOUSING"
    TAX = "TAX"
    BENEFITS = "BENEFITS"
    OTHER = "OTHER"


class Priority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class ConstituentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PURGED = "PURGED"


class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CaseStatus(str, Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_CONSTITUENT = "AWAITING_CONSTITUENT"
    AWAITING_AGENCY = "AWAITING_AGENCY"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class ReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    RECALLED = "RECALLED"
    CLOSED = "CLOSED"


class AgencyOutcome(str, Enum):
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class EventLifecycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class EventRegistrationStatus(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    FULL = "FULL"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (all ten entities carry id/created_at/updated_at/version) ---

class Representative(TypedDict):
    id: str
    full_name: str
    chamber: str
    district_name: str
    state_code: str
    office_email: str
    created_at: str
    updated_at: str
    version: int


class Constituent(TypedDict):
    id: str
    representative_id: str
    full_name: str
    email: str
    address: str
    phone: Optional[str]
    contact_consent: bool
    data_sharing_consent: bool
    status: str
    upcoming_event_count: int
    created_at: str
    updated_at: str
    version: int


class Agency(TypedDict):
    id: str
    name: str
    jurisdiction: str
    status: str
    open_referral_count: int
    created_at: str
    updated_at: str
    version: int


class ResponseTemplate(TypedDict):
    id: str
    category: str
    body_template: str
    response_window_hours: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    constituent_id: str
    representative_id: str
    subject: str
    description: str
    category: str
    priority: str
    status: str
    assigned_template_id: Optional[str]
    assignee_staff_id: Optional[str]
    response_window_hours: Optional[int]
    effective_window_hours: Optional[float]
    provisional_due_at: str
    final_due_at: Optional[str]
    cumulative_paused_hours: float
    paused_since: Optional[str]
    gross_elapsed_hours: float
    net_elapsed_hours: float
    breached: bool
    last_agency_outcome: Optional[str]
    reject_count: int
    triaged_at: Optional[str]
    resolved_at: Optional[str]
    closed_at: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgencyReferral(TypedDict):
    id: str
    case_id: str
    agency_id: str
    referral_notes: Optional[str]
    status: str
    response_summary: Optional[str]
    sent_at: Optional[str]
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    name: str
    capacity: int
    address: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    representative_id: str
    venue_id: str
    title: str
    start_at: str
    end_at: str
    capacity: int
    lifecycle_status: str
    registration_status: str
    registered_count: int
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict):
    id: str
    event_id: str
    constituent_id: str
    status: str
    registered_at: str
    created_at: str
    updated_at: str
    version: int


class NewsletterCampaign(TypedDict):
    id: str
    representative_id: str
    subject: str
    body: str
    page_count: int
    status: str
    recipient_count: int
    send_cost_cents: int
    created_at: str
    updated_at: str
    version: int
