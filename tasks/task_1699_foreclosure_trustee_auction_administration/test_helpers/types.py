"""Domain types: entity TypedDicts, status enums, role enum (PRD §3, §4)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    TRUSTEE_ADMIN = "TrusteeAdmin"
    CASE_MANAGER = "CaseManager"
    AUCTIONEER = "Auctioneer"
    BENEFICIARY = "Beneficiary"
    THIRD_PARTY_BIDDER = "ThirdPartyBidder"


class BeneficiaryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CaseLifecycle(str, Enum):
    REFERRED = "REFERRED"
    NOD_RECORDED = "NOD_RECORDED"
    NOTS_RECORDED = "NOTS_RECORDED"
    SALE_SCHEDULED = "SALE_SCHEDULED"
    SOLD = "SOLD"
    DEED_RECORDED = "DEED_RECORDED"
    CLOSED = "CLOSED"
    REINSTATED = "REINSTATED"
    PAID_OFF = "PAID_OFF"
    CANCELLED = "CANCELLED"


class HoldStatus(str, Enum):
    CLEAR = "CLEAR"
    BANKRUPTCY_STAY = "BANKRUPTCY_STAY"
    LITIGATION_HOLD = "LITIGATION_HOLD"


class NodStatus(str, Enum):
    RECORDED = "RECORDED"
    RESCINDED = "RESCINDED"


class NotsStatus(str, Enum):
    RECORDED = "RECORDED"
    PUBLICATION_COMPLETE = "PUBLICATION_COMPLETE"
    SALE_SCHEDULED = "SALE_SCHEDULED"
    CONCLUDED = "CONCLUDED"
    VOIDED = "VOIDED"


class PublicationStatus(str, Enum):
    RUN = "RUN"
    AFFIDAVIT_FILED = "AFFIDAVIT_FILED"


class SaleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class WinnerType(str, Enum):
    THIRD_PARTY = "THIRD_PARTY"
    BENEFICIARY = "BENEFICIARY"


class RegistrationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    DEPOSIT_APPLIED = "DEPOSIT_APPLIED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"


class InstructionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class QuoteType(str, Enum):
    REINSTATEMENT = "REINSTATEMENT"
    PAYOFF = "PAYOFF"


class QuoteStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class AdvanceCategory(str, Enum):
    PUBLICATION = "PUBLICATION"
    RECORDING = "RECORDING"
    POSTING = "POSTING"
    LEGAL = "LEGAL"
    PROPERTY_PRESERVATION = "PROPERTY_PRESERVATION"
    OTHER = "OTHER"


class AdvanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REIMBURSED = "REIMBURSED"


class StayType(str, Enum):
    BANKRUPTCY_CHAPTER_7 = "BANKRUPTCY_CHAPTER_7"
    BANKRUPTCY_CHAPTER_11 = "BANKRUPTCY_CHAPTER_11"
    BANKRUPTCY_CHAPTER_13 = "BANKRUPTCY_CHAPTER_13"
    LITIGATION_HOLD = "LITIGATION_HOLD"


class StayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class DeedStatus(str, Enum):
    DRAFTED = "DRAFTED"
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    EXPIRED = "EXPIRED"


class ClaimantType(str, Enum):
    JUNIOR_LIENHOLDER = "JUNIOR_LIENHOLDER"
    BORROWER = "BORROWER"
    JUDGMENT_CREDITOR = "JUDGMENT_CREDITOR"


class RecipientType(str, Enum):
    TRUSTEE_FEE = "TRUSTEE_FEE"
    BENEFICIARY_COST_REIMBURSEMENT = "BENEFICIARY_COST_REIMBURSEMENT"
    BENEFICIARY_DEBT_PAYOFF = "BENEFICIARY_DEBT_PAYOFF"
    CLAIMANT = "CLAIMANT"
    BORROWER_RESIDUE = "BORROWER_RESIDUE"


class DisbursementStatus(str, Enum):
    CLEARED = "CLEARED"
    REVERSED = "REVERSED"


class DistributionMethod(str, Enum):
    STATUTORY_PRIORITY = "STATUTORY_PRIORITY"
    PRO_RATA = "PRO_RATA"


# --- Entity records (PRD §2.4: every primary resource carries id, created_at,
# updated_at, version; Postponement and Bid are immutable ledger entries that
# carry only id and created_at) ---


class Beneficiary(TypedDict, total=False):
    id: str
    name: str
    reference_code: str
    contact_email: str
    status: str
    total_outstanding_advances_cents: int
    created_at: str
    updated_at: str
    version: int


class ForeclosureCase(TypedDict, total=False):
    id: str
    beneficiary_id: str
    loan_reference: str
    borrower_name: str
    property_address: str
    county_code: str
    unpaid_principal_balance_cents: int
    monthly_payment_cents: int
    months_in_arrears: int
    late_fee_per_month_cents: int
    note_rate_pct: float
    last_interest_paid_date: str
    prepayment_penalty_applies: bool
    distribution_method: str
    lifecycle_status: str
    hold_status: str
    reinstatement_deadline_date: Optional[str]
    undistributed_surplus_cents: int
    created_at: str
    updated_at: str
    version: int


class NoticeOfDefault(TypedDict, total=False):
    id: str
    foreclosure_case_id: str
    recording_date: str
    instrument_number: str
    status: str
    rescinded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NoticeOfTrusteeSale(TypedDict, total=False):
    id: str
    foreclosure_case_id: str
    recording_date: str
    instrument_number: str
    status: str
    postponement_count: int
    first_publication_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Publication(TypedDict, total=False):
    id: str
    notice_of_trustee_sale_id: str
    run_date: str
    newspaper_name: str
    run_index: int
    status: str
    affidavit_filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuctionSale(TypedDict, total=False):
    id: str
    foreclosure_case_id: str
    notice_of_trustee_sale_id: str
    venue_name: str
    scheduled_sale_start_at: str
    status: str
    opening_bid_cents: Optional[int]
    winner_type: Optional[str]
    winning_bid_cents: Optional[int]
    winning_bidder_registration_id: Optional[str]
    total_debt_at_close_cents: Optional[int]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Postponement(TypedDict, total=False):
    """Immutable ledger entry: id + created_at only, no updated_at/version."""

    id: str
    auction_sale_id: str
    prior_sale_start_at: str
    new_sale_start_at: str
    reason: str
    announced_via: str
    created_at: str


class BidderRegistration(TypedDict, total=False):
    id: str
    auction_sale_id: str
    bidder_name: str
    bidder_email: str
    deposit_cents: int
    required_deposit_cents: Optional[int]
    status: str
    disqualification_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    """Immutable ledger entry: id + created_at only, no updated_at/version."""

    id: str
    auction_sale_id: str
    bidder_registration_id: str
    amount_cents: int
    placed_at: str
    created_at: str


class BiddingInstruction(TypedDict, total=False):
    id: str
    foreclosure_case_id: str
    opening_bid_cents: int
    max_bid_cents: int
    strategy: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    foreclosure_case_id: str
    quote_type: str
    good_through_date: str
    arrears_cents: int
    late_fees_cents: int
    costs_cents: int
    interest_cents: int
    trustee_fee_cents: int
    prepayment_penalty_cents: int
    total_cents: int
    status: str
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostAdvance(TypedDict, total=False):
    id: str
    foreclosure_case_id: str
    category: str
    amount_cents: int
    incurred_date: str
    status: str
    denial_reason: Optional[str]
    submitted_by_beneficiary_id: str
    created_at: str
    updated_at: str
    version: int


class StayOrder(TypedDict, total=False):
    id: str
    foreclosure_case_id: str
    stay_type: str
    court_case_number: str
    filed_at: str
    status: str
    released_at: Optional[str]
    release_court_order_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrusteesDeed(TypedDict, total=False):
    id: str
    auction_sale_id: str
    grantee_name: str
    status: str
    recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurplusClaim(TypedDict, total=False):
    id: str
    foreclosure_case_id: str
    claimant_name: str
    claimant_type: str
    priority_rank: int
    claimed_amount_cents: int
    filed_date: str
    approved_amount_cents: Optional[int]
    paid_cents: int
    status: str
    denial_reason: Optional[str]
    filed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    foreclosure_case_id: str
    surplus_claim_id: Optional[str]
    recipient_type: str
    amount_cents: int
    distribution_run_index: int
    status: str
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
