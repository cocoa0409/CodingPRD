"""Domain types: entity TypedDicts, status enums, role enum for the Surety Bond Underwriting API.

Every primary resource carries id, created_at, updated_at, and version (PRD §2.4); none is
creation-immutable, so all entities expose updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ---
class UserRole(str, Enum):
    UNDERWRITER = "Underwriter"
    SENIOR_UNDERWRITER = "SeniorUnderwriter"
    CLAIMS_EXAMINER = "ClaimsExaminer"


# --- Status enums ---
class SuretyProgramStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class CreditTier(str, Enum):
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    SUBSTANDARD = "SUBSTANDARD"


class IndemnityAgreementStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class BondType(str, Enum):
    BID = "BID"
    PERFORMANCE = "PERFORMANCE"
    PAYMENT = "PAYMENT"
    LICENSE_PERMIT = "LICENSE_PERMIT"
    FIDELITY = "FIDELITY"


class BondApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REFERRED = "REFERRED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    BOUND = "BOUND"


class DeclineReason(str, Enum):
    OBLIGEE_INELIGIBLE = "OBLIGEE_INELIGIBLE"
    CREDIT = "CREDIT"
    CAPACITY = "CAPACITY"
    OTHER = "OTHER"


class BondStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    RENEWED = "RENEWED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    INVESTIGATING = "INVESTIGATING"
    PAID = "PAID"
    DENIED = "DENIED"


class RiderType(str, Enum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    NAME_CHANGE = "NAME_CHANGE"


class RiderStatus(str, Enum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class ReinsuranceTreatyStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECAPTURED = "RECAPTURED"


class CancelMode(str, Enum):
    PRO_RATA = "PRO_RATA"
    SHORT_RATE = "SHORT_RATE"


class SettleOutcome(str, Enum):
    PAY = "PAY"
    DENY = "DENY"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.4) ---
class SuretyProgram(TypedDict):
    id: str
    name: str
    single_limit_cents: int
    aggregate_limit_cents: int
    referral_threshold_cents: int
    loss_alert_threshold_cents: int
    aggregate_committed_cents: int
    aggregate_available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Principal(TypedDict):
    id: str
    legal_name: str
    credit_score: int
    working_capital_cents: int
    credit_tier: str
    indemnity_on_file: bool
    created_at: str
    updated_at: str
    version: int


class IndemnityAgreement(TypedDict):
    id: str
    principal_id: str
    indemnitor_count: int
    required_signature_count: int
    collected_signature_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BondApplication(TypedDict):
    id: str
    principal_id: str
    program_id: str
    bond_type: str
    requested_penal_sum_cents: int
    term_months: int
    quoted_premium_rate_bps: int
    quoted_premium_cents: int
    status: str
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bond(TypedDict):
    id: str
    application_id: str
    principal_id: str
    program_id: str
    superseded_by_bond_id: Optional[str]
    bond_type: str
    penal_sum_cents: int
    term_months: int
    power_of_attorney_number: Optional[str]
    premium_rate_bps: int
    written_premium_cents: int
    earned_premium_cents: int
    ceded_penal_sum_cents: int
    net_retained_cents: int
    incurred_loss_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    bond_id: str
    claimant_name: str
    demand_cents: int
    reserve_cents: int
    paid_loss_cents: Optional[int]
    salvage_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict):
    id: str
    bond_id: str
    rider_type: str
    penal_sum_delta_cents: int
    additional_premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReinsuranceTreaty(TypedDict):
    id: str
    name: str
    cession_pct_bps: int
    treaty_capacity_cents: int
    ceded_committed_cents: int
    ceded_available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Cession(TypedDict):
    id: str
    bond_id: str
    treaty_id: str
    ceded_penal_sum_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
