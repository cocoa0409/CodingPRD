"""Domain types: entity TypedDicts, status enums, role enum.

All field names and status values are taken verbatim from the PRD. Entities with
the full common-field set carry id/created_at/updated_at/version; the two append-only
artifacts (EscrowTransaction, TaxRecord) carry only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────
class UserRole(str, Enum):
    CLIENT = "Client"
    FREELANCER = "Freelancer"
    ARBITRATOR = "Arbitrator"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums (PRD §3) ────────────────────────────────────────────
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FreelancerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FeeTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class JobPostingStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    AWARDED = "AWARDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProposalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"


class MilestoneStatus(str, Enum):
    DRAFT = "DRAFT"
    FUNDED = "FUNDED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    RELEASED = "RELEASED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class TimeLogStatus(str, Enum):
    LOGGED = "LOGGED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class EscrowTxnType(str, Enum):
    FUND = "FUND"
    RELEASE = "RELEASE"
    REFUND = "REFUND"


class EscrowTxnStatus(str, Enum):
    HELD = "HELD"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_ARBITRATION = "UNDER_ARBITRATION"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class DisputeResolution(str, Enum):
    FREELANCER_FAVOR = "FREELANCER_FAVOR"
    CLIENT_FAVOR = "CLIENT_FAVOR"
    SPLIT = "SPLIT"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    HELD_NO_TAX_ID = "HELD_NO_TAX_ID"


class ActorRole(str, Enum):
    CLIENT = "CLIENT"
    FREELANCER = "FREELANCER"


class TaxBasis(str, Enum):
    GROSS_BASIS = "GROSS_BASIS"
    NET_BASIS = "NET_BASIS"


class TaxFormStatus(str, Enum):
    BELOW_THRESHOLD = "BELOW_THRESHOLD"
    GENERATED = "GENERATED"


# ─── Entity TypedDicts (common_fields: true) ──────────────────────────
class Client(TypedDict):
    id: str
    display_name: str
    email: str
    wallet_balance_cents: int
    escrow_held_cents: int
    lifetime_funded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Freelancer(TypedDict):
    id: str
    display_name: str
    email: str
    tax_id_on_file: bool
    skills: List[str]
    lifetime_earnings_cents: int
    lifetime_gross_billed_cents: int
    completed_contract_count: int
    dispute_loss_count: int
    reputation_score: float
    fee_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class JobPosting(TypedDict):
    id: str
    client_id: str
    title: str
    billing_type: str
    budget_cents: int
    required_skills: List[str]
    status: str
    proposal_count: int
    awarded_proposal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict):
    id: str
    job_posting_id: str
    freelancer_id: str
    bid_amount_cents: int
    cover_letter: str
    round_count: int
    last_actor: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    client_id: str
    freelancer_id: str
    proposal_id: str
    billing_type: str
    sow_text: Optional[str]
    agreed_amount_cents: int
    hourly_cap_hours: Optional[float]
    status: str
    total_released_cents: int
    total_refunded_cents: int
    open_milestone_count: int
    open_dispute_count: int
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    contract_id: str
    title: str
    amount_cents: int
    funded_cents: int
    released_gross_cents: int
    refunded_cents: int
    ordinal: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TimeLog(TypedDict):
    id: str
    contract_id: str
    milestone_id: str
    freelancer_id: str
    work_date: str
    start_minute: int
    end_minute: int
    billable_minutes: int
    memo: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    contract_id: str
    milestone_id: str
    raised_by: str
    reason: str
    claimed_release_cents: int
    arbitrator_award_cents: Optional[int]
    resolution: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    freelancer_id: str
    milestone_id: str
    gross_cents: int
    platform_fee_cents: int
    net_cents: int
    tax_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict):
    id: str
    contract_id: str
    author_role: str
    freelancer_id: str
    rating: int
    comment: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only artifacts (common_fields: false) ─────────────────────
# EscrowTransaction and TaxRecord carry ONLY id + created_at — no
# updated_at, no version (PRD §2.4).
class EscrowTransaction(TypedDict):
    id: str
    created_at: str
    contract_id: str
    milestone_id: str
    txn_type: str
    amount_cents: int
    status: str


class TaxRecord(TypedDict):
    id: str
    created_at: str
    freelancer_id: str
    tax_year: int
    reportable_gross_cents: int
    is_reportable: bool
    form_status: str
