"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PASSENGER = "Passenger"
    CONDUCTOR = "Conductor"
    FARE_ADMIN = "FareAdmin"


class TicketType(str, Enum):
    SINGLE = "SINGLE"
    MONTHLY = "MONTHLY"


class TravelPeriod(str, Enum):
    PEAK = "PEAK"
    OFF_PEAK = "OFF_PEAK"


class ApportionmentMethod(str, Enum):
    ZONE_COUNT = "ZONE_COUNT"
    DISTANCE = "DISTANCE"


class ReducedFareCategory(str, Enum):
    NONE = "NONE"
    SENIOR = "SENIOR"
    STUDENT = "STUDENT"
    DISABILITY = "DISABILITY"


class TicketStatus(str, Enum):
    PURCHASED = "PURCHASED"
    ACTIVATED = "ACTIVATED"
    VALIDATED = "VALIDATED"
    REFUNDED = "REFUNDED"
    EXCHANGED = "EXCHANGED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class InspectionResult(str, Enum):
    VALID = "VALID"
    UPGRADE_REQUIRED = "UPGRADE_REQUIRED"
    EVASION = "EVASION"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    CONTESTED = "CONTESTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class RefundDestination(str, Enum):
    WALLET = "WALLET"
    ORIGINAL = "ORIGINAL"


class DisruptionSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class ServiceCreditStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


# --- Append-only / immutable config entities: only id + created_at ---

class FareProduct(TypedDict):
    id: str
    origin_zone: int
    destination_zone: int
    ticket_type: str
    base_fare_cents: int
    peak_surcharge_cents: int
    apportionment_method: str
    created_at: str


class Agency(TypedDict):
    id: str
    code: str
    zones_served: List[int]
    created_at: str


class Inspection(TypedDict):
    id: str
    passenger_id: str
    ticket_id: Optional[str]
    observed_destination_zone: int
    result: str
    fare_shortfall_cents: int
    created_at: str


class Upgrade(TypedDict):
    id: str
    inspection_id: str
    ticket_id: str
    from_zone: int
    to_zone: int
    upgrade_fare_cents: int
    created_at: str


class ServiceDisruption(TypedDict):
    id: str
    line_code: str
    scheduled_departure: str
    actual_departure: str
    window_start: str
    window_end: str
    delay_minutes: int
    severity: str
    created_at: str


# --- Mutable entities: id + created_at + updated_at + version ---

class Passenger(TypedDict):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    reduced_fare_category: str
    reduced_fare_valid_until: Optional[str]
    wallet_credit_cents: int
    evasion_count: int
    created_at: str
    updated_at: str
    version: int


class ReducedFareApplication(TypedDict):
    id: str
    passenger_id: str
    category: str
    proof_document_ref: str
    proof_expires_at: str
    valid_until: Optional[str]
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    passenger_id: str
    fare_product_id: str
    ticket_type: str
    origin_zone: int
    destination_zone: int
    travel_period: str
    wallet_applied_cents: int
    reduced_fare_applied: bool
    purchase_price_cents: int
    apportionment_method: str
    revenue_allocations: List[dict]
    status: str
    activated_at: Optional[str]
    expires_at: Optional[str]
    refund_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    inspection_id: str
    passenger_id: str
    base_penalty_cents: int
    fare_shortfall_cents: int
    total_penalty_cents: int
    status: str
    contest_grounds: Optional[str]
    resolution_decision: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict):
    id: str
    ticket_id: str
    reason: str
    refund_destination: str
    refund_amount_cents: int
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceCredit(TypedDict):
    id: str
    disruption_id: str
    ticket_id: str
    passenger_id: str
    credit_amount_cents: int
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
