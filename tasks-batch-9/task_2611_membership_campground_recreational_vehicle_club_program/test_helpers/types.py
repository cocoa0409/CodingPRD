"""Entity shapes, enum vocabularies and role names for the RV club program API.

Two resources are deliberately append-only and therefore carry only ``id`` and
``created_at``: ``AmenityInspection`` and ``SatisfactionSurvey`` have no
``updated_at`` and no ``version`` at all.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    """The five roles, spelled precisely as the contract requires."""

    MEMBER = "Member"
    PARK_MANAGER = "ParkManager"
    CLUB_ADMIN = "ClubAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRANSIENT_GUEST = "TransientGuest"


ALL_ROLES: List[str] = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TRANSFER_PENDING = "TRANSFER_PENDING"
    TERMINATED = "TERMINATED"


class DuesStatus(str, Enum):
    CURRENT = "CURRENT"
    GRACE = "GRACE"
    DELINQUENT = "DELINQUENT"
    WRITTEN_OFF = "WRITTEN_OFF"


class SuspensionReason(str, Enum):
    DUES_DELINQUENCY = "DUES_DELINQUENCY"
    OCCUPANCY_POLICY = "OCCUPANCY_POLICY"
    ADMIN_ACTION = "ADMIN_ACTION"


class ParkClass(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"


class NetworkType(str, Enum):
    CLUB_OWNED = "CLUB_OWNED"
    AFFILIATE = "AFFILIATE"


class ParkStatus(str, Enum):
    SEASONAL_CLOSED = "SEASONAL_CLOSED"
    OPEN = "OPEN"
    MAINTENANCE_HOLD = "MAINTENANCE_HOLD"


class AmenityComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    PROBATION = "PROBATION"
    NON_COMPLIANT = "NON_COMPLIANT"


class BookerType(str, Enum):
    MEMBER = "MEMBER"
    TRANSIENT = "TRANSIENT"


class ReservationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CHECKED_IN = "CHECKED_IN"
    EXTENSION_REVIEW = "EXTENSION_REVIEW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PoolCharged(str, Enum):
    NONE = "NONE"
    MEMBER_POOL = "MEMBER_POOL"
    BORROWED_TRANSIENT = "BORROWED_TRANSIENT"
    TRANSIENT_POOL = "TRANSIENT_POOL"


class CancellationReason(str, Enum):
    MEMBER_REQUEST = "MEMBER_REQUEST"
    MEMBERSHIP_SUSPENDED = "MEMBERSHIP_SUSPENDED"
    MAINTENANCE = "MAINTENANCE"
    SEASON_CLOSURE = "SEASON_CLOSURE"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class DuesInvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAST_DUE = "PAST_DUE"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class TransferType(str, Enum):
    GIFT = "GIFT"
    RESALE = "RESALE"
    ESTATE = "ESTATE"


class TransferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    PROBATION = "PROBATION"
    FAIL = "FAIL"


class ProjectCategory(str, Enum):
    SAFETY = "SAFETY"
    UTILITY = "UTILITY"
    AMENITY = "AMENITY"
    EXPANSION = "EXPANSION"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FUNDED = "FUNDED"
    DEFERRED = "DEFERRED"


class ExceptionReason(str, Enum):
    MEDICAL = "MEDICAL"
    EMPLOYMENT = "EMPLOYMENT"
    WEATHER = "WEATHER"
    RIG_REPAIR = "RIG_REPAIR"


class ExceptionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class MaintenanceWorkType(str, Enum):
    ROUTINE = "ROUTINE"
    CAPITAL = "CAPITAL"
    EMERGENCY = "EMERGENCY"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ExceptionDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class AuditedEntity(TypedDict, total=False):
    """Most resources carry id plus three audit columns."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyEntity(TypedDict, total=False):
    """Append-only resources carry only id and created_at."""

    id: str
    created_at: str


class MembershipTier(AuditedEntity, total=False):
    code: str
    name: str
    tier_rank: int
    upfront_cost_cents: int
    annual_dues_cents: int
    entitlement_nights_class_a: int
    entitlement_nights_class_b: int
    entitlement_nights_class_c: int
    annual_total_night_cap: int
    advance_window_days: int
    max_consecutive_stay_nights: int
    min_out_nights_between_stays: int
    affiliate_access_enabled: bool
    resale_allowed: bool
    transfer_fee_cents: int


