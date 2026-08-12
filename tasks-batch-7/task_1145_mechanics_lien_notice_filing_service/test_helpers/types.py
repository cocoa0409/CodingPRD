"""Domain types: entity shapes, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    OPS_AGENT = "OpsAgent"
    CUSTOMER_ADMIN = "CustomerAdmin"
    COUNSEL = "Counsel"


class ProjectType(str, Enum):
    COMMERCIAL_PRIVATE = "COMMERCIAL_PRIVATE"
    RESIDENTIAL_PRIVATE = "RESIDENTIAL_PRIVATE"
    STATE_PUBLIC = "STATE_PUBLIC"
    FEDERAL_PUBLIC = "FEDERAL_PUBLIC"


class ResearchStatus(str, Enum):
    UNRESEARCHED = "UNRESEARCHED"
    RESEARCHED = "RESEARCHED"
    VERIFIED = "VERIFIED"


class LienPosture(str, Enum):
    CLEAR = "CLEAR"
    NOTICED = "NOTICED"
    ENCUMBERED = "ENCUMBERED"
    LITIGATION = "LITIGATION"


class RuleStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class DayBasis(str, Enum):
    CALENDAR = "CALENDAR"
    BUSINESS = "BUSINESS"


class CapMode(str, Enum):
    UNCAPPED = "UNCAPPED"
    CONTRACT_BALANCE = "CONTRACT_BALANCE"


class DeliveryMethod(str, Enum):
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    PERSONAL_SERVICE = "PERSONAL_SERVICE"
    EMAIL_STATUTORY = "EMAIL_STATUTORY"


class PartyRole(str, Enum):
    OWNER = "OWNER"
    GC = "GC"
    LENDER = "LENDER"
    HIRER = "HIRER"
    SURETY = "SURETY"


class PartyResearchStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class SpanKind(str, Enum):
    BASE_CONTRACT = "BASE_CONTRACT"
    CHANGE_ORDER = "CHANGE_ORDER"
    PUNCH_LIST = "PUNCH_LIST"
    WARRANTY = "WARRANTY"


class SpanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    SERVED = "SERVED"
    PROOF_CONFIRMED = "PROOF_CONFIRMED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    EXPIRED = "EXPIRED"


class ProofResult(str, Enum):
    DELIVERED = "DELIVERED"
    REFUSED = "REFUSED"
    RETURNED = "RETURNED"


class LienClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    AMOUNT_LOCKED = "AMOUNT_LOCKED"
    FILED = "FILED"
    RELEASED = "RELEASED"
    BONDED_OFF = "BONDED_OFF"
    FORECLOSED = "FORECLOSED"
    EXPIRED = "EXPIRED"


class WaiverType(str, Enum):
    CONDITIONAL_PROGRESS = "CONDITIONAL_PROGRESS"
    UNCONDITIONAL_PROGRESS = "UNCONDITIONAL_PROGRESS"
    CONDITIONAL_FINAL = "CONDITIONAL_FINAL"
    UNCONDITIONAL_FINAL = "UNCONDITIONAL_FINAL"


class WaiverStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"


class BondingRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    BOND_RECORDED = "BOND_RECORDED"
    REJECTED = "REJECTED"


class ReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUIT_FILED = "SUIT_FILED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    MOOT_BONDED = "MOOT_BONDED"
    MOOT_RELEASED = "MOOT_RELEASED"
    MOOT_EXPIRED = "MOOT_EXPIRED"


class StopNoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    SERVED = "SERVED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class BondClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


# All entities carry the common system-managed properties of PRD §2.4:
# id, created_at, updated_at, version.

class Company(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    prepaid_balance_cents: int
    open_notice_count: int
    created_at: str
    updated_at: str
    version: int


class JurisdictionRule(TypedDict, total=False):
    id: str
    state_code: str
    project_type: str
    prelim_notice_required: bool
    prelim_days: int
    prelim_day_basis: str
    refused_counts_as_served: bool
    allowed_delivery_methods: list
    filing_window_days: int
    foreclosure_deadline_days: int
    stop_notice_days: int
    bond_claim_days: int
    counts_punch_list: bool
    retainage_claimable: bool
    cap_mode: str
    interest_annual_rate: float
    bond_pct: float
    effective_from: str
    status: str
    supersedes_rule_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    company_id: str
    name: str
    state_code: str
    county: str
    project_type: str
    property_legal_description: str
    contract_value_cents: int
    approved_extras_cents: int
    retainage_held_cents: int
    research_status: str
    first_furnishing_date: Optional[str]
    last_furnishing_date: Optional[str]
    open_notice_count: int
    open_lien_count: int
    lien_posture: str
    created_at: str
    updated_at: str
    version: int


class Party(TypedDict, total=False):
    id: str
    project_id: str
    party_role: str
    legal_name: str
    address: str
    research_status: str
    created_at: str
    updated_at: str
    version: int


class FurnishingSpan(TypedDict, total=False):
    id: str
    project_id: str
    span_kind: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class NoticeOrder(TypedDict, total=False):
    id: str
    project_id: str
    recipient_party_id: str
    delivery_method: str
    status: str
    service_deadline: Optional[str]
    served_at: Optional[str]
    proof_result: Optional[str]
    proof_url: Optional[str]
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class LienClaim(TypedDict, total=False):
    id: str
    project_id: str
    status: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    gross_snapshot_cents: Optional[int]
    verified_paid_cents: int
    effective_waiver_cents: int
    waived_to_extras_cents: int
    waived_to_contract_cents: int
    outstanding_cents: Optional[int]
    filed_at: Optional[str]
    filing_window_end: Optional[str]
    foreclosure_deadline: Optional[str]
    locked_rule_id: Optional[str]
    interest_cents: Optional[int]
    total_with_interest_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict, total=False):
    id: str
    project_id: str
    waiver_type: str
    amount_cents: int
    period_start: str
    period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    project_id: str
    lien_claim_id: Optional[str]
    amount_cents: int
    received_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BondingRequest(TypedDict, total=False):
    id: str
    lien_claim_id: str
    surety_party_id: str
    bond_amount_cents: int
    status: str
    recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ForeclosureReferral(TypedDict, total=False):
    id: str
    lien_claim_id: str
    counsel_name: str
    status: str
    suit_filed_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StopNotice(TypedDict, total=False):
    id: str
    project_id: str
    amount_cents: int
    coverage_start: str
    coverage_end: str
    status: str
    served_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BondClaim(TypedDict, total=False):
    id: str
    project_id: str
    surety_party_id: str
    amount_cents: int
    status: str
    submitted_at: Optional[str]
    resolve_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int
