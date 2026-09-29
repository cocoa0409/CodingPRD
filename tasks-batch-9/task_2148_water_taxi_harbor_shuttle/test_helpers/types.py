"""Domain types for the Water Taxi & Harbor Shuttle API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    HARBOR_ADMIN = "HarborAdmin"
    DISPATCHER = "Dispatcher"
    VESSEL_MASTER = "VesselMaster"
    MARINE_INSPECTOR = "MarineInspector"
    RIDER = "Rider"
    FARE_AUDITOR = "FareAuditor"


class DockFeeStatus(str, Enum):
    ACCRUING = "ACCRUING"
    CAPPED = "CAPPED"


class HullClass(str, Enum):
    HARBOR = "HARBOR"
    OFFSHORE = "OFFSHORE"


class EndorsementClass(str, Enum):
    MASTER_25T = "MASTER_25T"
    MASTER_100T = "MASTER_100T"


class VesselServiceState(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    LAID_UP = "LAID_UP"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class InspectionType(str, Enum):
    ANNUAL = "ANNUAL"
    PRE_DEPARTURE = "PRE_DEPARTURE"


class InspectionResult(str, Enum):
    PASS = "PASS"
    PASS_WITH_DEFICIENCIES = "PASS_WITH_DEFICIENCIES"
    FAIL = "FAIL"


class CrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Posture(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class SurgeTier(str, Enum):
    NONE = "NONE"
    ELEVATED = "ELEVATED"
    PEAK = "PEAK"


class ServiceMode(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_DEMAND = "ON_DEMAND"


class TripOperationalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BOARDING = "BOARDING"
    DEPARTED = "DEPARTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TripSettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    VOID = "VOID"


class DockSlotPurpose(str, Enum):
    LANDING = "LANDING"
    LAYOVER = "LAYOVER"


class DockSlotStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    VOIDED = "VOIDED"


class ZoneTier(str, Enum):
    INNER = "INNER"
    OUTER = "OUTER"
    ALL_ZONE = "ALL_ZONE"


class RidePassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    REFUNDED = "REFUNDED"


class SettlementBasis(str, Enum):
    PRO_RATA = "PRO_RATA"
    DIFFERENTIAL = "DIFFERENTIAL"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    BOARDED = "BOARDED"
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"
    UNFULFILLED = "UNFULFILLED"


class RedemptionStatus(str, Enum):
    NONE = "NONE"
    REDEEMED = "REDEEMED"
    RESTORED = "RESTORED"


class InterruptionCause(str, Enum):
    WEATHER = "WEATHER"
    TIDE = "TIDE"
    MECHANICAL = "MECHANICAL"
    DOCK_CLOSURE = "DOCK_CLOSURE"


class InterruptionStatus(str, Enum):
    DECLARED = "DECLARED"
    RESOLVED = "RESOLVED"


class RefundClaimStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class RefundDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


# --- Entity shapes -------------------------------------------------------
# Every entity below carries id / created_at / updated_at / version, except
# VesselInspection, which is an immutable event record carrying only id and
# created_at.


class Dock(TypedDict):
    id: str
    name: str
    berth_count: int
    min_turnaround_minutes: int
    landing_fee_per_pax_cents: int
    berth_minute_rate_cents: int
    monthly_fee_cap_cents: int
    shared_operator_count: int
    accrued_fee_cents: int
    fee_status: str
    created_at: str
    updated_at: str
    version: int


class Stop(TypedDict):
    id: str
    dock_id: str
    name: str
    zone_index: int
    charted_depth_m: float
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict):
    id: str
    name: str
    seat_capacity: int
    draft_m: float
    hull_class: str
    required_endorsement: str
    layup_start_date: Optional[str]
    layup_end_date: Optional[str]
    service_state: str
    annual_inspection_expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VesselInspection(TypedDict):
    id: str
    vessel_id: str
    inspection_type: str
    result: str
    deficiency_count: int
    performed_on: str
    expires_on: Optional[str]
    inspector_user_id: str
    created_at: str


class CrewMember(TypedDict):
    id: str
    name: str
    endorsement_class: str
    cert_expires_on: str
    medical_expires_on: str
    status: str
    trips_mastered_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceDay(TypedDict):
    id: str
    service_date: str
    wind_knots: float
    wave_height_m: float
    low_water_m: float
    manual_suspension: bool
    event_name: Optional[str]
    expected_attendance: int
    posture: str
    surge_tier: str
    surge_multiplier_bp: int
    planned_extra_vessels: int
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    service_day_id: str
    vessel_id: str
    master_crew_id: str
    origin_stop_id: str
    destination_stop_id: str
    service_mode: str
    scheduled_departure_utc: str
    scheduled_arrival_utc: str
    actual_departure_utc: Optional[str]
    actual_arrival_utc: Optional[str]
    effective_capacity: int
    seats_committed: int
    booked_pax: int
    boarded_pax: int
    operational_status: str
    settlement_status: str
    provisional_fee_cents: int
    final_fee_cents: int
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DockSlot(TypedDict):
    id: str
    dock_id: str
    trip_id: str
    purpose: str
    start_utc: str
    end_utc: str
    status: str
    pax_basis: int
    berth_minutes: int
    rebate_bp: int
    projected_fee_cents: int
    landing_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class RidePass(TypedDict):
    id: str
    rider_user_id: str
    zone_tier: str
    rides_purchased: int
    purchase_price_cents: int
    valid_until: str
    rides_remaining: int
    rides_consumed: int
    status: str
    refund_basis: Optional[str]
    refund_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    rider_user_id: str
    trip_id: Optional[str]
    ride_pass_id: Optional[str]
    origin_stop_id: str
    destination_stop_id: str
    requested_date: str
    service_mode: str
    party_size: int
    offer_round: int
    declined_trip_ids: List[str]
    status: str
    redemption_status: str
    interrupted_from_status: Optional[str]
    fare_quoted_cents: int
    fare_charged_cents: int
    fare_refunded_cents: int
    credit_refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceInterruption(TypedDict):
    id: str
    service_day_id: str
    cause: str
    declared_by_user_id: str
    status: str
    affected_booking_count: int
    total_provisional_refund_cents: int
    created_at: str
    updated_at: str
    version: int


class RefundClaim(TypedDict):
    id: str
    booking_id: str
    service_interruption_id: str
    declarer_user_id: str
    approver_user_id: Optional[str]
    entitlement_cents: int
    cash_refund_cents: int
    credit_refund_cents: int
    ride_restored: bool
    status: str
    created_at: str
    updated_at: str
    version: int
