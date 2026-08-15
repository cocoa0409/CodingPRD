"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    FORWARDER_OPS = "ForwarderOps"
    CAPACITY_PLANNER = "CapacityPlanner"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CUSTOMS_BROKER = "CustomsBroker"
    PRICING_MANAGER = "PricingManager"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


class KnownShipperStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    KNOWN = "KNOWN"
    SUSPENDED = "SUSPENDED"


class FlightBookingStatus(str, Enum):
    OPEN = "OPEN"
    CUTOFF_CLOSED = "CUTOFF_CLOSED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class MasterWaybillStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_FOR_CONSOLIDATION = "OPEN_FOR_CONSOLIDATION"
    TENDERED = "TENDERED"
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    VOID = "VOID"


class HouseWaybillStatus(str, Enum):
    DRAFT = "DRAFT"
    SCREENING = "SCREENING"
    SCREENING_REJECTED = "SCREENING_REJECTED"
    CLEARED = "CLEARED"
    CONSOLIDATED = "CONSOLIDATED"
    TENDERED = "TENDERED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class WeightBasis(str, Enum):
    UNRATED = "UNRATED"
    QUOTED = "QUOTED"
    FINAL = "FINAL"


class ScreeningType(str, Enum):
    SECURITY = "SECURITY"
    DANGEROUS_GOODS = "DANGEROUS_GOODS"


class ScreeningResult(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class CustomsEntryStatus(str, Enum):
    PREPARING = "PREPARING"
    HANDED_OFF = "HANDED_OFF"
    FILED = "FILED"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"


class CustomsEntryType(str, Enum):
    INFORMAL = "INFORMAL"
    CONSUMPTION = "CONSUMPTION"
    TRANSIT = "TRANSIT"


class MilestoneEventCode(str, Enum):
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"


class ExceptionCode(str, Enum):
    NONE = "NONE"
    DAMAGE = "DAMAGE"
    SHORTAGE = "SHORTAGE"
    DELAY = "DELAY"
    CUSTOMS_HOLD = "CUSTOMS_HOLD"


class ClaimType(str, Enum):
    DAMAGE = "DAMAGE"
    SHORTAGE = "SHORTAGE"
    DELAY = "DELAY"
    LOSS = "LOSS"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    COUNTERED = "COUNTERED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class LiabilityBasis(str, Enum):
    STANDARD = "STANDARD"
    DECLARED_VALUE = "DECLARED_VALUE"


class Shipper(TypedDict, total=False):
    id: str
    name: str
    account_code: str
    known_shipper_status: str
    screening_rejection_count: int
    created_at: str
    updated_at: str
    version: int


class FlightBooking(TypedDict, total=False):
    id: str
    airline_code: str
    flight_number: str
    origin_code: str
    destination_code: str
    scheduled_departure_utc: str
    cutoff_utc: str
    booked_weight_kg: float
    booked_volume_m3: float
    consumed_weight_kg: float
    consumed_volume_m3: float
    utilization_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MasterWaybill(TypedDict, total=False):
    id: str
    booking_id: str
    mawb_number: str
    total_chargeable_weight_kg: float
    total_volume_m3: float
    total_freight_amount: float
    tender_window_start_utc: Optional[str]
    tender_window_end_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HouseWaybill(TypedDict, total=False):
    id: str
    shipper_id: str
    mawb_id: Optional[str]
    hwb_number: str
    origin_code: str
    destination_code: str
    pieces: int
    gross_weight_kg: float
    declared_volume_m3: float
    measured_volume_m3: Optional[float]
    effective_volume_m3: float
    chargeable_weight_kg: float
    weight_basis: str
    dg_flag: bool
    declared_value_amount: float
    declared_value_surcharge_paid: bool
    freight_amount: float
    fuel_surcharge_amount: float
    security_fee_amount: float
    spot_surcharge_amount: float
    spot_surcharge_applied: bool
    total_charge_amount: float
    rate_agreement_id: Optional[str]
    submitted_by_user_id: Optional[str]
    delivered_at_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScreeningRecord(TypedDict, total=False):
    id: str
    hwb_id: str
    screening_type: str
    result: str
    rejection_reason: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustomsEntry(TypedDict, total=False):
    id: str
    hwb_id: str
    entry_type: str
    broker_reference: Optional[str]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WeightBreak(TypedDict):
    min_weight_kg: float
    rate_per_kg: float


class RateAgreement(TypedDict, total=False):
    id: str
    shipper_id: str
    origin_code: str
    destination_code: str
    weight_breaks: List[WeightBreak]
    min_charge_amount: float
    fuel_surcharge_pct: float
    security_fee_amount: float
    spot_surcharge_pct: float
    valid_from_utc: str
    valid_to_utc: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit entry (PRD §2.4): carries ONLY id + created_at among the
# common fields — no updated_at, no version.
class MilestoneEvent(TypedDict, total=False):
    id: str
    mawb_id: str
    event_code: str
    event_time_utc: str
    exception_code: str
    note: Optional[str]
    out_of_order: bool
    created_at: str


class Claim(TypedDict, total=False):
    id: str
    hwb_id: str
    claim_type: str
    claimed_amount: float
    liability_basis: str
    liability_limit_amount: float
    approved_amount: Optional[float]
    counter_amount: Optional[float]
    review_round_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
