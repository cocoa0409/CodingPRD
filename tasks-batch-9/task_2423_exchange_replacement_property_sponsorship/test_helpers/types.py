"""Domain types: entity TypedDicts, status enums, role enum.

Every name here is taken from the PRD's own vocabulary.
"""

from enum import Enum
from typing import TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    SPONSOR_PRINCIPAL = "SponsorPrincipal"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRUSTEE = "Trustee"
    INVESTOR = "Investor"
    MASTER_TENANT = "MasterTenant"
    QUALIFIED_INTERMEDIARY = "QualifiedIntermediary"
    PLATFORM_ADMIN = "PlatformAdmin"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Status / enum vocabularies
# --------------------------------------------------------------------------


class PropertyStatus(str, Enum):
    UNDER_CONTRACT = "UNDER_CONTRACT"
    ACQUIRED = "ACQUIRED"
    CONTRACT_EXPIRED = "CONTRACT_EXPIRED"
    DISPOSED = "DISPOSED"


class AssetType(str, Enum):
    INDUSTRIAL = "INDUSTRIAL"
    MULTIFAMILY = "MULTIFAMILY"
    RETAIL = "RETAIL"
    OFFICE = "OFFICE"


class TrustStatus(str, Enum):
    FORMING = "FORMING"
    FUNDING = "FUNDING"
    OPERATING = "OPERATING"
    WINDING_DOWN = "WINDING_DOWN"
    TERMINATED = "TERMINATED"
    CONVERTED_LLC = "CONVERTED_LLC"


class TrustPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class OfferingStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    EFFECTIVE = "EFFECTIVE"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class ExemptionRule(str, Enum):
    RULE_506B = "RULE_506B"
    RULE_506C = "RULE_506C"


class AccreditationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class SuitabilityStatus(str, Enum):
    NOT_REVIEWED = "NOT_REVIEWED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class InvestorEntityType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    JOINT = "JOINT"
    IRA = "IRA"
    LLC = "LLC"
    REVOCABLE_TRUST = "REVOCABLE_TRUST"


class AccreditationMethod(str, Enum):
    SELF_CERT_INCOME = "SELF_CERT_INCOME"
    SELF_CERT_NET_WORTH = "SELF_CERT_NET_WORTH"
    THIRD_PARTY_LETTER = "THIRD_PARTY_LETTER"


class ExchangeFileStatus(str, Enum):
    OPEN = "OPEN"
    IDENTIFIED = "IDENTIFIED"
    CLOSED_MATCHED = "CLOSED_MATCHED"
    EXPIRED = "EXPIRED"


class IdentificationRule(str, Enum):
    THREE_PROPERTY = "THREE_PROPERTY"
    TWO_HUNDRED_PCT = "TWO_HUNDRED_PCT"


class IdentificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class SubscriptionStatus(str, Enum):
    RESERVED = "RESERVED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    RESCINDED = "RESCINDED"


class LoanStatus(str, Enum):
    COMMITTED = "COMMITTED"
    FUNDED = "FUNDED"
    PAID_OFF = "PAID_OFF"


class RecourseType(str, Enum):
    NON_RECOURSE = "NON_RECOURSE"
    RECOURSE = "RECOURSE"


class MasterLeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class LedgerBucket(str, Enum):
    OPERATING = "OPERATING"
    RESERVE = "RESERVE"


class LedgerEntryType(str, Enum):
    EQUITY_CONTRIBUTION = "EQUITY_CONTRIBUTION"
    LOAN_PROCEEDS = "LOAN_PROCEEDS"
    ACQUISITION_PAYMENT = "ACQUISITION_PAYMENT"
    SPONSOR_LOAD = "SPONSOR_LOAD"
    RESERVE_FUNDING = "RESERVE_FUNDING"
    RESERVE_DRAW = "RESERVE_DRAW"
    RENT_RECEIPT = "RENT_RECEIPT"
    DEBT_SERVICE = "DEBT_SERVICE"
    DISTRIBUTION_PAYMENT = "DISTRIBUTION_PAYMENT"
    SALE_PROCEEDS = "SALE_PROCEEDS"
    LOAN_PAYOFF = "LOAN_PAYOFF"
    REVERSAL = "REVERSAL"


class LedgerSourceKind(str, Enum):
    SUBSCRIPTION_CLOSE = "SUBSCRIPTION_CLOSE"
    LOAN_FUNDING = "LOAN_FUNDING"
    ACQUISITION = "ACQUISITION"
    RENT_POSTING = "RENT_POSTING"
    DEBT_SERVICE_POSTING = "DEBT_SERVICE_POSTING"
    CAPITAL_NEED = "CAPITAL_NEED"
    DISTRIBUTION = "DISTRIBUTION"
    EXIT = "EXIT"
    REVERSAL = "REVERSAL"


class RentKind(str, Enum):
    BASE = "BASE"
    SUPPLEMENTAL = "SUPPLEMENTAL"


class CapitalNeedStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    FUNDED = "FUNDED"
    VOIDED = "VOIDED"


class CapitalNeedType(str, Enum):
    NORMAL_REPAIR = "NORMAL_REPAIR"
    TENANT_IMPROVEMENT = "TENANT_IMPROVEMENT"
    STRUCTURAL_CAPEX = "STRUCTURAL_CAPEX"


class FundingSource(str, Enum):
    RESERVE = "RESERVE"
    MASTER_TENANT = "MASTER_TENANT"
    CAPITAL_CALL = "CAPITAL_CALL"


