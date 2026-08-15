"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# --- Role enum (PRD §2.1) ---------------------------------------------------


class UserRole(str, Enum):
    BOARD_ADMIN = "BoardAdmin"
    PHYSICIAN = "Physician"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --- Status enums (PRD §3) --------------------------------------------------


class PartnershipStatus(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    PARTNER_TRACK = "PARTNER_TRACK"
    SHAREHOLDER = "SHAREHOLDER"
    EXITING = "EXITING"
    EXITED = "EXITED"


class Standing(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class SeatClass(str, Enum):
    CLINICAL = "CLINICAL"
    AT_LARGE = "AT_LARGE"
    EX_OFFICIO = "EX_OFFICIO"


class BoardSeatStatus(str, Enum):
    VACANT = "VACANT"
    FILLED = "FILLED"


class CommitteeType(str, Enum):
    QUALITY = "QUALITY"
    FINANCE = "FINANCE"
    COMPENSATION = "COMPENSATION"


class CommitteeRole(str, Enum):
    CHAIR = "CHAIR"
    MEMBER = "MEMBER"


class ApprovalThreshold(str, Enum):
    SIMPLE_MAJORITY = "SIMPLE_MAJORITY"
    SUPERMAJORITY = "SUPERMAJORITY"


class CommitteeStatus(str, Enum):
    CHARTERED = "CHARTERED"
    ACTIVE = "ACTIVE"
    IMPAIRED = "IMPAIRED"
    DISSOLVED = "DISSOLVED"


class TargetTier(str, Enum):
    PARTNER_TRACK = "PARTNER_TRACK"
    SHAREHOLDER = "SHAREHOLDER"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class MotionType(str, Enum):
    CHARTER_AMENDMENT = "CHARTER_AMENDMENT"
    COMP_POLICY = "COMP_POLICY"
    CAPITAL_CALL = "CAPITAL_CALL"
    DISTRIBUTION = "DISTRIBUTION"
    BUYOUT_APPROVAL = "BUYOUT_APPROVAL"
    MERGER = "MERGER"


class MotionStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    OPEN = "OPEN"
    TABLED = "TABLED"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class VoteChoice(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"


class VoteStatus(str, Enum):
    CAST = "CAST"
    VOIDED = "VOIDED"


class CapitalCallStatus(str, Enum):
    APPROVED = "APPROVED"
    BILLED = "BILLED"
    COLLECTED = "COLLECTED"
    PARTIALLY_DEFAULTED = "PARTIALLY_DEFAULTED"


class AssessmentStatus(str, Enum):
    BILLED = "BILLED"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"


class DistributionMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    SENIORITY_TIERED = "SENIORITY_TIERED"


class AllocationStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"
    CANCELLED = "CANCELLED"


class DistributionStatus(str, Enum):
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class TriggerType(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    RETIREMENT = "RETIREMENT"
    TERMINATION = "TERMINATION"
    DEATH = "DEATH"


class ExitValuationStatus(str, Enum):
    INITIATED = "INITIATED"
    APPRAISED = "APPRAISED"
    DISPUTED = "DISPUTED"
    ARBITRATION = "ARBITRATION"
    FINALIZED = "FINALIZED"


class COIStatus(str, Enum):
    FILED = "FILED"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class MergerStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DUE_DILIGENCE = "DUE_DILIGENCE"
    NEGOTIATION = "NEGOTIATION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    TERMINATED = "TERMINATED"


# --- Entity TypedDicts ------------------------------------------------------
# All entities carry id / created_at / updated_at / version (PRD §2.4).


class GovernancePolicy(TypedDict, total=False):
    id: str
    singleton_key: str
    total_shares_authorized: int
    board_quorum_count: int
    supermajority_num: int
    supermajority_den: int
    voting_window_days: int
    offer_window_days: int
    buy_in_base_shareholder_cents: int
    buy_in_base_partner_cents: int
    tenure_discount_pct_per_year: float
    max_tenure_discount_pct: float
    min_buy_in_cents: int
    fiscal_year_start_month: int
    late_fee_pct: float
    delinquency_grace_days: int
    minority_discount_pct: float
    ebitda_multiple: float
    trailing_ebitda_cents: int
    bonus_pool_pct: float
    distribution_cap_pct: float
    seniority_carve_pct: float
    seniority_tier_years: int
    max_dispute_rounds: int
    max_committee_members: int
    comp_policy_version: int
    treasury_shares: int
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict, total=False):
    id: str
    full_name: str
    hire_date: str
    specialty: str
    founding_shareholder: bool
    initial_shares: int
    partnership_status: str
    standing: str
    shares_held: int
    capital_account_balance_cents: int
    ownership_pct: float
    tenure_years: int
    created_at: str
    updated_at: str
    version: int


class BoardSeat(TypedDict, total=False):
    id: str
    seat_label: str
    seat_class: str
    status: str
    current_holder_physician_id: Optional[str]
    current_term_start: Optional[str]
    current_term_end: Optional[str]
    next_holder_physician_id: Optional[str]
    next_term_start: Optional[str]
    next_term_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeMember(TypedDict, total=False):
    physician_id: str
    committee_role: str
    added_at: str


class Committee(TypedDict, total=False):
    id: str
    name: str
    committee_type: str
    quorum_count: int
    approval_threshold: str
    charter_version: int
    members: List[CommitteeMember]
    active_member_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BuyInOffer(TypedDict, total=False):
    id: str
    physician_id: str
    target_tier: str
    share_grant: int
    installment_count: int
    offered_at: str
    acceptance_deadline: str
    tenure_years_at_offer: int
    discount_pct_applied: float
    proration_twelfths: int
    final_amount_cents: int
    installment_schedule_cents: List[int]
    paid_installment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Motion(TypedDict, total=False):
    id: str
    motion_type: str
    sponsor_physician_id: str
    committee_id: Optional[str]
    supersedes_motion_id: Optional[str]
    payload: dict
    threshold_type: str
    status: str
    eligible_voter_ids: List[str]
    recused_physician_ids: List[str]
    eligible_voter_count: int
    required_votes: int
    votes_for: int
    votes_against: int
    votes_abstain: int
    opened_at: Optional[str]
    closes_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vote(TypedDict, total=False):
    id: str
    motion_id: str
    physician_id: str
    vote_choice: str
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapitalCall(TypedDict, total=False):
    id: str
    motion_id: str
    purpose: str
    total_amount_cents: int
    due_date: str
    assessed_total_cents: int
    collected_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalCallAssessment(TypedDict, total=False):
    id: str
    capital_call_id: str
    physician_id: str
    shares_at_billing: int
    assessed_cents: int
    late_fee_cents: int
    paid_cents: int
    total_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionAllocation(TypedDict, total=False):
    physician_id: str
    allocated_cents: int
    status: str


class Distribution(TypedDict, total=False):
    id: str
    motion_id: str
    total_amount_cents: int
    method: str
    fiscal_net_income_before_bonus_cents: int
    bonus_accrual_cents: int
    distributable_cap_cents: int
    allocations: List[DistributionAllocation]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExitValuation(TypedDict, total=False):
    id: str
    physician_id: str
    trigger_type: str
    ownership_pct_snapshot: float
    provisional_value_cents: int
    appraised_practice_value_cents: int
    final_value_cents: int
    appraisal_final: bool
    dispute_rounds: int
    approving_motion_id: Optional[str]
    payment_schedule_cents: List[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class COIDisclosure(TypedDict, total=False):
    id: str
    physician_id: str
    related_motion_id: Optional[str]
    description: str
    status: str
    reviewed_by: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MergerProposal(TypedDict, total=False):
    id: str
    counterparty_name: str
    exchange_ratio_x1000: int
    cash_consideration_cents: int
    diligence_note: Optional[str]
    deciding_motion_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
