"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the common system fields (id, created_at, updated_at,
version) per the PRD's common resource properties section.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    GIFT_OFFICER = "GiftOfficer"
    GIFT_ADMINISTRATOR = "GiftAdministrator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ESTATE_MANAGER = "EstateManager"
    FINANCE_STEWARD = "FinanceSteward"


class VitalStatus(str, Enum):
    LIVING = "LIVING"
    DECEASED = "DECEASED"


class LegacySocietyStatus(str, Enum):
    NONE = "NONE"
    ENROLLED = "ENROLLED"
    RECOGNIZED = "RECOGNIZED"
    REVOKED = "REVOKED"


class RateTableStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class VehicleType(str, Enum):
    CGA = "CGA"
    CRT_UNITRUST = "CRT_UNITRUST"
    CRT_ANNUITY = "CRT_ANNUITY"
    BEQUEST = "BEQUEST"


class PaymentFrequency(str, Enum):
    ANNUAL = "ANNUAL"
    SEMIANNUAL = "SEMIANNUAL"
    QUARTERLY = "QUARTERLY"
    MONTHLY = "MONTHLY"


class IllustrationStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    SUPERSEDED = "SUPERSEDED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    FUNDED = "FUNDED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    MATURED = "MATURED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"
    RESCINDED = "RESCINDED"
    TERMINATED = "TERMINATED"


class DesignationSlot(str, Enum):
    PRIMARY_1 = "PRIMARY_1"
    PRIMARY_2 = "PRIMARY_2"
    CONTINGENT = "CONTINGENT"


class DesignationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class AssetKind(str, Enum):
    CASH = "CASH"
    SECURITIES = "SECURITIES"
    REAL_ESTATE = "REAL_ESTATE"


class AssetStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RECEIVED = "RECEIVED"
    APPRAISED = "APPRAISED"
    LIQUIDATED = "LIQUIDATED"
    DISTRIBUTED = "DISTRIBUTED"
    RETURNED = "RETURNED"


class PaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    PAID = "PAID"
    DEFERRED = "DEFERRED"
    LAPSED = "LAPSED"


class LapseReason(str, Enum):
    DONOR_DEATH = "DONOR_DEATH"
    TERMINATION = "TERMINATION"
    MATURITY = "MATURITY"
    MANUAL = "MANUAL"


class ReservePosture(str, Enum):
    SOLVENT = "SOLVENT"
    RESERVE_DEFICIENT = "RESERVE_DEFICIENT"


class EstateStatus(str, Enum):
    NOTIFIED = "NOTIFIED"
    PROBATE_OPEN = "PROBATE_OPEN"
    CONTESTED = "CONTESTED"
    DISTRIBUTION_PENDING = "DISTRIBUTION_PENDING"
    DISTRIBUTED = "DISTRIBUTED"
    CLOSED = "CLOSED"


class MilestoneKind(str, Enum):
    PETITION = "PETITION"
    NOTICE_TO_CREDITORS = "NOTICE_TO_CREDITORS"
    INVENTORY = "INVENTORY"
    APPRAISAL = "APPRAISAL"
    FINAL_ACCOUNTING = "FINAL_ACCOUNTING"
    COURT_ORDER = "COURT_ORDER"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    FILED = "FILED"
    OVERDUE = "OVERDUE"
    CLOSED = "CLOSED"


