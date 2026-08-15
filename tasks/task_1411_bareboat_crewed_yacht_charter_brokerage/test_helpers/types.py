"""Domain types: entity TypedDicts, status enums, role enum for the
bareboat & crewed yacht charter brokerage PRD."""
from enum import Enum
from typing import Optional, TypedDict


class OperatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BrokerType(str, Enum):
    CENTRAL_AGENT = "CENTRAL_AGENT"
    RETAIL_BROKER = "RETAIL_BROKER"
    BOTH = "BOTH"


class QualificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"


class ResumeClass(str, Enum):
    NONE = "NONE"
    COASTAL = "COASTAL"
    OFFSHORE = "OFFSHORE"
    OCEAN = "OCEAN"


class CharterType(str, Enum):
    BAREBOAT = "BAREBOAT"
    CREWED = "CREWED"


class PricingMode(str, Enum):
    PRO_RATA = "PRO_RATA"
    WEEKLY_PLUS_DAILY = "WEEKLY_PLUS_DAILY"


class YachtStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class BlockType(str, Enum):
    MAINTENANCE = "MAINTENANCE"
    OPERATOR_HOLD = "OPERATOR_HOLD"
    CHARTER = "CHARTER"


class AvailabilityBlockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class CharterRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class AgreementStatus(str, Enum):
    PENDING_SIGNATURES = "PENDING_SIGNATURES"
    SIGNED = "SIGNED"
    IN_PREP = "IN_PREP"
    UNDERWAY = "UNDERWAY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class FundsStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    FULLY_FUNDED = "FULLY_FUNDED"
    SETTLING = "SETTLING"
    SETTLED = "SETTLED"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"


class EscrowStatus(str, Enum):
    OPEN = "OPEN"
    SETTLING = "SETTLING"
    CLOSED = "CLOSED"


class MovementType(str, Enum):
    CLIENT_FUND = "CLIENT_FUND"
    RELEASE_TO_OPERATOR = "RELEASE_TO_OPERATOR"
    RELEASE_TO_CENTRAL_AGENT = "RELEASE_TO_CENTRAL_AGENT"
    RELEASE_TO_RETAIL_BROKER = "RELEASE_TO_RETAIL_BROKER"
    REFUND_TO_CLIENT = "REFUND_TO_CLIENT"


class MoneyBucket(str, Enum):
    CHARTER_FEE = "CHARTER_FEE"
    APA = "APA"
    DEPOSIT = "DEPOSIT"
    GRATUITY = "GRATUITY"


class ExpenseBucket(str, Enum):
    APA = "APA"
    DAMAGE_CLAIM = "DAMAGE_CLAIM"


class ExpenseStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"


class LegStatus(str, Enum):
    PLANNED = "PLANNED"
    PERMITTED = "PERMITTED"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class InsuranceStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class CommissionBasis(str, Enum):
    CHARTER_FEE = "CHARTER_FEE"
    CANCELLATION_PENALTY = "CANCELLATION_PENALTY"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    OPERATOR = "Operator"
    CLIENT = "Client"
    RETAIL_BROKER = "RetailBroker"
    CENTRAL_AGENT = "CentralAgent"


class Operator(TypedDict):
    id: str
    name: str
    home_port: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Broker(TypedDict):
    id: str
    display_name: str
    broker_type: str
    license_no: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    email: str
    qualification_status: str
    resume_class: Optional[str]
    skippered_hours: Optional[int]
    resume_submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Yacht(TypedDict):
    id: str
    operator_id: str
    listing_central_agent_id: str
    name: str
    charter_type: str
    home_port: str
    capacity_berths: int
    weekly_base_rate_cents: int
    min_charter_days: int
    required_resume_class: str
    security_deposit_cents: int
    pricing_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AvailabilityBlock(TypedDict):
    id: str
    yacht_id: str
    charter_agreement_id: Optional[str]
    block_type: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CharterRequest(TypedDict):
    id: str
    client_id: str
    yacht_id: str
    retail_broker_id: Optional[str]
    rebooked_from_request_id: Optional[str]
    start_date: str
    end_date: str
    guests_count: int
    quoted_charter_fee_cents: Optional[int]
    apa_pct: Optional[float]
    gratuity_pledged_cents: Optional[int]
    retail_pct_bps: Optional[int]
    round_count: int
    offer_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CharterAgreement(TypedDict):
    id: str
    charter_request_id: str
    client_id: str
    yacht_id: str
    operator_id: str
    retail_broker_id: Optional[str]
    central_agent_id: str
    start_date: str
    end_date: str
    charter_fee_cents: int
    apa_pct: float
    apa_amount_cents: int
    security_deposit_cents: int
    gratuity_pledged_cents: int
    retail_pct_bps: int
    pricing_mode: str
    signing_due_cents: int
    final_due_cents: int
    client_signed_at: Optional[str]
    central_agent_signed_at: Optional[str]
    days_before_start: Optional[int]
    cancellation_penalty_cents: Optional[int]
    status: str
    funds_status: str
    created_at: str
    updated_at: str
    version: int


class EscrowAccount(TypedDict):
    id: str
    charter_agreement_id: str
    held_charter_fee_cents: int
    held_apa_cents: int
    held_deposit_cents: int
    held_gratuity_cents: int
    total_funded_cents: int
    total_released_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EscrowMovement(TypedDict):
    # Ledger-style resource: carries only id + created_at (no updated_at/version).
    id: str
    created_at: str
    escrow_account_id: str
    movement_type: str
    bucket: str
    amount_cents: int
    memo: str


class ExpenseEntry(TypedDict):
    id: str
    charter_agreement_id: str
    bucket: str
    description: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ItineraryLeg(TypedDict):
    id: str
    charter_agreement_id: str
    seq_no: int
    port_name: str
    arrival_date: str
    departure_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PortPermit(TypedDict):
    id: str
    itinerary_leg_id: str
    port_authority_ref: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict):
    id: str
    charter_agreement_id: str
    insurer_name: str
    policy_no: str
    coverage_amount_cents: int
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict):
    # Ledger-style resource: carries only id + created_at (no updated_at/version).
    id: str
    created_at: str
    charter_agreement_id: str
    basis: str
    basis_amount_cents: int
    commission_total_cents: int
    retail_share_cents: int
    central_share_cents: int
