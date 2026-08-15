"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    OPS_MANAGER = "OpsManager"
    TOUR_MANAGER = "TourManager"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    WAREHOUSE_TECH = "WarehouseTech"
    PARTNER_VENDOR_REP = "PartnerVendorRep"


class ArtistTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    PLATINUM = "PLATINUM"


class TourStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TourStopStatus(str, Enum):
    PLANNED = "PLANNED"
    GEAR_STAGED = "GEAR_STAGED"
    SHOW_READY = "SHOW_READY"
    LOADED_OUT = "LOADED_OUT"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class RiderLineStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SOURCED = "SOURCED"
    SUBSTITUTION_PENDING = "SUBSTITUTION_PENDING"
    APPROVED = "APPROVED"
    FULFILLED = "FULFILLED"
    SHORTED = "SHORTED"
    CANCELLED = "CANCELLED"


class GearCategory(str, Enum):
    GUITAR = "GUITAR"
    BASS = "BASS"
    DRUMS = "DRUMS"
    KEYS = "KEYS"
    AMP = "AMP"
    PA = "PA"
    BACKLINE_MISC = "BACKLINE_MISC"


class WeightClass(str, Enum):
    HAND_CARRY = "HAND_CARRY"
    STANDARD = "STANDARD"
    HEAVY = "HEAVY"
    OVERSIZE = "OVERSIZE"


class GearUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OUT_ON_RENTAL = "OUT_ON_RENTAL"
    IN_TRANSIT = "IN_TRANSIT"
    MAINTENANCE = "MAINTENANCE"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class ReservationLineStatus(str, Enum):
    DRAFT = "DRAFT"
    SOURCED = "SOURCED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    INSPECTED = "INSPECTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADING = "LOADING"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ShipmentLineStatus(str, Enum):
    BOOKED = "BOOKED"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class FlightCaseStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    IN_TRANSIT = "IN_TRANSIT"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class FlightCaseSizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    TRUNK = "TRUNK"


class PartnerVendorStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class CrossRentalRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class MaintenanceTicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_PARTS = "AWAITING_PARTS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MaintenanceTicketReason(str, Enum):
    SCHEDULED_CYCLE = "SCHEDULED_CYCLE"
    DAMAGE_REPAIR = "DAMAGE_REPAIR"
    CONDITION_THRESHOLD = "CONDITION_THRESHOLD"
    POST_FLIGHT_INSPECTION = "POST_FLIGHT_INSPECTION"


class DamageClaimStatus(str, Enum):
    FILED = "FILED"
    ASSESSED = "ASSESSED"
    CHARGED = "CHARGED"
    DISPUTED = "DISPUTED"
    WAIVED = "WAIVED"
    PAID = "PAID"


class DamageSeverity(str, Enum):
    COSMETIC = "COSMETIC"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    TOTAL_LOSS = "TOTAL_LOSS"


class Artist(TypedDict, total=False):
    id: str
    legal_name: str
    tier: str
    deposit_credit_cents: int
    deposit_waived: bool
    risk_score: int
    created_at: str
    updated_at: str
    version: int


class Tour(TypedDict, total=False):
    id: str
    artist_id: str
    name: str
    status: str
    start_date: str
    end_date: str
    insurance_policy_id: Optional[str]
    projected_rental_fee_cents: int
    final_settlement_cents: int
    stop_count: int
    created_at: str
    updated_at: str
    version: int


class TourStop(TypedDict, total=False):
    id: str
    tour_id: str
    city_code: str
    venue_date: str
    load_in_ts: str
    status: str
    rider_revision: int
    created_at: str
    updated_at: str
    version: int


class RiderLine(TypedDict, total=False):
    id: str
    tour_stop_id: str
    gear_model_id: str
    quantity: int
    status: str
    fulfilled_by_reservation_id: Optional[str]
    substitution_of_line_id: Optional[str]
    substitution_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GearModel(TypedDict, total=False):
    id: str
    sku: str
    category: str
    daily_rate_cents: int
    replacement_value_cents: int
    weight_class: str
    substitute_model_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class GearUnit(TypedDict, total=False):
    id: str
    gear_model_id: str
    serial_number: str
    home_city_code: str
    status: str
    condition_score: int
    rental_days_since_service: int
    flight_case_required: bool
    active_reservation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReservationLine(TypedDict, total=False):
    id: str
    tour_id: str
    rider_line_id: str
    gear_unit_id: Optional[str]
    origin_city_code: str
    dest_city_code: str
    start_date: str
    end_date: str
    status: str
    quoted_fee_cents: int
    settled_fee_cents: Optional[int]
    deposit_held_cents: int
    is_cross_rental: bool
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    tour_id: str
    from_city_code: str
    to_city_code: str
    ship_date: str
    status: str
    tech_labor_minutes: int
    capacity_kg: int
    booked_weight_kg: int
    created_at: str
    updated_at: str
    version: int


class ShipmentLine(TypedDict, total=False):
    id: str
    shipment_id: str
    gear_unit_id: str
    flight_case_id: Optional[str]
    weight_kg: int
    labor_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FlightCase(TypedDict, total=False):
    id: str
    case_code: str
    size_class: str
    home_city_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PartnerVendor(TypedDict, total=False):
    id: str
    name: str
    city_codes: List[str]
    commission_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CrossRentalRequest(TypedDict, total=False):
    id: str
    reservation_line_id: str
    partner_vendor_id: str
    gear_model_id: str
    status: str
    vendor_rate_cents_per_day: int
    commission_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MaintenanceTicket(TypedDict, total=False):
    id: str
    gear_unit_id: str
    opened_reason: str
    status: str
    opened_at: str
    closed_at: Optional[str]
    service_cost_cents: Optional[int]
    condition_delta: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    reservation_line_id: str
    gear_unit_id: str
    assessed_severity: str
    repair_estimate_cents: int
    status: str
    charge_cents: Optional[int]
    filed_by_user_id: str
    created_at: str
    updated_at: str
    version: int