class RestrictionType(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    SCHOLARSHIP = "SCHOLARSHIP"
    FACULTY_SUPPORT = "FACULTY_SUPPORT"
    RESEARCH = "RESEARCH"
    CAPITAL = "CAPITAL"


class FundStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ENDOWED = "ENDOWED"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class ValuationRunStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"


class AdjustmentDirection(str, Enum):
    CONTRIBUTION = "CONTRIBUTION"
    WITHDRAWAL = "WITHDRAWAL"


class Donor(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    contact_email: Optional[str]
    vital_status: str
    deceased_on: Optional[str]
    legacy_society_status: str
    documented_gift_total_cents: int
    created_at: str
    updated_at: str
    version: int


class RateTable(TypedDict, total=False):
    id: str
    label: str
    discount_rate_bps: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Illustration(TypedDict, total=False):
    id: str
    donor_id: str
    vehicle_type: str
    gift_amount_cents: int
    payout_rate_bps: Optional[int]
    payment_frequency: str
    lives: int
    annuitant_1_age: int
    annuitant_2_age: Optional[int]
    funding_month: str
    rate_table_id: str
    illustrated_annual_annuity_cents: Optional[int]
    illustrated_deduction_cents: int
    status: str
    supersedes_illustration_id: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class GiftAgreement(TypedDict, total=False):
    id: str
    donor_id: str
    illustration_id: Optional[str]
    vehicle_type: str
    gift_amount_cents: int
    payout_rate_bps: Optional[int]
    payment_frequency: str
    lives: int
    annuitant_1_age: int
    annuitant_2_age: Optional[int]
    funding_month: str
    rate_table_id: str
    status: str
    executed_at: Optional[str]
    executed_by_user_id: Optional[str]
    annual_annuity_cents: Optional[int]
    booked_deduction_cents: Optional[int]
    corpus_value_cents: Optional[int]
    received_value_cents: int
    total_paid_cents: int
    total_scheduled_cents: int
    liability_released_cents: int
    actuarial_liability_cents: Optional[int]
    remainder_value_cents: Optional[int]
    reserve_requirement_cents: int
    surrender_value_cents: Optional[int]
    fund_id: Optional[str]
    restriction_type: str
    restriction_text: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BeneficiaryDesignation(TypedDict, total=False):
    id: str
    gift_agreement_id: str
    slot: str
    beneficiary_name: str
    document_received: bool
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GiftAsset(TypedDict, total=False):
    id: str
    gift_agreement_id: Optional[str]
    estate_id: Optional[str]
    asset_kind: str
    description: Optional[str]
    pledged_value_cents: int
    status: str
    dod_high_price_cents: Optional[int]
    dod_low_price_cents: Optional[int]
    alt_high_price_cents: Optional[int]
    alt_low_price_cents: Optional[int]
    fmv_cents: Optional[int]
    appraised_value_cents: Optional[int]
    gross_proceeds_cents: Optional[int]
    liquidation_costs_cents: Optional[int]
    net_proceeds_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AnnuityPayment(TypedDict, total=False):
    id: str
    gift_agreement_id: str
    period_index: int
    due_date: str
    amount_cents: int
    status: str
    paid_at: Optional[str]
    defer_until: Optional[str]
    lapse_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReserveFund(TypedDict, total=False):
    id: str
    name: str
    balance_cents: int
    booked_target_cents: int
    projected_target_cents: int
    booked_coverage_bps: Optional[int]
    posture: str
    created_at: str
    updated_at: str
    version: int


class Estate(TypedDict, total=False):
    id: str
    donor_id: str
    gift_agreement_id: Optional[str]
    status: str
    notified_on: str
    recorded_by_user_id: str
    alternate_valuation_elected: bool
    gross_proceeds_cents: int
    administration_costs_cents: int
    specific_bequests_cents: int
    residual_to_university_cents: Optional[int]
    distributed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProbateMilestone(TypedDict, total=False):
    id: str
    estate_id: str
    kind: str
    due_date: str
    status: str
    filed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Fund(TypedDict, total=False):
    id: str
    name: str
    restriction_type: str
    minimum_endowment_cents: int
    gift_agreement_id: str
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CorpusUpdate(TypedDict):
    agreement_id: str
    new_corpus_cents: int


class ValuationRun(TypedDict, total=False):
    id: str
    coverage_start: str
    coverage_end: str
    valuation_date: str
    corpus_updates: Optional[List[CorpusUpdate]]
    status: str
    created_by_user_id: str
    posted_by_user_id: Optional[str]
    agreements_revalued_count: Optional[int]
    total_liability_cents: Optional[int]
    total_remainder_cents: Optional[int]
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