class DistributionStatus(str, Enum):
    DECLARED = "DECLARED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class DistributionKind(str, Enum):
    OPERATING = "OPERATING"
    LIQUIDATING = "LIQUIDATING"


class TaxStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"


class AllocationVariant(str, Enum):
    UNITS_AT_YEAR_END = "UNITS_AT_YEAR_END"
    UNIT_DAYS_WEIGHTED = "UNIT_DAYS_WEIGHTED"


class ExitEventStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class ExitMode(str, Enum):
    ASSET_SALE = "ASSET_SALE"
    SECTION_721_CONVERSION = "SECTION_721_CONVERSION"


class ConsentDecision(str, Enum):
    CONSENT = "CONSENT"
    WITHHOLD = "WITHHOLD"


# --------------------------------------------------------------------------
# Entity shapes
#
# Entities carrying id + created_at + updated_at + version, and the three
# append-only journals which carry only id + created_at (PRD §2.5).
# --------------------------------------------------------------------------


class Property(TypedDict):
    id: str
    name: str
    state_code: str
    asset_type: str
    purchase_price_cents: int
    appraised_value_cents: int
    annual_noi_cents: int
    occupancy_rate: float
    contract_close_deadline: str
    depreciable_basis_cents: int
    acquired_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DstTrust(TypedDict):
    id: str
    property_id: str
    trust_name: str
    total_units: int
    units_issued: int
    reserve_floor_cents: int
    reserve_target_pct: float
    reserve_balance_cents: int
    operating_balance_cents: int
    equity_raised_cents: int
    property_acquired_at: str
    springing_llc_armed: bool
    status: str
    posture: str
    created_at: str
    updated_at: str
    version: int


class Offering(TypedDict):
    id: str
    trust_id: str
    exemption_rule: str
    unit_price_cents: int
    min_units_per_investor: int
    load_pct: float
    closing_costs_cents: int
    reserve_funding_pct: float
    rescission_window_days: int
    initial_reserve_cents: int
    target_equity_cents: int
    sponsor_load_cents: int
    units_committed: int
    equity_committed_cents: int
    ppm_submitted_by_user_id: str
    ppm_version: int
    effective_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Investor(TypedDict):
    id: str
    legal_name: str
    entity_type: str
    accreditation_method: str
    annual_income_cents: int
    net_worth_cents: int
    liquid_net_worth_cents: int
    accreditation_status: str
    accreditation_verified_at: str
    accreditation_expires_at: str
    suitability_status: str
    suitability_cap_cents: int
    suitability_offering_id: str
    suitability_reviewed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ExchangeFile(TypedDict):
    id: str
    investor_id: str
    source_exit_event_id: str
    qi_reference: str
    relinquished_closed_on: str
    relinquished_sale_price_cents: int
    net_proceeds_cents: int
    debt_retired_cents: int
    identification_rule: str
    boot_tolerance_cents: int
    identification_deadline: str
    exchange_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PropertyIdentification(TypedDict):
    id: str
    exchange_file_id: str
    property_id: str
    fair_market_value_cents: int
    identified_at: str
    sequence_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    offering_id: str
    investor_id: str
    exchange_file_id: str
    units_requested: int
    investment_amount_cents: int
    boot_cents: int
    closing_sequence_no: int
    closed_at: str
    rescission_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanFacility(TypedDict):
    id: str
    trust_id: str
    lender_name: str
    principal_cents: int
    rate_bps: int
    recourse_type: str
    maturity_on: str
    ltv_pct: float
    dscr: float
    repriced_count: int
    funded_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MasterLease(TypedDict):
    id: str
    trust_id: str
    master_tenant_user_id: str
    term_start_on: str
    term_end_on: str
    base_rent_annual_cents: int
    supplemental_rent_annual_cents: int
    executed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalNeed(TypedDict):
    id: str
    trust_id: str
    need_type: str
    amount_cents: int
    needed_by: str
    funding_source: str
    funded_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict):
    id: str
    trust_id: str
    kind: str
    period_start: str
    period_end: str
    provisional_amount_cents: int
    final_amount_cents: int
    reconciliation_delta_cents: int
    declared_at: str
    paid_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxStatement(TypedDict):
    id: str
    trust_id: str
    subscription_id: str
    tax_year: int
    allocation_variant: str
    rental_income_cents: int
    interest_expense_cents: int
    depreciation_cents: int
    net_taxable_income_cents: int
    issued_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExitEvent(TypedDict):
    id: str
    trust_id: str
    exit_mode: str
    gross_price_cents: int
    selling_costs_cents: int
    consent_threshold_pct: float
    expected_close_on: str
    consented_units: int
    consent_pct: float
    net_proceeds_cents: int
    net_proceeds_per_unit_cents: int
    closed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only journal rows: only id and created_at (no updated_at, no version).


class TrustLedgerEntry(TypedDict):
    id: str
    trust_id: str
    reversal_of_entry_id: str
    entry_type: str
    bucket: str
    amount_cents: int
    occurred_at: str
    memo: str
    source_kind: str
    created_at: str


class DistributionAllocation(TypedDict):
    id: str
    distribution_id: str
    subscription_id: str
    units: int
    raw_share_cents: float
    allocated_cents: int
    residual_adjustment_cents: int
    created_at: str


class ExitConsent(TypedDict):
    id: str
    exit_event_id: str
    subscription_id: str
    decision: str
    units_at_consent: int
    recorded_at: str
    created_at: str


APPEND_ONLY_ENTITIES = ("TrustLedgerEntry", "DistributionAllocation", "ExitConsent")
