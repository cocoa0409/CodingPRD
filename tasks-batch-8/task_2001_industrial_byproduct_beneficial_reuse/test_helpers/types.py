"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    GENERATOR = "Generator"
    OFFTAKER = "Offtaker"
    BROKER_OPS = "BrokerOps"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class MaterialType(str, Enum):
    FLY_ASH = "FLY_ASH"
    SLAG = "SLAG"
    GYPSUM = "GYPSUM"
    FOUNDRY_SAND = "FOUNDRY_SAND"
    BIOSOLIDS = "BIOSOLIDS"


class UseCase(str, Enum):
    CEMENT_ADDITIVE = "CEMENT_ADDITIVE"
    ROAD_BASE = "ROAD_BASE"
    SOIL_AMENDMENT = "SOIL_AMENDMENT"
    MINE_RECLAMATION = "MINE_RECLAMATION"


class PermitRegime(str, Enum):
    PERMIT = "PERMIT"
    NOTIFICATION = "NOTIFICATION"


class StreamStatus(str, Enum):
    DRAFT = "DRAFT"
    CHARACTERIZED = "CHARACTERIZED"
    ACTIVE = "ACTIVE"


class CharacterizationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class EligibilityStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class PermitStatus(str, Enum):
    FILED = "FILED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class FulfillmentStatus(str, Enum):
    UNMET = "UNMET"
    MET = "MET"


class CommitmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ShipmentStatus(str, Enum):
    BOOKED = "BOOKED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RECONDITIONING = "RECONDITIONING"
    VOIDED = "VOIDED"
    CANCELLED = "CANCELLED"
    DISPOSED = "DISPOSED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class CreditEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    REVERSAL = "REVERSAL"


class CreditTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).


class Generator(TypedDict):
    id: str
    legal_name: str
    hq_state_code: str
    contact_email: str
    total_credits: float
    credit_tier: str
    created_at: str
    updated_at: str
    version: int


class Offtaker(TypedDict):
    id: str
    legal_name: str
    hq_state_code: str
    receiving_state_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class ByproductStream(TypedDict):
    id: str
    generator_id: str
    material_type: str
    declared_moisture_pct: float
    expected_tons_per_month: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CharacterizationProfile(TypedDict):
    id: str
    stream_id: str
    lab_name: str
    sampled_on: str
    ph: float
    arsenic_ppm: float
    lead_ppm: float
    moisture_pct_measured: float
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReuseEligibility(TypedDict):
    id: str
    stream_id: str
    state_code: str
    use_case: str
    valid_from: str
    valid_until: str
    filed_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StatePermit(TypedDict):
    id: str
    state_code: str
    material_type: str
    regime: str
    permit_number: str
    issued_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyAgreement(TypedDict):
    id: str
    generator_id: str
    stream_id: str
    committed_monthly_tons: int
    revenue_share_pct_to_generator: float
    freight_share_pct_to_generator: float
    term_start: str
    term_end: str
    booked_month_to_date_tons: float
    delivered_month_to_date_tons: float
    counter_month: str
    fulfillment_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OfftakeCommitment(TypedDict):
    id: str
    offtaker_id: str
    stream_id: str
    destination_state_code: str
    committed_monthly_tons: int
    max_moisture_pct: float
    max_arsenic_ppm: float
    accepted_month_to_date_tons: float
    cumulative_rejected_tons: float
    counter_month: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    supply_agreement_id: str
    offtake_commitment_id: str
    pickup_date: str
    distance_miles: int
    gross_tons: float
    loading_moisture_pct: float
    destination_moisture_pct: Optional[float]
    destination_arsenic_ppm: Optional[float]
    price_at_pickup_cents_per_ton: int
    price_at_acceptance_cents_per_ton: Optional[int]
    freight_total_cents: int
    generator_freight_share_cents: int
    broker_freight_share_cents: int
    provisional_settlement_cents: int
    moisture_deduction_pct: Optional[float]
    net_billable_tons: Optional[float]
    final_gross_revenue_cents: Optional[int]
    final_generator_share_cents: Optional[int]
    final_broker_share_cents: Optional[int]
    generator_net_payout_cents: Optional[int]
    status: str
    rejection_reason: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageFacility(TypedDict):
    id: str
    state_code: str
    material_types_allowed: List[str]
    capacity_tons: int
    current_inventory_tons: float
    created_at: str
    updated_at: str
    version: int


class StorageReservation(TypedDict):
    id: str
    facility_id: str
    stream_id: str
    start_date: str
    end_date: str
    tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger records (PRD §2.5): only id + created_at, never
# updated_at or version.


class MarketPriceIndex(TypedDict):
    id: str
    material_type: str
    region_code: str
    effective_from: str
    price_cents_per_ton: int
    published_by_user_id: str
    created_at: str


class SustainabilityCreditEntry(TypedDict):
    id: str
    generator_id: str
    shipment_id: str
    entry_type: str
    period: str
    tons_credited: float
    credits: float
    created_at: str
