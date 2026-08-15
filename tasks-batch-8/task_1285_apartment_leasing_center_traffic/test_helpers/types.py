"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROPERTY_MANAGER = "PropertyManager"
    LEASING_AGENT = "LeasingAgent"
    APPLICANT = "Applicant"


class ProrateMethod(str, Enum):
    CALENDAR = "CALENDAR"
    FIXED_30 = "FIXED_30"


class ConcessionType(str, Enum):
    NONE = "NONE"
    FLAT_AMOUNT = "FLAT_AMOUNT"
    PERCENT_OFF = "PERCENT_OFF"
    FREE_MONTHS = "FREE_MONTHS"


class PricingOfferStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"
    EXPIRED = "EXPIRED"


class InquirySource(str, Enum):
    WALK_IN = "WALK_IN"
    PHONE = "PHONE"
    WEB_FORM = "WEB_FORM"
    ILS_LISTING = "ILS_LISTING"
    REFERRAL = "REFERRAL"


class InquiryStatus(str, Enum):
    NEW = "NEW"
    CONTACTED = "CONTACTED"
    TOUR_SCHEDULED = "TOUR_SCHEDULED"
    CONVERTED = "CONVERTED"
    LOST = "LOST"


class TourType(str, Enum):
    GUIDED = "GUIDED"
    SELF_GUIDED = "SELF_GUIDED"


class TourStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class WaitlistEntryStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    CONVERTED = "CONVERTED"
    CANCELLED = "CANCELLED"


class Recommendation(str, Enum):
    APPROVE = "APPROVE"
    CONDITION = "CONDITION"
    DENY = "DENY"


class ApplicationDecision(str, Enum):
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    DENIED = "DENIED"


class ApplicationStatus(str, Enum):
    SCREENING = "SCREENING"
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    CONDITIONS_CLEARED = "CONDITIONS_CLEARED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    LEASED = "LEASED"


class LeaseStatus(str, Enum):
    ISSUED = "ISSUED"
    SIGNED_BY_APPLICANT = "SIGNED_BY_APPLICANT"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class MoveInStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Property(TypedDict, total=False):
    id: str
    name: str
    code: str
    response_time_target_minutes: int
    tour_buffer_minutes: int
    self_guided_window_minutes: int
    max_moveins_per_day: int
    utility_transfer_required: bool
    prorate_method: str
    required_addenda: List[str]
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    property_id: str
    max_concurrent_tours: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Floorplan(TypedDict, total=False):
    id: str
    property_id: str
    name: str
    bedrooms: int
    base_rent_cents: int
    total_units: int
    committed_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class PricingOffer(TypedDict, total=False):
    id: str
    property_id: str
    floorplan_id: str
    base_rent_cents: int
    concession_type: str
    concession_value: float
    lease_term_months: int
    effective_start: str
    expires_at: str
    effective_monthly_rent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inquiry(TypedDict, total=False):
    id: str
    property_id: str
    floorplan_id: Optional[str]
    contact_name: str
    contact_email: str
    source: str
    assigned_agent_id: Optional[str]
    first_responded_at: Optional[str]
    response_met_target: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class Tour(TypedDict, total=False):
    id: str
    inquiry_id: str
    agent_id: Optional[str]
    tour_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    floorplan_id: str
    contact_name: str
    contact_email: str
    position: int
    offer_expires_at: Optional[str]
    linked_application_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    inquiry_id: Optional[str]
    waitlist_entry_id: Optional[str]
    floorplan_id: str
    applicant_name: str
    applicant_email: str
    annual_income_cents: int
    credit_score: int
    monthly_rent_snapshot_cents: int
    recommendation: str
    required_deposit_cents: Optional[int]
    deposit_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    application_id: str
    floorplan_id: str
    monthly_rent_cents: int
    deposit_cents: int
    addenda_codes: List[str]
    signing_deadline: str
    signed_at: Optional[str]
    executed_at: Optional[str]
    superseded_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MoveIn(TypedDict, total=False):
    id: str
    lease_id: str
    scheduled_date: str
    utility_confirmed: bool
    prorated_rent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