class Member(AuditedEntity, total=False):
    full_name: str
    email: str
    home_region: Optional[str]
    status: str


class Membership(AuditedEntity, total=False):
    member_id: str
    tier_id: str
    transferred_from_membership_id: Optional[str]
    membership_status: str
    dues_status: str
    suspension_reason: Optional[str]
    purchased_at: str
    tenure_origin_at: str
    upfront_paid_cents: int
    entitlement_year_start: str
    nights_used_class_a: int
    nights_used_class_b: int
    nights_used_class_c: int
    annual_nights_used: int
    dues_balance_cents: int
    dues_paid_through: Optional[str]
    transfer_count: int
    resale_eligible_at: str
    tenure_years: int


class Park(AuditedEntity, total=False):
    name: str
    park_class: str
    affiliate_agreement_id: Optional[str]
    network_type: str
    total_sites: int
    member_allocation_pct: int
    member_pool_sites: int
    transient_pool_sites: int
    season_open_date: str
    season_close_date: str
    park_status: str
    amenity_compliance_status: str
    rating_score: float
    forced_cancellation_count: int
    funded_capital_cents_ytd: int
    last_inspection_at: Optional[str]


class Reservation(AuditedEntity, total=False):
    park_id: str
    membership_id: Optional[str]
    booker_type: str
    guest_name: Optional[str]
    arrival_date: str
    departure_date: str
    scheduled_departure_date: str
    nights: int
    status: str
    pool_charged: str
    entitlement_nights_charged: int
    affiliate_nights_charged: int
    total_charge_cents: int
    extension_count: int
    extension_denied_count: int
    cancellation_reason: Optional[str]
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    consecutive_run_nights: int


class AffiliateAgreement(AuditedEntity, total=False):
    partner_name: str
    status: str
    effective_from: str
    effective_to: str
    annual_member_night_quota: int
    reciprocity_ratio: float
    min_tier_rank: int
    advance_window_cap_days: int
    per_stay_night_cap: int
    settlement_rate_cents_per_night: int
    nights_consumed_ytd: int
    settlement_owed_cents: int


class DuesInvoice(AuditedEntity, total=False):
    membership_id: str
    cycle_year: int
    amount_cents: int
    base_dues_cents: int
    capital_assessment_cents: int
    loyalty_credit_cents: int
    late_fee_cents: int
    paid_amount_cents: int
    due_date: str
    paid_at: Optional[str]
    status: str
    days_past_due: int


class TransferRequest(AuditedEntity, total=False):
    membership_id: str
    from_member_id: str
    to_member_id: str
    transfer_type: str
    sale_price_cents: int
    status: str
    transfer_fee_cents: int
    successor_membership_id: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    rejection_reason: Optional[str]


class AmenityInspection(AppendOnlyEntity, total=False):
    park_id: str
    inspected_at: str
    inspector_user_id: str
    restroom_score: int
    hookup_score: int
    utility_score: int
    road_score: int
    composite_score: float
    result: str


class SatisfactionSurvey(AppendOnlyEntity, total=False):
    reservation_id: str
    park_id: str
    membership_id: str
    overall_rating: int
    cleanliness_rating: int
    staff_rating: int
    value_rating: int
    weighted_score: float
    submitted_at: str


class CapitalProject(AuditedEntity, total=False):
    park_id: str
    title: str
    category: str
    requested_cost_cents: int
    fiscal_year: int
    status: str
    priority_score: int
    funded_amount_cents: int
    requested_by_user_id: str
    decided_by_user_id: Optional[str]


class OccupancyException(AuditedEntity, total=False):
    reservation_id: str
    requested_run_nights: int
    tier_limit_nights: int
    reason: str
    status: str
    granted_run_nights: int
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]


class MaintenanceWindow(AuditedEntity, total=False):
    park_id: str
    start_date: str
    end_date: str
    work_type: str
    status: str
    cancelled_reservation_count: int


# Convenience aliases used by fixtures that return loose dicts.
JsonDict = Dict[str, Any]
