"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource carries the standard
system-managed fields id + created_at + updated_at + version (PRD section on
common resource properties); the Invoice entity additionally embeds an
append-only payments list whose sub-records are payment entries.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class SponsorStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"


class AssetStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RETIRED = "RETIRED"


class AssetClass(str, Enum):
    SIGNAGE = "SIGNAGE"
    DIGITAL = "DIGITAL"
    HOSPITALITY = "HOSPITALITY"


class WindowStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class RightsHolder(str, Enum):
    TEAM = "TEAM"
    VENUE = "VENUE"
    LEAGUE = "LEAGUE"


class IndustryCategory(str, Enum):
    BEVERAGE = "BEVERAGE"
    BANKING = "BANKING"
    AUTO = "AUTO"
    AIRLINE = "AIRLINE"
    TECH = "TECH"


class EscalatorMode(str, Enum):
    COMPOUND = "COMPOUND"
    SIMPLE = "SIMPLE"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERSIGNED = "COUNTERSIGNED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class RightsStatus(str, Enum):
    CLEAR = "CLEAR"
    CONTESTED = "CONTESTED"


class GrantStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CONFLICTED = "CONFLICTED"
    RELEASED = "RELEASED"


class UnitKind(str, Enum):
    GAME_DISPLAY = "GAME_DISPLAY"
    IMPRESSION_BLOCK = "IMPRESSION_BLOCK"
    SUITE_NIGHT = "SUITE_NIGHT"


class DeliverableStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FULFILLED = "FULFILLED"
    MISSED = "MISSED"
    COMPED = "COMPED"
    CANCELLED = "CANCELLED"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class CreditStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REDEEMED = "REDEEMED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"
    WRITTEN_OFF = "WRITTEN_OFF"


class InstallmentLabel(str, Enum):
    SIGNING = "SIGNING"
    MID_SEASON = "MID_SEASON"
    POST_SEASON = "POST_SEASON"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class OpportunityStage(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    PROPOSED = "PROPOSED"
    NEGOTIATING = "NEGOTIATING"
    WON = "WON"
    LOST = "LOST"


class UserRole(str, Enum):
    VENUE_ADMIN = "VenueAdmin"
    SPONSORSHIP_SALES = "SponsorshipSales"
    ACTIVATION_MANAGER = "ActivationManager"
    FINANCE_MANAGER = "FinanceManager"
    SPONSOR_CONTACT = "SponsorContact"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Venue(TypedDict, total=False):
    id: str
    display_name: str
    city: str
    current_season: int
    created_at: str
    updated_at: str
    version: int


class SponsorAccount(TypedDict, total=False):
    id: str
    legal_name: str
    display_name: str
    industry_category: str
    sponsor_status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    venue_id: str
    name: str
    asset_class: str
    rate_card_unit_cents: int
    avg_impressions_per_unit: int
    cpm_cents: int
    asset_status: str
    created_at: str
    updated_at: str
    version: int


class RightsWindow(TypedDict, total=False):
    id: str
    venue_id: str
    holder: str
    category: str
    first_season: int
    last_season: int
    window_status: str
    created_at: str
    updated_at: str
    version: int


class SponsorshipContract(TypedDict, total=False):
    id: str
    venue_id: str
    sponsor_id: str
    title: str
    term_first_season: int
    term_last_season: int
    base_fee_cents: int
    escalator_pct: float
    escalator_mode: str
    renewed_from_contract_id: Optional[str]
    contract_status: str
    rights_status: str
    scheduled_total_cents: int
    receivable_cents: int
    make_good_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class ExclusivityGrant(TypedDict, total=False):
    id: str
    contract_id: str
    category: str
    first_season: int
    last_season: int
    grant_status: str
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict, total=False):
    id: str
    contract_id: str
    asset_id: str
    season: int
    unit_kind: str
    contracted_units: int
    checkin_date: Optional[str]
    checkout_date: Optional[str]
    approved_units: int
    deliverable_status: str
    created_at: str
    updated_at: str
    version: int


class EvidenceSubmission(TypedDict, total=False):
    id: str
    deliverable_id: str
    units_claimed: int
    evidence_uri: str
    submitted_by_user_id: str
    submission_status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MakeGoodCredit(TypedDict, total=False):
    id: str
    contract_id: str
    deliverable_id: str
    requested_amount_cents: int
    approved_amount_cents: Optional[int]
    redeemed_against_invoice_id: Optional[str]
    credit_status: str
    created_at: str
    updated_at: str
    version: int


class PaymentRecord(TypedDict, total=False):
    payment_id: str
    amount_cents: int
    method: str
    external_ref: Optional[str]
    posted_at: str
    voided: bool


class Invoice(TypedDict, total=False):
    id: str
    contract_id: str
    installment_seq: int
    installment_label: str
    amount_cents: int
    paid_cents: int
    credits_applied_cents: int
    invoice_status: str
    payments: List[PaymentRecord]
    created_at: str
    updated_at: str
    version: int


class ValuationReport(TypedDict, total=False):
    id: str
    contract_id: str
    season: int
    report_status: str
    delivered_value_provisional_cents: int
    delivered_value_final_cents: int
    fulfillment_pct: float
    make_good_due_cents: int
    created_at: str
    updated_at: str
    version: int


class RenewalOpportunity(TypedDict, total=False):
    id: str
    contract_id: str
    proposed_fee_cents: int
    stage: str
    resulting_contract_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
