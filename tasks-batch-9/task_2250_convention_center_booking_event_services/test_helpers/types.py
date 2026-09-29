"""Domain types for the Convention Center Booking & Event Services API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    LICENSEE = "Licensee"
    SALES_MANAGER = "SalesManager"
    EVENT_SERVICES_MANAGER = "EventServicesManager"
    SETTLEMENT_ANALYST = "SettlementAnalyst"
    FACILITIES_PLANNER = "FacilitiesPlanner"
    VENUE_ADMIN = "VenueAdmin"


# --------------------------------------------------------------------------
# Enumerated domain vocabularies
# --------------------------------------------------------------------------


class OrganizationType(str, Enum):
    NATIONAL_ASSOCIATION = "NATIONAL_ASSOCIATION"
    LOCAL_ORGANIZATION = "LOCAL_ORGANIZATION"
    PROMOTER = "PROMOTER"


class BookingStanding(str, Enum):
    GOOD = "GOOD"
    HOLD_RESTRICTED = "HOLD_RESTRICTED"


class SpaceClass(str, Enum):
    HALL = "HALL"
    BALLROOM = "BALLROOM"
    MEETING_ROOM = "MEETING_ROOM"


class EventClass(str, Enum):
    CITYWIDE_CONVENTION = "CITYWIDE_CONVENTION"
    LOCAL_EVENT = "LOCAL_EVENT"
    CONSUMER_SHOW = "CONSUMER_SHOW"


class EventBookingStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    DEFINITE = "DEFINITE"
    IN_HOUSE = "IN_HOUSE"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class OrderPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    LOCKED = "LOCKED"


class SpaceHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CHALLENGED = "CHALLENGED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class LicenseAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    EXECUTED = "EXECUTED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    VOIDED = "VOIDED"
    TERMINATED = "TERMINATED"


class ServiceCategory(str, Enum):
    UTILITIES = "UTILITIES"
    RIGGING = "RIGGING"
    CLEANING = "CLEANING"
    SECURITY = "SECURITY"
    CATERING = "CATERING"


class VendorTier(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    PREFERRED = "PREFERRED"
    OPEN = "OPEN"


class CoveredCategory(str, Enum):
    UTILITIES = "UTILITIES"
    RIGGING = "RIGGING"
    CLEANING = "CLEANING"
    SECURITY = "SECURITY"


class OrderTiming(str, Enum):
    ADVANCE = "ADVANCE"
    LATE = "LATE"


class ServiceOrderApprovalStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ServiceOrderBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    ESTIMATED = "ESTIMATED"
    RECONCILED = "RECONCILED"
    VOID = "VOID"


class LaborCallStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    ACTUALIZED = "ACTUALIZED"
    CANCELLED = "CANCELLED"


class ArrangementType(str, Enum):
    IN_HOUSE = "IN_HOUSE"
    OUTSIDE_EXCEPTION = "OUTSIDE_EXCEPTION"


class ExceptionReason(str, Enum):
    ETHNIC_CUISINE = "ETHNIC_CUISINE"
    SPONSOR_PRODUCT_SAMPLING = "SPONSOR_PRODUCT_SAMPLING"
    RELIGIOUS_DIETARY = "RELIGIOUS_DIETARY"


class CateringArrangementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class UsageKind(str, Enum):
    MOVE_IN = "MOVE_IN"
    SHOW = "SHOW"
    DARK = "DARK"
    MOVE_OUT = "MOVE_OUT"
    HOLDOVER = "HOLDOVER"


class SettlementBasis(str, Enum):
    CONTRACTED = "CONTRACTED"
    ACTUAL_USAGE = "ACTUAL_USAGE"


class EventSettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    ARBITRATION = "ARBITRATION"
    FINAL = "FINAL"


class LineKind(str, Enum):
    RENTAL = "RENTAL"
    SERVICE = "SERVICE"
    LABOR = "LABOR"
    CATERING = "CATERING"
    ADJUSTMENT = "ADJUSTMENT"


class ProjectKind(str, Enum):
    ROUTINE_MAINTENANCE = "ROUTINE_MAINTENANCE"
    CAPITAL_PROJECT = "CAPITAL_PROJECT"


class MaintenanceBlackoutStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DEFERRED = "DEFERRED"


# --------------------------------------------------------------------------
# Entities carrying the four common properties (PRD §2.4)
# --------------------------------------------------------------------------


class Client(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    organization_type: str
    total_deposits_paid_cents: int
    credit_balance_cents: int
    outstanding_balance_cents: int
    booking_standing: str
    created_at: str
    updated_at: str
    version: int


class SpaceUnit(TypedDict):
    id: str
    name: str
    parent_space_id: Optional[str]
    space_class: str
    rentable_sqft: int
    daily_base_rate_cents: int
    rigging_capable: bool
    committed_space_days: int
    active_blackout_count: int
    created_at: str
    updated_at: str
    version: int


class BookingPolicyWindow(TypedDict):
    id: str
    event_class: str
    priority_rank: int
    open_months_before: int
    close_months_before: int
    max_holds_per_booking: int
    challenge_response_hours: int
    rental_discount_pct: float
    max_challenge_rounds: int
    created_at: str
    updated_at: str
    version: int


class EventBooking(TypedDict):
    id: str
    client_id: str
    space_id: str
    policy_window_id: str
    event_name: str
    event_class: str
    move_in_start_date: str
    show_start_date: str
    show_end_date: str
    move_out_end_date: str
    projected_room_nights: int
    status: str
    order_posture: str
    gross_rental_cents: int
    contracted_rental_cents: int
    deposit_required_cents: int
    space_days_committed: int
    hold_count: int
    created_at: str
    updated_at: str
    version: int


class SpaceHold(TypedDict):
    id: str
    booking_id: str
    challenged_by_hold_id: Optional[str]
    hold_rank: int
    status: str
    challenge_round: int
    challenge_deadline_utc: Optional[str]
    release_deadline_utc: Optional[str]
    interval_start_date: str
    interval_end_date: str
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict):
    id: str
    booking_id: str
    status: str
    rental_rate_cents: int
    contracted_rental_cents: int
    deposit_required_cents: int
    deposit_held_cents: int
    amendment_round: int
    pending_amendment_note: Optional[str]
    issued_at_utc: Optional[str]
    executed_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    legal_name: str
    service_category: str
    vendor_tier: str
    coi_expiry_date: str
    is_in_house_caterer: bool
    created_at: str
    updated_at: str
    version: int


class UnionJurisdiction(TypedDict):
    id: str
    craft_name: str
    covered_category: str
    straight_time_rate_cents: int
    overtime_multiplier: float
    min_call_hours: float
    st_window_start_hour: int
    st_window_end_hour: int
    max_crew_hours_per_day: float
    committed_crew_hours: float
    lockout_active: bool
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    booking_id: str
    vendor_id: str
    service_category: str
    ordered_quantity: float
    order_timing: str
    approval_status: str
    billing_status: str
    estimated_charge_cents: int
    actual_quantity: Optional[float]
    actual_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LaborCall(TypedDict):
    id: str
    booking_id: str
    jurisdiction_id: str
    work_category: str
    work_date: str
    scheduled_start_hour: float
    scheduled_end_hour: float
    crew_size: int
    actual_start_hour: Optional[float]
    actual_end_hour: Optional[float]
    status: str
    billed_hours: float
    estimated_charge_cents: int
    actual_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CateringArrangement(TypedDict):
    id: str
    booking_id: str
    vendor_id: str
    arrangement_type: str
    exception_reason: Optional[str]
    estimated_fnb_cents: int
    actual_fnb_cents: Optional[int]
    buyout_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventSettlement(TypedDict):
    id: str
    booking_id: str
    basis: str
    status: str
    line_subtotal_cents: int
    facility_service_fee_cents: int
    deposit_applied_cents: int
    grand_total_cents: int
    revision_round: int
    dispute_reason: Optional[str]
    issued_by_user_id: Optional[str]
    issued_at_utc: Optional[str]
    dispute_deadline_utc: Optional[str]
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceBlackout(TypedDict):
    id: str
    space_id: str
    window_start_date: str
    window_end_date: str
    buffer_days: int
    project_kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only immutable records: only id + created_at (PRD §2.4)
# --------------------------------------------------------------------------


class SpaceUsageRecord(TypedDict):
    id: str
    booking_id: str
    usage_date: str
    usage_kind: str
    recorded_by_user_id: str
    created_at: str


class SettlementLineItem(TypedDict):
    id: str
    settlement_id: str
    line_kind: str
    source_ref_id: Optional[str]
    amount_cents: int
    memo: Optional[str]
    created_at: str


APPEND_ONLY_ENTITY_NAMES: List[str] = ["SpaceUsageRecord", "SettlementLineItem"]
