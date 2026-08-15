"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CLAIMS_EXAMINER = "ClaimsExaminer"
    ACTUARIAL_ANALYST = "ActuarialAnalyst"
    PEER_REVIEWER = "PeerReviewer"
    APPOINTED_ACTUARY = "AppointedActuary"


class LineOfBusiness(str, Enum):
    COMMERCIAL_AUTO = "COMMERCIAL_AUTO"
    GENERAL_LIABILITY = "GENERAL_LIABILITY"
    WORKERS_COMP = "WORKERS_COMP"
    PROPERTY = "PROPERTY"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class TransactionType(str, Enum):
    PAYMENT = "PAYMENT"
    PAYMENT_REVERSAL = "PAYMENT_REVERSAL"
    CASE_RESERVE_SET = "CASE_RESERVE_SET"


class Basis(str, Enum):
    PAID = "PAID"
    INCURRED = "INCURRED"


class RunMethod(str, Enum):
    CHAIN_LADDER = "CHAIN_LADDER"
    BORNHUETTER_FERGUSON = "BORNHUETTER_FERGUSON"


class PatternStatus(str, Enum):
    DRAFT = "DRAFT"
    SELECTED = "SELECTED"
    WITHDRAWN = "WITHDRAWN"


class StudyStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"
    WITHDRAWN = "WITHDRAWN"


class OpinionScope(str, Enum):
    REASONABLE = "REASONABLE"
    DEFICIENT = "DEFICIENT"
    REDUNDANT = "REDUNDANT"
    NO_OPINION = "NO_OPINION"


class OpinionStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# --- Entity TypedDicts -------------------------------------------------------
# All primary resources carry id + created_at + updated_at + version (PRD §2.4).


class ReservingSegment(TypedDict, total=False):
    id: str
    name: str
    line_of_business: str
    large_loss_threshold_cents: int
    max_range_width_pct: float
    benchmark_open_severity_cents: int
    last_closed_quarter: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CatastropheEvent(TypedDict, total=False):
    id: str
    segment_id: str
    name: str
    start_date: str
    end_date: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    segment_id: str
    claim_number: str
    accident_date: str
    report_date: str
    catastrophe_event_id: Optional[str]
    status: str
    paid_to_date_cents: int
    case_outstanding_cents: int
    reported_incurred_cents: int
    is_large_loss: bool
    is_segregated: bool
    adequacy_ratio_development: Optional[float]
    adequacy_ratio_benchmark: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ClaimTransaction(TypedDict, total=False):
    # Append-only event-log entry (PRD §2.4): ONLY id + created_at are
    # system-managed; updated_at and version are absent by contract.
    id: str
    claim_id: str
    type: str
    transaction_date: str
    effective_quarter: str
    amount_cents: Optional[int]
    case_value_cents: Optional[int]
    created_at: str


class TriangleCell(TypedDict):
    accident_quarter: str
    dev_quarter: int
    amount_cents: int


class LossTriangle(TypedDict, total=False):
    id: str
    segment_id: str
    basis: str
    valuation_quarter: str
    cells: List[TriangleCell]
    large_loss_cells: List[TriangleCell]
    is_stale: bool
    created_at: str
    updated_at: str
    version: int


class DevelopmentPattern(TypedDict, total=False):
    id: str
    segment_id: str
    basis: str
    valuation_quarter: str
    effective_from_quarter: str
    effective_to_quarter: str
    selected_factors: List[float]
    tail_factor: float
    status: str
    created_at: str
    updated_at: str
    version: int


class UltimateByAccidentQuarter(TypedDict):
    accident_quarter: str
    age_at_valuation: int
    cdf: float
    ultimate_cents: int


class ReserveRun(TypedDict, total=False):
    id: str
    segment_id: str
    development_pattern_id: str
    valuation_quarter: str
    method: str
    basis: str
    earned_exposure_cents: Optional[int]
    a_priori_loss_ratio: Optional[float]
    ultimate_cents: int
    ibnr_cents: int
    range_low_cents: int
    range_high_cents: int
    ultimate_by_accident_quarter: List[UltimateByAccidentQuarter]
    is_stale: bool
    created_at: str
    updated_at: str
    version: int


class ReservingStudy(TypedDict, total=False):
    id: str
    segment_id: str
    valuation_quarter: str
    selected_method: str
    selected_basis: str
    status: str
    stale_data_flag: bool
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    opinion_id: Optional[str]
    selected_ultimate_cents: Optional[int]
    selected_ibnr_cents: Optional[int]
    selected_range_low_cents: Optional[int]
    selected_range_high_cents: Optional[int]
    reconciliation_variance_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ActuarialOpinion(TypedDict, total=False):
    id: str
    statement_date: str
    opinion_scope: str
    status: str
    created_by_user_id: str
    signed_by_user_id: Optional[str]
    signed_at: Optional[str]
    filing_deadline_date: str
    created_at: str
    updated_at: str
    version: int


class RollForward(TypedDict, total=False):
    id: str
    segment_id: str
    valuation_quarter: str
    prior_valuation_quarter: str
    basis: str
    expected_emergence_cents: int
    actual_emergence_cents: int
    ave_variance_cents: int
    ave_variance_ratio: Optional[float]
    created_at: str
    updated_at: str
    version: int
