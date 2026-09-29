"""Typed shapes for every resource the RV share marketplace API returns.

Four record types are append-only evidence and therefore carry only ``id`` and
``created_at`` — no ``updated_at`` and no ``version``. Those four
(:class:`RenterQualification`, :class:`MeterReading`, :class:`TripPhoto`,
:class:`LedgerEntry`) deliberately omit the mutable-state bookkeeping fields.
"""

from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class Role:
    OWNER = "Owner"
    RENTER = "Renter"
    PLATFORM_ADMIN = "PlatformAdmin"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


ALL_ROLES = (Role.OWNER, Role.RENTER, Role.PLATFORM_ADMIN, Role.CLAIMS_ADJUSTER)


# ---------------------------------------------------------------------------
# Status vocabularies
# ---------------------------------------------------------------------------
class OwnerStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DrivingRecordStatus:
    NONE = "NONE"
    CLEAR = "CLEAR"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    EXPIRED = "EXPIRED"


class TowingTier:
    NONE = "NONE"
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"


class VehicleClass:
    CLASS_A = "CLASS_A"
    CLASS_C = "CLASS_C"
    CAMPER_VAN = "CAMPER_VAN"
    TRAVEL_TRAILER = "TRAVEL_TRAILER"
    FIFTH_WHEEL = "FIFTH_WHEEL"


class ListingStatus:
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    LISTED = "LISTED"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class InsuranceStatus:
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class DocType:
    TITLE = "TITLE"
    REGISTRATION = "REGISTRATION"
    INSURANCE_POLICY = "INSURANCE_POLICY"
    INSPECTION_PHOTO = "INSPECTION_PHOTO"


class Zone:
    EXTERIOR_FRONT = "EXTERIOR_FRONT"
    EXTERIOR_REAR = "EXTERIOR_REAR"
    INTERIOR = "INTERIOR"
    ROOF = "ROOF"
    UNDERCARRIAGE = "UNDERCARRIAGE"


class DocVerificationStatus:
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"


class CheckType:
    DRIVING_RECORD = "DRIVING_RECORD"
    TOWING_EXPERIENCE = "TOWING_EXPERIENCE"


class QualificationResult:
    CLEAR = "CLEAR"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    VERIFIED_BASIC = "VERIFIED_BASIC"
    VERIFIED_ADVANCED = "VERIFIED_ADVANCED"
    UNVERIFIED = "UNVERIFIED"


class PlanTier:
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class PolicyTier:
    FLEXIBLE = "FLEXIBLE"
    MODERATE = "MODERATE"
    STRICT = "STRICT"


class SeasonCode:
    PEAK = "PEAK"
    SHOULDER = "SHOULDER"
    OFF = "OFF"


class CampgroundStatus:
    ACCEPTING = "ACCEPTING"
    CLOSED = "CLOSED"


class DeliveryOption:
    PICKUP = "PICKUP"
    CAMPGROUND_DROPOFF = "CAMPGROUND_DROPOFF"


class TripStatus:
    REQUESTED = "REQUESTED"
    OWNER_APPROVED = "OWNER_APPROVED"
    CONFIRMED = "CONFIRMED"
    IN_TRIP = "IN_TRIP"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    CANCELLED_BY_RENTER = "CANCELLED_BY_RENTER"
    CANCELLED_BY_OWNER = "CANCELLED_BY_OWNER"
    CANCELLED_BY_PLATFORM = "CANCELLED_BY_PLATFORM"


class SettlementStatus:
    NONE = "NONE"
    HELD = "HELD"
    RECONCILING = "RECONCILING"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class LoyaltyTier:
    NONE = "NONE"
    TIER_1 = "LOYALTY_TIER_1"
    TIER_2 = "LOYALTY_TIER_2"


class AssignmentStatus:
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    WAITLISTED = "WAITLISTED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class ReadingType:
    PRE_TRIP = "PRE_TRIP"
    MID_TRIP = "MID_TRIP"
    POST_TRIP = "POST_TRIP"


class PhotoPhase:
    PRE_TRIP = "PRE_TRIP"
    POST_TRIP = "POST_TRIP"


class CauseCode:
    COLLISION = "COLLISION"
    THEFT = "THEFT"
    WATER_INTRUSION = "WATER_INTRUSION"
    TIRE_BLOWOUT = "TIRE_BLOWOUT"
    AWNING_WIND = "AWNING_WIND"
    INTERIOR_STAIN = "INTERIOR_STAIN"
    APPLIANCE_FAILURE = "APPLIANCE_FAILURE"


class ClaimStatus:
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ComparisonVerdict:
    PRE_EXISTING = "PRE_EXISTING"
    NEW_DAMAGE = "NEW_DAMAGE"
    NO_VISIBLE_CHANGE = "NO_VISIBLE_CHANGE"


class LedgerParty:
    RENTER = "RENTER"
    OWNER = "OWNER"
    PLATFORM = "PLATFORM"


class LedgerEntryType:
    TRIP_CHARGE = "TRIP_CHARGE"
    OWNER_PAYOUT = "OWNER_PAYOUT"
    SERVICE_FEE = "SERVICE_FEE"
    PROTECTION_PREMIUM = "PROTECTION_PREMIUM"
    OWNER_CANCEL_FEE = "OWNER_CANCEL_FEE"
    DAMAGE_RENTER_CHARGE = "DAMAGE_RENTER_CHARGE"
    DAMAGE_OWNER_CREDIT = "DAMAGE_OWNER_CREDIT"
    DAMAGE_PLAN_PAYMENT = "DAMAGE_PLAN_PAYMENT"
    TRIP_CHARGE_REVERSAL = "TRIP_CHARGE_REVERSAL"
    OWNER_PAYOUT_REVERSAL = "OWNER_PAYOUT_REVERSAL"
    SERVICE_FEE_REVERSAL = "SERVICE_FEE_REVERSAL"
    PROTECTION_PREMIUM_REVERSAL = "PROTECTION_PREMIUM_REVERSAL"


