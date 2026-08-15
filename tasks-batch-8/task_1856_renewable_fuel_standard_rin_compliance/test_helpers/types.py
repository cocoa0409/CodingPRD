"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    COMPLIANCE_MANAGER = "ComplianceManager"
    TRADER = "Trader"
    AUDITOR = "Auditor"


class ObligationYearStatus(str, Enum):
    OPEN = "OPEN"
    VOLUME_CLOSED = "VOLUME_CLOSED"
    FINALIZED = "FINALIZED"


class CompliancePosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    SHORTFALL = "SHORTFALL"
    SATISFIED = "SATISFIED"


class DiligenceStatus(str, Enum):
    UNVETTED = "UNVETTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class RINLotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class RINLotOrigin(str, Enum):
    GENERATED = "GENERATED"
    PURCHASED = "PURCHASED"


class DCode(str, Enum):
    D3 = "D3"
    D4 = "D4"
    D5 = "D5"
    D6 = "D6"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class TransferStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    VERIFIED = "VERIFIED"
    INVALIDATED = "INVALIDATED"
    CANCELLED = "CANCELLED"


class RetirementCategory(str, Enum):
    CELLULOSIC = "CELLULOSIC"
    BIOMASS_DIESEL = "BIOMASS_DIESEL"
    ADVANCED = "ADVANCED"
    TOTAL_RENEWABLE = "TOTAL_RENEWABLE"


class RetirementBatchStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ReportType(str, Enum):
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class ComplianceReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class AttestEngagementStatus(str, Enum):
    ENGAGED = "ENGAGED"
    FIELDWORK = "FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    REMEDIATION = "REMEDIATION"
    CLOSED_CLEAN = "CLOSED_CLEAN"


class AttestFindings(str, Enum):
    CLEAN = "CLEAN"
    ADVERSE = "ADVERSE"


class StateCreditReportStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    VERIFIED = "VERIFIED"


class ProgramType(str, Enum):
    LCFS = "LCFS"


class ComplianceAccount(TypedDict):
    id: str
    company_name: str
    epa_registration_id: str
    escrow_reserved_cents: int
    spent_cents: int
    created_at: str
    updated_at: str
    version: int


class ObligationYear(TypedDict):
    id: str
    account_id: str
    year: int
    projected_volume_gal: int
    actual_volume_gal: Optional[int]
    std_cellulosic_pct: float
    std_biomass_diesel_pct: float
    std_advanced_pct: float
    std_total_pct: float
    status: str
    provisional_rvo_cellulosic_rins: int
    provisional_rvo_biomass_diesel_rins: int
    provisional_rvo_advanced_rins: int
    provisional_rvo_total_rins: int
    final_rvo_cellulosic_rins: Optional[int]
    final_rvo_biomass_diesel_rins: Optional[int]
    final_rvo_advanced_rins: Optional[int]
    final_rvo_total_rins: Optional[int]
    retired_cellulosic_rins: int
    retired_biomass_diesel_rins: int
    retired_advanced_rins: int
    retired_total_rins: int
    retired_prior_cellulosic_rins: int
    retired_prior_biomass_diesel_rins: int
    retired_prior_advanced_rins: int
    retired_prior_total_rins: int
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    account_id: str
    vendor_name: str
    qap_audited: bool
    diligence_status: str
    last_diligence_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RINLot(TypedDict):
    id: str
    account_id: str
    origin: str
    vendor_id: Optional[str]
    trade_id: Optional[str]
    d_code: str
    vintage_year: int
    gallon_qty: int
    equivalence_value: float
    rin_qty: int
    attached_qty: int
    separated_qty: int
    pending_retired_qty: int
    retired_qty: int
    invalidated_qty: int
    expired_qty: int
    available_qty: int
    unit_cost_cents: int
    status: str
    retention_until: str
    created_at: str
    updated_at: str
    version: int


class BlendingRecord(TypedDict):
    # Immutable event log: id + created_at only (no updated_at, no version).
    id: str
    account_id: str
    rin_lot_id: str
    blended_gallons: int
    blended_at: str
    retention_until: str
    created_at: str


class RINTrade(TypedDict):
    id: str
    account_id: str
    vendor_id: str
    d_code: str
    vintage_year: int
    rin_qty: int
    price_per_rin_cents: int
    total_price_cents: int
    payment_status: str
    transfer_status: str
    created_by_user_id: str
    delivered_at: Optional[str]
    verified_by_user_id: Optional[str]
    retention_until: str
    created_at: str
    updated_at: str
    version: int


class RetirementBatch(TypedDict):
    id: str
    obligation_year_id: str
    category: str
    d_code: str
    rin_qty: int
    allocations: list
    prior_vintage_qty: int
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict):
    id: str
    obligation_year_id: str
    report_type: str
    quarter_end_date: Optional[str]
    due_date: str
    status: str
    created_by_user_id: str
    submitted_at: Optional[str]
    is_late: bool
    amendment_required: bool
    retention_until: str
    created_at: str
    updated_at: str
    version: int


class AttestEngagement(TypedDict):
    id: str
    obligation_year_id: str
    auditor_user_id: str
    fieldwork_start: str
    fieldwork_end: str
    status: str
    findings: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StateProgram(TypedDict):
    id: str
    account_id: str
    state_code: str
    program_type: str
    ci_standard_gco2e_mj: float
    default_ci_gco2e_mj: float
    total_credits_tons: float
    created_at: str
    updated_at: str
    version: int


class StateCreditReport(TypedDict):
    id: str
    state_program_id: str
    period_label: str
    fuel_gallons: int
    status: str
    measured_ci_gco2e_mj: Optional[float]
    credits_tons: float
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceQuote(TypedDict):
    id: str
    account_id: str
    d_code: str
    vintage_year: int
    price_cents: int
    effective_start: str
    effective_end: str
    retention_until: str
    created_at: str
    updated_at: str
    version: int
