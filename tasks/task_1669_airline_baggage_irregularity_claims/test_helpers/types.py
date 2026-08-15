"""Domain types: entity TypedDicts, status enums, role enum for the baggage claims API."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    BAGGAGE_SERVICE_AGENT = "BaggageServiceAgent"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PASSENGER = "Passenger"


class BagTagStatus(str, Enum):
    CHECKED = "CHECKED"
    MISHANDLED = "MISHANDLED"
    IN_RECOVERY = "IN_RECOVERY"
    DELIVERED = "DELIVERED"
    DELIVERED_DAMAGED = "DELIVERED_DAMAGED"
    CLAIMED_LOST = "CLAIMED_LOST"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    TRACING = "TRACING"
    FOUND_PENDING_DELIVERY = "FOUND_PENDING_DELIVERY"
    DELIVERY_IN_PROGRESS = "DELIVERY_IN_PROGRESS"
    DELIVERED = "DELIVERED"
    DECLARED_LOST = "DECLARED_LOST"
    DAMAGE_REVIEW = "DAMAGE_REVIEW"
    CLAIM_REVIEW = "CLAIM_REVIEW"
    SETTLEMENT_OFFERED = "SETTLEMENT_OFFERED"
    SETTLEMENT_ACCEPTED = "SETTLEMENT_ACCEPTED"
    CLOSED = "CLOSED"


class ReportType(str, Enum):
    DELAYED = "DELAYED"
    DAMAGED = "DAMAGED"
    PILFERED = "PILFERED"


class LiabilityRegime(str, Enum):
    MONTREAL = "MONTREAL"
    DOMESTIC = "DOMESTIC"


class TracingEventType(str, Enum):
    FORWARDED = "FORWARDED"
    LOCATED = "LOCATED"
    ON_HAND_AT_STATION = "ON_HAND_AT_STATION"
    IN_TRANSIT_TO = "IN_TRANSIT_TO"
    DELIVERY_ARRANGED = "DELIVERY_ARRANGED"
    MISSCAN_CORRECTED = "MISSCAN_CORRECTED"


class DispatchStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    FAILED_ATTEMPT = "FAILED_ATTEMPT"
    DELIVERED = "DELIVERED"
    FAILED_PERMANENT = "FAILED_PERMANENT"


class RepairOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS"
    REPLACEMENT_PENDING = "REPLACEMENT_PENDING"
    REPAIR_SETTLED = "REPAIR_SETTLED"
    REPLACE_SETTLED = "REPLACE_SETTLED"
    CANCELLED = "CANCELLED"


class RepairDecision(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"


class ExpenseClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SETTLEMENT_EARMARKED = "SETTLEMENT_EARMARKED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class SettlementPaymentStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class PassengerTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    ELITE = "ELITE"


class RootCause(str, Enum):
    MISCONNECT = "MISCONNECT"
    BAGROOM_ERROR = "BAGROOM_ERROR"
    LOADING_ERROR = "LOADING_ERROR"
    TAGGING_ERROR = "TAGGING_ERROR"
    SECURITY_HOLD = "SECURITY_HOLD"


# --- Entity TypedDicts -------------------------------------------------------
# All primary resources carry id + created_at + updated_at + version (PRD §2.4).
# TracingEvent is the single append-only exception: only id + created_at.


class Station(TypedDict, total=False):
    id: str
    station_code: str
    name: str
    bags_handled_total: int
    open_report_count: int
    recovered_bag_count: int
    mishandled_report_count: int
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict, total=False):
    id: str
    carrier_code: str
    name: str
    is_interline_partner: bool
    created_at: str
    updated_at: str
    version: int


class CourierService(TypedDict, total=False):
    id: str
    name: str
    serves_station_ids: List[str]
    turnaround_buffer_minutes: int
    active_dispatch_count: int
    created_at: str
    updated_at: str
    version: int


class RepairVendor(TypedDict, total=False):
    id: str
    name: str
    bench_capacity: int
    occupied_bench_slots: int
    available_bench_slots: int
    created_at: str
    updated_at: str
    version: int


class Passenger(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    tier: str
    created_at: str
    updated_at: str
    version: int


class BagTag(TypedDict, total=False):
    id: str
    tag_number: str
    passenger_id: str
    routing_carrier_ids: List[str]
    is_international: bool
    weight_kg: int
    declared_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IrregularityReport(TypedDict, total=False):
    id: str
    report_reference: str
    passenger_id: str
    bag_tag_id: str
    station_id: str
    type: str
    status: str
    opened_on: str
    delivered_on: Optional[str]
    liability_regime: str
    liable_carrier_id: str
    effective_cap_cents: int
    contents_loss_cents: Optional[int]
    damage_repairable: Optional[bool]
    contents_damage_cents: Optional[int]
    repair_payout_cents: int
    root_cause: Optional[str]
    root_cause_station_id: Optional[str]
    settlement_offer_cents: Optional[int]
    amount_payable_cents: int
    expenses_approved_unpaid_cents: int
    expenses_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class TracingEvent(TypedDict, total=False):
    # Append-only (PRD §2.4): carries ONLY id + created_at, no updated_at/version.
    id: str
    created_at: str
    report_id: str
    carrier_id: str
    station_id: str
    event_type: str
    occurred_at: str
    notes: str


class DeliveryDispatch(TypedDict, total=False):
    id: str
    report_id: str
    courier_service_id: str
    pickup_at: str
    travel_minutes: int
    delivery_address: str
    attempt_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict, total=False):
    id: str
    report_id: str
    vendor_id: str
    intake_date: str
    promised_date: str
    purchase_price_cents: int
    purchase_date: str
    repair_estimate_cents: int
    depreciated_value_cents: Optional[int]
    decision: Optional[str]
    payout_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpenseClaim(TypedDict, total=False):
    id: str
    report_id: str
    receipts: List[dict]
    claimed_total_cents: int
    eligible_receipt_count: int
    reimbursable_total_cents: Optional[int]
    decision_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementPayment(TypedDict, total=False):
    id: str
    report_id: str
    settlement_component_cents: int
    expense_component_cents: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
