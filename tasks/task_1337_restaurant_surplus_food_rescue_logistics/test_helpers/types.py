"""Domain types: entity shapes, status enums, role enum (PRD §2.1, §3).

Common-resource contract (PRD §2.5): every resource carries id, created_at,
updated_at, and version — EXCEPT temperature logs, which carry only id and
created_at plus their reading fields (immutable artifacts).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    DISPATCH_ADMIN = "DispatchAdmin"
    DONOR_COORDINATOR = "DonorCoordinator"
    VOLUNTEER_DRIVER = "VolunteerDriver"
    AGENCY_COORDINATOR = "AgencyCoordinator"


class FoodCategory(str, Enum):
    COLD_HELD = "COLD_HELD"
    HOT_HELD = "HOT_HELD"
    PRODUCE = "PRODUCE"
    SHELF_STABLE = "SHELF_STABLE"


class DonorSiteStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class DriverStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"


class CoolerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    CHECKED_OUT = "CHECKED_OUT"
    CLEANING = "CLEANING"
    QUARANTINED = "QUARANTINED"


class CoolerReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_OUT = "CHECKED_OUT"
    RELEASED = "RELEASED"
    RETURNED = "RETURNED"
    QUARANTINED_HOLD = "QUARANTINED_HOLD"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    SCHEDULED = "SCHEDULED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    DISCARDED = "DISCARDED"


class RunStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"
    VERIFIED = "VERIFIED"
    DECLINED = "DECLINED"
    FAILED_PICKUP = "FAILED_PICKUP"
    FAILED_DELIVERY = "FAILED_DELIVERY"
    CANCELLED = "CANCELLED"


class SafetyStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PROVISIONAL_COMPLIANT = "PROVISIONAL_COMPLIANT"
    VERIFIED_COMPLIANT = "VERIFIED_COMPLIANT"
    VERIFIED_VIOLATION = "VERIFIED_VIOLATION"


class FaultParty(str, Enum):
    DONOR = "DONOR"
    DRIVER = "DRIVER"
    AGENCY = "AGENCY"
    NONE = "NONE"


class FailureReason(str, Enum):
    DONOR_NO_SHOW = "DONOR_NO_SHOW"
    DRIVER_NO_SHOW = "DRIVER_NO_SHOW"
    SAFETY_REJECTED = "SAFETY_REJECTED"
    AGENCY_CLOSED = "AGENCY_CLOSED"
    OVER_CAPACITY = "OVER_CAPACITY"
    SAFETY_DISPOSAL = "SAFETY_DISPOSAL"
    OTHER = "OTHER"


class TemperaturePoint(str, Enum):
    PICKUP = "PICKUP"
    ARRIVAL = "ARRIVAL"


class ReporterRole(str, Enum):
    DRIVER = "DRIVER"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"


class StrikeSubjectType(str, Enum):
    DONOR_SITE = "DONOR_SITE"
    DRIVER = "DRIVER"


class StrikeStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    WAIVED = "WAIVED"


class TaxReceiptStatus(str, Enum):
    ISSUED = "ISSUED"
    AMENDED = "AMENDED"


class DonorSite(TypedDict, total=False):
    id: str
    legal_name: str
    ein: str
    contact_email: str
    enhanced_deduction_eligible: bool
    status: str
    strike_count: int
    lifetime_weight_lbs: int
    pending_estimated_lbs: int
    lifetime_tax_value_cents: int
    created_at: str
    updated_at: str
    version: int


class RecipientAgency(TypedDict, total=False):
    id: str
    name: str
    accepts_categories: List[str]
    capacity_cold_held_lbs: int
    capacity_hot_held_lbs: int
    capacity_produce_lbs: int
    capacity_shelf_stable_lbs: int
    committed_cold_held_lbs: int
    committed_hot_held_lbs: int
    committed_produce_lbs: int
    committed_shelf_stable_lbs: int
    received_total_lbs: int
    created_at: str
    updated_at: str
    version: int


class VolunteerDriver(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    vehicle_capacity_lbs: int
    cooler_slot_count: int
    cold_chain_certified: bool
    status: str
    reliability_score: int
    completed_run_count: int
    upheld_strike_count: int
    created_at: str
    updated_at: str
    version: int


class DriverAvailabilityWindow(TypedDict, total=False):
    id: str
    driver_id: str
    window_start: str
    window_end: str
    status: str
    booked_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Cooler(TypedDict, total=False):
    id: str
    label: str
    capacity_liters: int
    status: str
    cleaning_ends_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoolerReservation(TypedDict, total=False):
    id: str
    cooler_id: str
    rescue_run_id: str
    blocked_start: str
    blocked_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DonationOffer(TypedDict, total=False):
    id: str
    donor_site_id: str
    food_category: str
    requires_cold_chain: bool
    estimated_weight_lbs: int
    pickup_window_start: str
    pickup_window_end: str
    status: str
    failed_attempts: int
    current_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RescueRun(TypedDict, total=False):
    id: str
    offer_id: str
    agency_id: str
    driver_id: str
    run_status: str
    safety_status: str
    estimated_weight_snapshot: int
    actual_weight_lbs: Optional[int]
    pickup_time: Optional[str]
    arrival_time: Optional[str]
    verified_at: Optional[str]
    driver_attestation_signed_at: Optional[str]
    agency_countersigned_by_user_id: Optional[str]
    agency_countersigned_at: Optional[str]
    fault_party: Optional[str]
    failure_reason: Optional[str]
    disposal_method: Optional[str]
    disposal_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only artifact (PRD §2.5): carries ONLY id + created_at plus the
# reading fields — no updated_at, no version.
class TemperatureLog(TypedDict, total=False):
    id: str
    rescue_run_id: str
    point: str
    temp_f: float
    recorded_at: str
    recorded_by_user_id: str
    created_at: str


class StrikeReport(TypedDict, total=False):
    id: str
    rescue_run_id: str
    reporter_role: str
    reporter_user_id: Optional[str]
    subject_type: str
    subject_id: str
    reason: str
    status: str
    adjudicated_by_user_id: Optional[str]
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxReceiptLine(TypedDict, total=False):
    food_category: str
    weight_lbs: int
    fmv_cents_per_lb: int
    basis_cents_per_lb: int
    standard_cents: int
    enhanced_cents: int


class TaxReceipt(TypedDict, total=False):
    id: str
    donor_site_id: str
    period_start: str
    period_end: str
    status: str
    rate_card_version: int
    lines: List[TaxReceiptLine]
    total_standard_value_cents: int
    total_enhanced_value_cents: int
    deductible_value_cents: int
    total_weight_lbs: int
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict, total=False):
    id: str
    effective_start: str
    effective_end: str
    card_version: int
    cold_held_fmv_cents_per_lb: int
    cold_held_basis_cents_per_lb: int
    hot_held_fmv_cents_per_lb: int
    hot_held_basis_cents_per_lb: int
    produce_fmv_cents_per_lb: int
    produce_basis_cents_per_lb: int
    shelf_stable_fmv_cents_per_lb: int
    shelf_stable_basis_cents_per_lb: int
    created_at: str
    updated_at: str
    version: int
