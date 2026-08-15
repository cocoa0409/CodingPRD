"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource carries the standard
four system-managed fields (id, created_at, updated_at, version) per the PRD
common-resource-properties section.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    RENTER = "Renter"
    DOCK_STAFF = "DockStaff"
    FLEET_MANAGER = "FleetManager"
    MECHANIC = "Mechanic"


class SizeClass(str, Enum):
    COMPACT_36 = "COMPACT_36"
    STANDARD_44 = "STANDARD_44"
    LUXE_56 = "LUXE_56"


class Season(str, Enum):
    PEAK = "PEAK"
    SHOULDER = "SHOULDER"
    OFF_PEAK = "OFF_PEAK"


class VesselStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_MAINTENANCE = "IN_MAINTENANCE"


class QualificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"


class CertificateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class IssuingAuthority(str, Enum):
    NASBLA = "NASBLA"
    USCG = "USCG"
    STATE = "STATE"


class BookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CHECKED_OUT = "CHECKED_OUT"
    INTERRUPTED = "INTERRUPTED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class SettlementStatus(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"


class DepositStatus(str, Enum):
    PENDING = "PENDING"
    HELD = "HELD"
    RELEASED = "RELEASED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    FULLY_APPLIED = "FULLY_APPLIED"


class OrientationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    COUNTERSIGNED = "COUNTERSIGNED"
    CANCELLED = "CANCELLED"


class CancellationReason(str, Enum):
    RENTER_REQUEST = "RENTER_REQUEST"
    WEATHER = "WEATHER"
    RENTER_SUSPENDED = "RENTER_SUSPENDED"
    VESSEL_MECHANICAL = "VESSEL_MECHANICAL"


class ItineraryStatus(str, Enum):
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class ChargeLineType(str, Enum):
    RENTAL = "RENTAL"
    RENTAL_ADJUSTMENT = "RENTAL_ADJUSTMENT"
    FUEL = "FUEL"
    PUMP_OUT = "PUMP_OUT"
    CLEANING_FEE = "CLEANING_FEE"
    LATE_RETURN = "LATE_RETURN"
    DAMAGE = "DAMAGE"
    GROUNDING_LIABILITY = "GROUNDING_LIABILITY"
    MECHANICAL_REFUND = "MECHANICAL_REFUND"
    CANCELLATION_REFUND = "CANCELLATION_REFUND"


class ChargeStatus(str, Enum):
    POSTED = "POSTED"
    PAID = "PAID"
    APPLIED_TO_DEPOSIT = "APPLIED_TO_DEPOSIT"
    REFUNDED = "REFUNDED"


class IncidentType(str, Enum):
    MECHANICAL_FAILURE = "MECHANICAL_FAILURE"
    GROUNDING = "GROUNDING"
    DAMAGE = "DAMAGE"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    TOTAL_LOSS = "TOTAL_LOSS"


class IncidentResolution(str, Enum):
    REPAIRED_RESUME = "REPAIRED_RESUME"
    REPAIRED_TERMINATE = "REPAIRED_TERMINATE"
    GROUNDING_CONFIRMED = "GROUNDING_CONFIRMED"
    DAMAGE_ASSESSED = "DAMAGE_ASSESSED"
    REJECTED = "REJECTED"


class MaintenanceWindowSource(str, Enum):
    SCHEDULED_PLANNED = "SCHEDULED_PLANNED"
    INCIDENT_EMERGENCY = "INCIDENT_EMERGENCY"


class MaintenanceWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class CleaningTurnStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AdvisorySeverity(str, Enum):
    WATCH = "WATCH"
    WARNING = "WARNING"
    STORM = "STORM"


class WeatherAdvisoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all resources carry id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Vessel(TypedDict):
    id: str
    name: str
    size_class: str
    berth_count: int
    home_marina: str
    fuel_tank_capacity_gallons: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonRate(TypedDict):
    id: str
    size_class: str
    season: str
    start_date: str
    end_date: str
    nightly_rate_cents: int
    weekly_discount_pct: int
    created_at: str
    updated_at: str
    version: int


class GeoZone(TypedDict):
    id: str
    zone_code: str
    name: str
    max_vessels_per_night: int
    allowed_size_classes: List[str]
    created_at: str
    updated_at: str
    version: int


class Renter(TypedDict):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    qualification_status: str
    risk_score_lifetime: int
    risk_score_rolling_24m: int
    deposit_multiplier: float
    created_at: str
    updated_at: str
    version: int


class SafetyCertificate(TypedDict):
    id: str
    renter_id: str
    cert_number: str
    issuing_authority: str
    issued_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    vessel_id: str
    renter_id: str
    start_date: str
    end_date: str
    party_size: int
    status: str
    settlement_status: str
    deposit_status: str
    orientation_status: str
    orientation_items: List[dict]
    total_nights: int
    quoted_total_cents: int
    deposit_required_cents: int
    deposit_held_cents: int
    deposit_applied_cents: int
    deposit_released_cents: int
    refund_issued_cents: int
    provisional_estimate_cents: Optional[int]
    final_settlement_cents: Optional[int]
    checkout_fuel_gauge_percent: Optional[int]
    checkout_pump_out_done: Optional[bool]
    return_fuel_gauge_percent: Optional[int]
    return_pump_out_done: Optional[bool]
    actual_return_at: Optional[str]
    hold_expires_at: str
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Itinerary(TypedDict):
    id: str
    booking_id: str
    waypoints: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    booking_id: str
    line_type: str
    amount_cents: int
    status: str
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    booking_id: str
    incident_type: str
    occurred_at: str
    description: Optional[str]
    status: str
    severity: Optional[str]
    resolution: Optional[str]
    downtime_days: Optional[int]
    assessed_damage_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict):
    id: str
    vessel_id: str
    start_date: str
    end_date: str
    reason: Optional[str]
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CleaningTurn(TypedDict):
    id: str
    booking_id: str
    scheduled_date: str
    status: str
    re_clean_count: int
    created_at: str
    updated_at: str
    version: int


class WeatherAdvisory(TypedDict):
    id: str
    severity: str
    zone_ids: List[str]
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int
