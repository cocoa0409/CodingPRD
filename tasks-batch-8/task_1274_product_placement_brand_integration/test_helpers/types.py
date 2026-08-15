"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.1 declares the seven roles; §2.4 fixes common resource properties.
Entities whose lifecycle is append-only (ContinuityRecord, §2.4) carry only
id + created_at; every other entity carries id + created_at + updated_at +
version.
"""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    BRAND_REP = "BrandRep"
    INTEGRATION_MANAGER = "IntegrationManager"
    PRODUCTION_REP = "ProductionRep"
    NETWORK_STANDARDS_REVIEWER = "NetworkStandardsReviewer"
    CLEARANCE_OFFICER = "ClearanceOfficer"
    VERIFICATION_ANALYST = "VerificationAnalyst"


class BrandStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BrandCategory(str, Enum):
    BEVERAGE = "BEVERAGE"
    AUTOMOTIVE = "AUTOMOTIVE"
    TECH = "TECH"
    FOOD = "FOOD"
    BEAUTY = "BEAUTY"
    OTHER = "OTHER"


class BriefStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ClearancePolicy(str, Enum):
    STANDARD = "STANDARD"
    STRICT = "STRICT"


class EpisodeStatus(str, Enum):
    SCRIPT_REVIEW = "SCRIPT_REVIEW"
    LOCKED = "LOCKED"
    AIRED = "AIRED"
    VERIFIED = "VERIFIED"


class OpportunityStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    PITCHED = "PITCHED"
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    WITHDRAWN = "WITHDRAWN"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    PRODUCTION_REVIEW = "PRODUCTION_REVIEW"
    NETWORK_REVIEW = "NETWORK_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONTRACTED = "CONTRACTED"
    WITHDRAWN = "WITHDRAWN"


class ContractStatus(str, Enum):
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    ACTIVE = "ACTIVE"
    UNDER_VERIFICATION = "UNDER_VERIFICATION"
    MAKEGOOD_REQUIRED = "MAKEGOOD_REQUIRED"
    SETTLED = "SETTLED"
    TERMINATED = "TERMINATED"


class ShipmentStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    STAGED = "STAGED"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    IN_RETURN = "IN_RETURN"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class ContinuityRecordStatus(str, Enum):
    LOGGED = "LOGGED"
    VOID = "VOID"


class ClearanceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    RELEASED = "RELEASED"


class ClearanceDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class ProposalDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"
    REJECT = "REJECT"


class AiringReportStatus(str, Enum):
    FILED = "FILED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    RE_MEASURED = "RE_MEASURED"


class MakeGoodCreditStatus(str, Enum):
    PENDING = "PENDING"
    WAIVED = "WAIVED"


class MakeGoodReason(str, Enum):
    EXPOSURE_SHORTFALL = "EXPOSURE_SHORTFALL"
    VERBAL_MISS = "VERBAL_MISS"
    COMBINED = "COMBINED"


class CrossPromoStatus(str, Enum):
    OWED = "OWED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"


class DisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------


class Brand(TypedDict, total=False):
    id: str
    name: str
    category: str
    watchlist_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BrandBrief(TypedDict, total=False):
    id: str
    brand_id: str
    title: str
    objective: str
    budget_cents: int
    remaining_budget_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Series(TypedDict, total=False):
    id: str
    name: str
    network_name: str
    clearance_policy: str
    created_at: str
    updated_at: str
    version: int


class Episode(TypedDict, total=False):
    id: str
    series_id: str
    episode_number: int
    runtime_seconds: int
    air_date: str
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScriptOpportunity(TypedDict, total=False):
    id: str
    episode_id: str
    scene_description: str
    start_timecode_seconds: int
    end_timecode_seconds: int
    estimated_exposure_seconds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IntegrationProposal(TypedDict, total=False):
    id: str
    brief_id: str
    opportunity_id: str
    proposed_fee_cents: int
    guaranteed_seconds: int
    guaranteed_verbal_mentions: int
    cross_promo_owed_count: int
    rate_cents_per_second: float
    terms_revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IntegrationContract(TypedDict, total=False):
    id: str
    proposal_id: str
    episode_id: str
    base_fee_cents: int
    guaranteed_seconds: int
    guaranteed_verbal_mentions: int
    rate_cents_per_second: float
    cross_promo_owed_count: int
    provisional_value_cents: Optional[int]
    bonus_cents: int
    makegood_total_cents: int
    outstanding_balance_cents: int
    final_settlement_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PropShipment(TypedDict, total=False):
    id: str
    contract_id: str
    item_description: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContinuityRecord(TypedDict, total=False):
    # Append-only (PRD §2.4): carries ONLY id + created_at among common fields.
    # updated_at and version are intentionally absent.
    id: str
    contract_id: str
    shipment_id: str
    scene_timecode_seconds: int
    note: str
    status: str
    created_at: str


class CompetitiveClearance(TypedDict, total=False):
    id: str
    episode_id: str
    brand_id: str
    category: str
    risk_score: Optional[int]
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AiringReport(TypedDict, total=False):
    id: str
    episode_id: str
    contract_id: str
    measured_segments_seconds: List[float]
    measured_verbal_mentions: int
    measured_seconds: float
    measured_value_cents: int
    filed_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MakeGoodCredit(TypedDict, total=False):
    id: str
    contract_id: str
    amount_cents: int
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrossPromoObligation(TypedDict, total=False):
    id: str
    contract_id: str
    owed_count: int
    fulfilled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisclosureFiling(TypedDict, total=False):
    id: str
    contract_id: str
    disclosure_text: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractLedger(TypedDict, total=False):
    base_fee_cents: int
    bonus_cents: int
    makegood_total_cents: int
    outstanding_balance_cents: int
    provisional_value_cents: Optional[int]
    final_settlement_cents: Optional[int]