# ---------------------------------------------------------------------------
# Mutable resources: id / created_at / updated_at / version
# ---------------------------------------------------------------------------
class MutableResource(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Owner(MutableResource):
    display_name: str
    email: str
    payout_state_code: str
    status: str
    owner_penalty_points: int
    payout_balance_cents: int
    listed_listing_count: int


class Renter(MutableResource):
    display_name: str
    email: str
    date_of_birth: str
    license_state_code: str
    wallet_credit_cents: int
    renter_penalty_points: int
    driving_record_points: int
    driving_record_status: str
    towing_verified_tier: str


class Listing(MutableResource):
    owner_id: str
    nickname: str
    vehicle_class: str
    requires_towing: bool
    gvwr_lbs: int
    length_ft: int
    base_nightly_rate_cents: int
    included_miles_per_night: int
    mileage_overage_rate_cents_per_mile: int
    included_generator_hours_per_night: float
    generator_overage_rate_cents_per_hour: int
    min_renter_age: int
    delivery_offered: bool
    delivery_base_fee_cents: int
    delivery_per_mile_cents: int
    listing_status: str
    insurance_status: str
    inspection_photo_zone_count: int
    completed_night_count: int
    last_reconciled_at: Optional[str]


class VehicleDocument(MutableResource):
    listing_id: str
    doc_type: str
    zone: Optional[str]
    expires_on: Optional[str]
    image_ref: str
    verification_status: str
    superseded: bool


class ProtectionPlan(MutableResource):
    tier: str
    daily_premium_cents: int
    premium_pct_of_base_bp: int
    deductible_cents: int
    coverage_ceiling_cents: int
    excluded_causes: List[str]
    eligible_vehicle_classes: List[str]


class CancellationPolicy(MutableResource):
    tier: str
    full_refund_hours_before: int
    partial_refund_pct_bp: int
    renter_cancel_penalty_points: int
    owner_cancel_penalty_points: int
    owner_cancel_fee_bp: int


class PricingSeason(MutableResource):
    season_code: str
    start_month_day: str
    end_month_day: str
    multiplier_bp: int


class Campground(MutableResource):
    name: str
    state_code: str
    max_rig_length_ft: int
    daily_dropoff_capacity: int
    dropoff_buffer_minutes: int
    status: str
    scheduled_assignment_count: int


class Booking(MutableResource):
    listing_id: str
    renter_id: str
    protection_plan_id: str
    cancellation_policy_id: str
    start_date: str
    end_date: str
    delivery_option: str
    declared_miles: int
    declared_generator_hours: float
    nights: int
    trip_status: str
    settlement_status: str
    renter_age_years_at_start: int
    renter_record_points_snapshot: int
    towing_verified_tier: str
    base_subtotal_cents: int
    premium_cents: int
    delivery_fee_cents: int
    loyalty_tier: str
    loyalty_discount_cents: int
    service_fee_cents: int
    estimated_overage_cents: int
    quoted_total_cents: int
    hold_amount_cents: int
    final_overage_cents: int
    trip_total_overage_cents: int
    late_return_fee_cents: int
    final_total_cents: int
    balance_due_cents: int
    refund_cents: int
    info_round_count: int


class DeliveryAssignment(MutableResource):
    booking_id: str
    campground_id: str
    window_start: str
    window_end: str
    distance_miles: int
    setup_fee_cents: int
    delivery_fee_cents: int
    status: str
    dropoff_date: str
    promoted_from_waitlist: bool


class DamageClaim(MutableResource):
    booking_id: str
    cause_code: str
    damage_zone: str
    claimed_amount_cents: int
    description: str
    status: str
    comparison_verdict: Optional[str]
    pre_photo_count: int
    post_photo_count: int
    info_rounds_used: int
    gross_amount_cents: int
    renter_charge_cents: int
    plan_paid_cents: int
    owner_payout_cents: int
    override_amount_cents: Optional[int]
    override_reason: Optional[str]


# ---------------------------------------------------------------------------
# Append-only evidence: id / created_at only
# ---------------------------------------------------------------------------
class AppendOnlyRecord(TypedDict):
    id: str
    created_at: str


class RenterQualification(AppendOnlyRecord):
    renter_id: str
    check_type: str
    result: str
    violation_points: int
    checked_at: str
    expires_on: Optional[str]


class MeterReading(AppendOnlyRecord):
    booking_id: str
    reading_type: str
    odometer_miles: int
    generator_hours: float
    recorded_at: str


class TripPhoto(AppendOnlyRecord):
    booking_id: str
    phase: str
    zone: str
    damage_flagged: bool
    image_ref: str


class LedgerEntry(AppendOnlyRecord):
    booking_id: str
    party: str
    entry_type: str
    amount_cents: int
    reversal_of_entry_id: Optional[str]
    memo: str


class PricingGuidance(TypedDict):
    """The read-only pricing guidance projection. It stores nothing."""

    listing_id: str
    window_start_date: str
    window_end_date: str
    booked_nights: int
    utilization_bp: int
    util_adj_bp: int
    season_code: str
    season_multiplier_bp: int
    suggested_nightly_rate_cents: int


# Resources whose payloads must never expose updated_at or version.
APPEND_ONLY_RESOURCE_NAMES = (
    "renter_qualification",
    "meter_reading",
    "trip_photo",
    "ledger_entry",
)
