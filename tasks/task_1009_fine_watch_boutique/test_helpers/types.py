"""Domain types: entity TypedDicts, status enums, role enum.

Every field name mirrors the Fine-Watch Boutique PRD exactly. The append-only
ProvenanceEvent carries only id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    ASSOCIATE = "Associate"
    CLIENT = "Client"
    WATCHMAKER = "Watchmaker"


# --- Shared enums ---
class ConditionGrade(str, Enum):
    NEW = "NEW"
    MINT = "MINT"
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"


class ModelLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class WatchSource(str, Enum):
    PURCHASE = "PURCHASE"
    TRADE_IN = "TRADE_IN"
    CONSIGNMENT = "CONSIGNMENT"


class WatchAuthStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    AUTHENTICATED = "AUTHENTICATED"
    FLAGGED = "FLAGGED"


class WatchStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    OFFERED = "OFFERED"
    RESERVED = "RESERVED"
    IN_SERVICE = "IN_SERVICE"
    CONSIGNED = "CONSIGNED"
    SOLD = "SOLD"


class WaitlistTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIER = "PREMIER"
    VIP = "VIP"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    ALLOCATED = "ALLOCATED"
    EXPIRED = "EXPIRED"
    DECLINED = "DECLINED"


class ServiceType(str, Enum):
    BATTERY = "BATTERY"
    MOVEMENT_OVERHAUL = "MOVEMENT_OVERHAUL"
    WATER_RESISTANCE = "WATER_RESISTANCE"


class MovementComplexity(str, Enum):
    STANDARD = "STANDARD"
    CHRONOGRAPH = "CHRONOGRAPH"
    GRAND_COMPLICATION = "GRAND_COMPLICATION"


class ServiceTicketStatus(str, Enum):
    RECEIVED = "RECEIVED"
    DIAGNOSED = "DIAGNOSED"
    READY = "READY"
    COLLECTED = "COLLECTED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class AppraisalPurpose(str, Enum):
    WARRANTY = "WARRANTY"
    INSURANCE = "INSURANCE"
    SALE = "SALE"


class ValuationBasis(str, Enum):
    MARKET = "MARKET"
    INSURANCE_REPLACEMENT = "INSURANCE_REPLACEMENT"


class Disposition(str, Enum):
    TRADE_IN = "TRADE_IN"
    CONSIGNMENT = "CONSIGNMENT"


class TradeInStatus(str, Enum):
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    SETTLED = "SETTLED"
    DECLINED = "DECLINED"
    REVERSED = "REVERSED"


class LayawayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"
    FULFILLED = "FULFILLED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class ProvenanceEventType(str, Enum):
    INTAKE = "INTAKE"
    AUTHENTICATED = "AUTHENTICATED"
    FLAGGED = "FLAGGED"
    APPRAISED = "APPRAISED"
    SERVICED = "SERVICED"
    LAYAWAY_RESERVED = "LAYAWAY_RESERVED"
    ALLOCATED = "ALLOCATED"
    TRADE_IN_INTAKE = "TRADE_IN_INTAKE"
    REVERSED = "REVERSED"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    kyc_verified: bool
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class WatchModel(TypedDict):
    id: str
    brand: str
    reference_number: str
    display_name: str
    msrp_cents: int
    market_premium_bps: int
    allocation_controlled: bool
    lifecycle: str
    created_at: str
    updated_at: str
    version: int


class Watch(TypedDict):
    id: str
    model_id: str
    serial_number: str
    condition_grade: str
    has_box_papers: bool
    list_price_cents: int
    acquisition_cost_cents: Optional[int]
    is_loaner: bool
    source: str
    authentication_status: str
    status: str
    current_appraisal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Watchmaker(TypedDict):
    id: str
    display_name: str
    specialties: List[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    customer_id: str
    model_id: str
    priority_tier: str
    deposit_cents: int
    allocated_watch_id: Optional[str]
    offer_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict):
    id: str
    watch_id: str
    customer_id: str
    watchmaker_id: str
    service_type: str
    movement_complexity: str
    water_resistance_target_m: Optional[int]
    parts_cost_cents: int
    appt_start: str
    appt_end: str
    loaner_watch_id: Optional[str]
    loan_start: Optional[str]
    loan_end: Optional[str]
    quoted_cents: Optional[int]
    amount_paid_cents: int
    payment_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    watch_id: str
    purpose: str
    valuation_basis: str
    condition_grade_snapshot: str
    market_value_cents: int
    replacement_value_cents: int
    appraised_value_cents: int
    created_at: str
    updated_at: str
    version: int


class TradeInOffer(TypedDict):
    id: str
    customer_id: str
    incoming_brand: str
    incoming_reference: str
    serial_number: str
    est_model_msrp_cents: int
    condition_grade: str
    has_box_papers: bool
    disposition: str
    appraised_market_cents: int
    commission_rate_bps: Optional[int]
    quoted_credit_cents: int
    resulting_watch_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LayawayPlan(TypedDict):
    id: str
    customer_id: str
    watch_id: str
    deposit_cents: int
    use_store_credit: bool
    term_months: int
    first_due_at: str
    total_price_cents: int
    per_installment_cents: int
    final_installment_cents: int
    paid_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class ProvenanceEvent(TypedDict):
    id: str
    watch_id: str
    event_type: str
    detail: str
    actor_role: str
    created_at: str
