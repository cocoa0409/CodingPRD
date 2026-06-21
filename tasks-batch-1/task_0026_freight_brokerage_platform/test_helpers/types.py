"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model. Append-only resources (Accessorial and
SmartWayAudit) omit `updated_at` and `version` because the PRD explicitly says
they are immutable once created (PRD §2.4).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Status enums (one per state-machine-bearing entity) ───────────


class ShipperStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"


class CarrierQualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class RejectionReasonCode(str, Enum):
    BAD_MC = "BAD_MC"
    BAD_USDOT = "BAD_USDOT"
    INSURANCE_EXPIRED = "INSURANCE_EXPIRED"
    SAFETY_OVER_THRESHOLD = "SAFETY_OVER_THRESHOLD"


class SmartWayTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ContractRateStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class QuoteRequestStatus(str, Enum):
    OPEN = "OPEN"
    AWARDED = "AWARDED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class RateMode(str, Enum):
    SPOT = "SPOT"
    CONTRACT = "CONTRACT"


class RequestedEquipment(str, Enum):
    DRY_VAN = "DRY_VAN"
    REEFER = "REEFER"
    FLATBED = "FLATBED"


class LoadStatus(str, Enum):
    AWARDED = "AWARDED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AccessorialCode(str, Enum):
    LUMPER = "LUMPER"
    TARPS = "TARPS"
    EXTRA_STOP = "EXTRA_STOP"
    REWEIGH = "REWEIGH"
    LAYOVER = "LAYOVER"
    DETENTION = "DETENTION"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class FactoringRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ADVANCED = "ADVANCED"
    REJECTED = "REJECTED"
    RECOURSE = "RECOURSE"


class DisputeClaimStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class DisputeClaimType(str, Enum):
    OVERCHARGE = "OVERCHARGE"
    DAMAGED_GOODS = "DAMAGED_GOODS"
    LATE_DELIVERY = "LATE_DELIVERY"
    MISSING_POD = "MISSING_POD"


class ResolutionKind(str, Enum):
    UPHELD = "UPHELD"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"


class SmartWayComplianceStatus(str, Enum):
    PASSING = "PASSING"
    AT_RISK = "AT_RISK"
    FAILING = "FAILING"


class UserRole(str, Enum):
    BROKER_OPS = "BrokerOps"
    SHIPPER = "Shipper"
    CARRIER = "Carrier"


# ─── Entity TypedDicts ─────────────────────────────────────────────


class Shipper(TypedDict):
    id: str
    legal_name: str
    billing_email: str
    credit_limit_cents: int
    open_ar_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict):
    id: str
    legal_name: str
    mc_number: str
    usdot_number: str
    smartway_tier: str
    insurance_expiry_utc: str
    qualification_status: str
    safety_score: float
    rejection_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractRate(TypedDict):
    id: str
    shipper_id: str
    lane_origin: str
    lane_destination: str
    rate_per_mile_cents: int
    fuel_surcharge_per_mile_cents: int
    detention_free_minutes: int
    detention_rate_per_hour_cents: int
    effective_from_utc: str
    effective_until_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QuoteRequest(TypedDict):
    id: str
    shipper_id: str
    lane_origin: str
    lane_destination: str
    distance_miles: int
    pickup_window_start_utc: str
    pickup_window_end_utc: str
    requested_equipment: str
    requires_smartway: bool
    rate_mode: str
    contract_rate_id: Optional[str]
    contract_rate_version: Optional[int]
    quoted_total_cents: int
    status: str
    expires_at_utc: str
    created_at: str
    updated_at: str
    version: int


class Load(TypedDict):
    id: str
    quote_request_id: str
    carrier_id: str
    agreed_rate_cents: int
    detention_charge_cents: int
    accessorial_total_cents: int
    pod_received_at_utc: Optional[str]
    actual_pickup_at_utc: Optional[str]
    actual_delivery_at_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only line item: PRD §2.4 says only id + created_at.
class Accessorial(TypedDict):
    id: str
    load_id: str
    code: str
    amount_cents: int
    note: Optional[str]
    created_at: str


class Invoice(TypedDict):
    id: str
    load_id: str
    total_cents: int
    factored: bool
    status: str
    amount_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class FactoringRequest(TypedDict):
    id: str
    invoice_id: str
    carrier_id: str
    factoring_fee_pct: float
    advance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisputeClaim(TypedDict):
    id: str
    invoice_id: str
    claim_type: str
    claimed_amount_cents: int
    resolution_amount_cents: Optional[int]
    resolution_kind: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only snapshot: PRD §2.4 says only id + created_at.
class SmartWayAudit(TypedDict):
    id: str
    shipper_id: str
    quarter_label: str
    total_loads: int
    smartway_loads: int
    smartway_ratio: float
    compliance_status: str
    created_at: str


class CreditRiskRead(TypedDict):
    score: int
    utilization_ratio: float
    late_count: int
    dispute_count: int
