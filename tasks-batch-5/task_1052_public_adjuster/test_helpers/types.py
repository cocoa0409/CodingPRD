"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Public Adjuster & Claim Advocacy PRD. Every persisted resource
carries id, created_at, updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    PUBLIC_ADJUSTER = "PublicAdjuster"
    FIRM_PRINCIPAL = "FirmPrincipal"
    CLIENT = "Client"
    CARRIER = "Carrier"
    SYSTEM = "System"


# ------------------------------------------------------------------------- statuses
class AdjusterStatus(str, Enum):
    ACTIVE = "ACTIVE"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    RESCINDED = "RESCINDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    NEGOTIATING = "NEGOTIATING"
    OFFER_RECEIVED = "OFFER_RECEIVED"
    IN_APPRAISAL = "IN_APPRAISAL"
    SETTLED = "SETTLED"
    PAID = "PAID"
    WITHDRAWN = "WITHDRAWN"


class SupplementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class AppraisalStatus(str, Enum):
    INVOKED = "INVOKED"
    APPRAISERS_NAMED = "APPRAISERS_NAMED"
    UMPIRE_SELECTED = "UMPIRE_SELECTED"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CLEARED = "CLEARED"
    REVERSED = "REVERSED"


class DisbursementStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    HELD = "HELD"
    VOIDED = "VOIDED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


# -------------------------------------------------------------------- input enums
class PolicyType(str, Enum):
    HO3 = "HO3"
    HO5 = "HO5"
    COMMERCIAL = "COMMERCIAL"
    FLOOD = "FLOOD"


class PerilType(str, Enum):
    WIND = "WIND"
    WATER = "WATER"
    FIRE = "FIRE"
    HAIL = "HAIL"
    THEFT = "THEFT"


class PaymentType(str, Enum):
    INITIAL = "INITIAL"
    SUPPLEMENT = "SUPPLEMENT"
    APPRAISAL_AWARD = "APPRAISAL_AWARD"


class DisputeType(str, Enum):
    FEE = "FEE"
    SERVICE = "SERVICE"
    LICENSING = "LICENSING"


class DisputeRaisedBy(str, Enum):
    CLIENT = "CLIENT"
    CARRIER = "CARRIER"


# --------------------------------------------------------------------- entities
class Adjuster(TypedDict):
    id: str
    full_name: str
    firm_name: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    adjuster_id: str
    state_code: str
    license_number: str
    effective_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    email: str
    mailing_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    client_id: str
    carrier_name: str
    policy_number: str
    policy_type: str
    coverage_limit_cents: int
    deductible_cents: int
    effective_date: str
    expiry_date: str
    status: str
    committed_cents: int
    remaining_limit_cents: int
    forward_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    client_id: str
    adjuster_id: str
    loss_state_code: str
    fee_pct: float
    statutory_cap_pct: float
    prior_advance_cents: int
    advance_recouped_cents: int
    signed_at: Optional[str]
    rescission_deadline_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    contract_id: str
    date_of_loss: str
    loss_state_code: str
    peril_type: str
    pa_rcv_estimate_cents: int
    depreciation_pct: float
    pa_acv_estimate_cents: int
    carrier_offer_cents: int
    pa_counter_cents: int
    negotiation_round: int
    inspection_start: Optional[str]
    inspection_end: Optional[str]
    settlement_amount_cents: int
    settled_at: Optional[str]
    amount_recovered_cents: int
    provisional_fee_cents: int
    final_fee_cents: int
    accepted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplement(TypedDict):
    id: str
    claim_id: str
    amount_cents: int
    reason: str
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    claim_id: str
    pa_appraiser_name: Optional[str]
    carrier_appraiser_name: Optional[str]
    umpire_name: Optional[str]
    pa_appraiser_amount_cents: int
    carrier_appraiser_amount_cents: int
    award_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    claim_id: str
    amount_cents: int
    payment_type: str
    received_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    claim_id: str
    payment_id: str
    gross_cents: int
    fee_cents: int
    advance_recoup_cents: int
    client_cents: int
    released_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    claim_id: str
    dispute_type: str
    raised_by: str
    description: str
    resolution: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
