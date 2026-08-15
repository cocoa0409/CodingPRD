"""Domain types: entity TypedDicts, status enums, role enum.

All enums mirror the PRD's named status/value sets. Per PRD §2.5, every
primary resource carries the full common field set (id, created_at,
updated_at, version); the Retirement resource is the deliberate exception
and carries only id and created_at (no updated_at, no version).
"""
from enum import Enum
from typing import Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    REGISTRY_ADMIN = "RegistryAdmin"
    GENERATOR_OPERATOR = "GeneratorOperator"
    METER_ATTESTER = "MeterAttester"
    BROKER_TRADER = "BrokerTrader"
    PROGRAM_MANAGER = "ProgramManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    AUDITOR = "Auditor"


class Technology(str, Enum):
    SOLAR = "SOLAR"
    WIND = "WIND"
    HYDRO = "HYDRO"
    BIOMASS = "BIOMASS"
    GEOTHERMAL = "GEOTHERMAL"


class GeneratorStatus(str, Enum):
    REGISTERED = "REGISTERED"
    VERIFICATION = "VERIFICATION"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class MeterReadingStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ATTESTED = "ATTESTED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    VOIDED = "VOIDED"


class AccountType(str, Enum):
    GENERATOR = "GENERATOR"
    BROKER = "BROKER"
    PROGRAM = "PROGRAM"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    RETIRED = "RETIRED"
    REVOKED = "REVOKED"


class SettlementMode(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class TradeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class MarketClass(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    COMPLIANCE = "COMPLIANCE"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ARCHIVED = "ARCHIVED"


class SubscriptionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    WAITLISTED = "WAITLISTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class RetirementPurpose(str, Enum):
    VOLUNTARY_PROGRAM = "VOLUNTARY_PROGRAM"
    COMPLIANCE = "COMPLIANCE"
    WHOLESALE_CLAIM = "WHOLESALE_CLAIM"


class ObligationStatus(str, Enum):
    OPEN = "OPEN"
    MET = "MET"
    CLOSED_MET = "CLOSED_MET"
    CLOSED_SHORTFALL = "CLOSED_SHORTFALL"


class ClaimReportScope(str, Enum):
    VOLUNTARY_PROGRAM = "VOLUNTARY_PROGRAM"
    COMPLIANCE_OBLIGATION = "COMPLIANCE_OBLIGATION"


class ClaimReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class Generator(TypedDict, total=False):
    id: str
    legal_name: str
    facility_code: str
    technology: str
    nameplate_capacity_kw: int
    region_code: str
    commissioning_date: str
    status: str
    rejection_reason: Optional[str]
    cumulative_accepted_kwh: int
    carryover_kwh: int
    lifetime_minted_mwh: int
    next_serial: int
    created_at: str
    updated_at: str
    version: int


class MeterReading(TypedDict, total=False):
    id: str
    generator_id: str
    period_start: str
    period_end: str
    metered_kwh: int
    status: str
    submitted_by_user_id: str
    attested_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    minted: bool
    minted_vintage_month: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    account_type: str
    owner_name: str
    generator_id: Optional[str]
    program_id: Optional[str]
    status: str
    failure_strikes: int
    active_holdings_mwh: int
    locked_holdings_mwh: int
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    generator_id: str
    account_id: str
    vintage_month: str
    region_code: str
    technology: str
    serial_prefix: str
    serial_start: int
    serial_end: int
    quantity_mwh: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Trade(TypedDict, total=False):
    id: str
    from_account_id: str
    to_account_id: str
    items: List[dict]
    unit_price_cents_per_mwh: int
    settlement_mode: str
    status: str
    proposed_at: str
    accepted_at: Optional[str]
    settlement_deadline: Optional[str]
    settled_at: Optional[str]
    total_line_cents: Optional[int]
    broker_fee_cents: Optional[int]
    buyer_total_cents: Optional[int]
    seller_proceeds_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    name: str
    market_class: str
    eligible_region_codes: List[str]
    eligible_technologies: List[str]
    vintage_window_months: int
    capacity_cap_kw: int
    kwh_per_kw_monthly: int
    rate_tiers: List[dict]
    annual_claim_cap_mwh: int
    holding_account_id: Optional[str]
    status: str
    committed_capacity_kw: int
    retired_mwh_current_year: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    program_id: str
    customer_name: str
    utility_account_no: str
    allocation_kw: int
    estimated_usage_kwh: int
    status: str
    activated_at: Optional[str]
    waitlisted_at: Optional[str]
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bill(TypedDict, total=False):
    id: str
    subscription_id: str
    period_month: str
    usage_kwh: int
    charges_cents: int
    status: str
    provisional_credit_cents: int
    issued_credit_cents: Optional[int]
    proration_active_days: Optional[int]
    proration_days_in_period: Optional[int]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Retirement(TypedDict, total=False):
    # Immutable event row (PRD §2.5): carries only id + created_at of the
    # common fields — NO updated_at, NO version.
    id: str
    certificate_id: str
    account_id: str
    purpose: str
    program_id: Optional[str]
    obligation_id: Optional[str]
    external_claim_reference: Optional[str]
    quantity_mwh: int
    vintage_month: str
    region_code: str
    technology: str
    claimed_in_report_id: Optional[str]
    created_at: str


class ComplianceObligation(TypedDict, total=False):
    id: str
    lse_name: str
    year: int
    region_code: str
    required_mwh: int
    penalty_rate_cents_per_mwh: int
    covered_mwh: int
    status: str
    penalty_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ClaimReport(TypedDict, total=False):
    id: str
    scope: str
    program_id: Optional[str]
    obligation_id: Optional[str]
    report_year: int
    status: str
    retirement_ids: List[str]
    total_mwh: int
    totals_by_technology: Dict[str, int]
    totals_by_region: Dict[str, int]
    submitted_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
