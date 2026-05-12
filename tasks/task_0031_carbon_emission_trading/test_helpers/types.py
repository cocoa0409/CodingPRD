"""Domain types for the Carbon Emission Trading API.

Status enums and entity TypedDicts derived from PRD §2.4 (Common Resource
Properties) and §3 entity prose.

PRD §2.4 distinguishes two field-shape classes:
- Common-fields entities (Enterprise, AllocationCycle, Allocation,
  EmissionReport, VerificationAssignment, TradingOrder, ComplianceDeclaration,
  PenaltyOrder, AnnualSettlement) carry id, created_at, updated_at, version.
- Lighter entities (Objection, EmissionDataLine, SupportingDocument, Trade,
  AuditLogEntry) carry only id and created_at — tests MUST NOT assert
  updated_at or version on these.
"""
from __future__ import annotations
from enum import Enum
from typing import TypedDict, Optional, List, Any, Dict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    REGULATOR = "Regulator"
    ENTERPRISE = "Enterprise"
    VERIFIER_AGENCY = "VerifierAgency"


# ---------------------------------------------------------------------------
# Reference-data vocabularies
# ---------------------------------------------------------------------------
class JurisdictionCode(str, Enum):
    JD_ALPHA = "JD_ALPHA"
    JD_BETA = "JD_BETA"
    JD_GAMMA = "JD_GAMMA"


class IndustryCode(str, Enum):
    POWER = "POWER"
    STEEL = "STEEL"
    CEMENT = "CEMENT"
    CHEMICAL = "CHEMICAL"
    PETROCHEMICAL = "PETROCHEMICAL"


class AllocationMethod(str, Enum):
    INDUSTRY_BENCHMARK = "INDUSTRY_BENCHMARK"
    HISTORICAL_EMISSION = "HISTORICAL_EMISSION"


class EmissionSourceCategory(str, Enum):
    FUEL = "FUEL"
    ELECTRICITY = "ELECTRICITY"
    PROCESS = "PROCESS"
    FUGITIVE = "FUGITIVE"


class SupportingDocumentType(str, Enum):
    FUEL_INVOICE = "FUEL_INVOICE"
    METER_LOG = "METER_LOG"
    PROCESS_SHEET = "PROCESS_SHEET"
    EXTERNAL_AUDIT = "EXTERNAL_AUDIT"


class TradingSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TradingInstrument(str, Enum):
    QUOTA = "QUOTA"
    CCER = "CCER"


class TradingOrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class TradingChannel(str, Enum):
    EXCHANGE = "EXCHANGE"
    BLOCK = "BLOCK"
    OTC = "OTC"


class PenaltySeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class AuditSubjectType(str, Enum):
    QUOTA_CHANGE = "QUOTA_CHANGE"
    TRADE_RECORD = "TRADE_RECORD"
    EXTERNAL_SYNC = "EXTERNAL_SYNC"


class ExternalSystem(str, Enum):
    BANK = "BANK"
    REGULATOR = "REGULATOR"
    ENERGY_DATA = "ENERGY_DATA"


# ---------------------------------------------------------------------------
# Entity status enums (PRD §3)
# ---------------------------------------------------------------------------
class EnterpriseAccountStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class AllocationCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    OBJECTION_OPEN = "OBJECTION_OPEN"
    FINALIZED = "FINALIZED"
    COMPLIANCE_OPEN = "COMPLIANCE_OPEN"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class AllocationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PUBLISHED = "PUBLISHED"
    OBJECTED = "OBJECTED"
    REVISED = "REVISED"
    FINALIZED = "FINALIZED"


class ObjectionStatus(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class EmissionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_VERIFICATION = "UNDER_VERIFICATION"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    REJECTED = "REJECTED"


class VerificationAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    SCHEDULED = "SCHEDULED"
    ON_SITE_DONE = "ON_SITE_DONE"
    REPORT_ISSUED = "REPORT_ISSUED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class TradingOrderStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TradeSettlementStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class ComplianceDeclarationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    PENALIZED = "PENALIZED"
    FINALIZED = "FINALIZED"


class PenaltyPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"


class AnnualSettlementStatus(str, Enum):
    PENDING = "PENDING"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Common-fields entity TypedDicts (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Enterprise(TypedDict, total=False):
    id: str
    legal_name: str
    jurisdiction_code: str
    industry_code: str
    contact_email: str
    account_status: str
    quota_balance: float
    paid_quota_balance: float
    ccer_balance: float
    created_at: str
    updated_at: str
    version: int


class AllocationCycle(TypedDict, total=False):
    id: str
    cycle_year: int
    status: str
    free_paid_ratio: float
    ccer_cap_pct: float
    publication_date: Optional[str]
    objection_deadline: str
    compliance_deadline: str
    settlement_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    enterprise_id: str
    method: str
    activity_volume: Optional[float]
    benchmark_factor: Optional[float]
    historical_baseline: Optional[float]
    total_quota: Optional[float]
    free_quota: Optional[float]
    paid_quota: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class EmissionReport(TypedDict, total=False):
    id: str
    cycle_year: int
    version: int
    status: str
    submission_deadline: str
    submitted_at: Optional[str]
    total_reported_emissions: float
    total_verified_emissions: Optional[float]
    is_current_version: bool
    supporting_document_count: int
    created_at: str
    updated_at: str


class VerificationAssignment(TypedDict, total=False):
    id: str
    agency_id: str
    scheduled_visit_at: str
    status: str
    cross_check_delta_pct: Optional[float]
    report_issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradingOrder(TypedDict, total=False):
    id: str
    enterprise_id: str
    side: str
    instrument: str
    order_type: str
    quantity: float
    limit_price: Optional[float]
    filled_quantity: float
    status: str
    channel: str
    placed_at: str
    created_at: str
    updated_at: str
    version: int


class ComplianceDeclaration(TypedDict, total=False):
    id: str
    cycle_year: int
    declared_offset_quota: float
    declared_offset_ccer: float
    declared_borrow_amount: float
    declared_bank_amount: float
    status: str
    deficit_amount: float
    surplus_amount: float
    created_at: str
    updated_at: str
    version: int


class PenaltyOrder(TypedDict, total=False):
    id: str
    severity: str
    penalty_rate: float
    deficit_amount: float
    penalty_amount: float
    mandatory_deduction_amount: float
    payment_status: str
    payment_due_at: str
    paid_at: Optional[str]
    credit_record_reported: bool
    created_at: str
    updated_at: str
    version: int


class AnnualSettlement(TypedDict, total=False):
    id: str
    enterprise_id: str
    opening_quota: float
    net_traded_quota: float
    retired_quota: float
    closing_balance: float
    carry_forward_amount: float
    repurchase_amount: float
    deficit_purchase_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lighter entity TypedDicts (id + created_at only; PRD §2.4)
# ---------------------------------------------------------------------------
class Objection(TypedDict, total=False):
    id: str
    filer_enterprise_id: str
    ground: str
    status: str
    revised_total_quota: Optional[float]
    filed_at: str
    resolved_at: Optional[str]
    created_at: str


class EmissionDataLine(TypedDict, total=False):
    id: str
    source_category: str
    activity_data: float
    emission_factor: float
    source_amount: float
    verified_amount: Optional[float]
    supporting_document_id: Optional[str]
    created_at: str


class SupportingDocument(TypedDict, total=False):
    id: str
    document_type: str
    file_uri: str
    uploaded_at: str
    created_at: str


class Trade(TypedDict, total=False):
    id: str
    buy_order_id: str
    sell_order_id: str
    instrument: str
    quantity: float
    price: float
    gross_value: float
    buyer_fee: float
    seller_fee: float
    settlement_status: str
    executed_at: str
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    enterprise_id: Optional[str]
    action: str
    delta_quota: float
    delta_ccer: float
    external_system: Optional[str]
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "JurisdictionCode",
    "IndustryCode",
    "AllocationMethod",
    "EmissionSourceCategory",
    "SupportingDocumentType",
    "TradingSide",
    "TradingInstrument",
    "TradingOrderType",
    "TradingChannel",
    "PenaltySeverity",
    "AuditSubjectType",
    "ExternalSystem",
    "EnterpriseAccountStatus",
    "AllocationCycleStatus",
    "AllocationStatus",
    "ObjectionStatus",
    "EmissionReportStatus",
    "VerificationAssignmentStatus",
    "TradingOrderStatus",
    "TradeSettlementStatus",
    "ComplianceDeclarationStatus",
    "PenaltyPaymentStatus",
    "AnnualSettlementStatus",
    "Enterprise",
    "AllocationCycle",
    "Allocation",
    "EmissionReport",
    "VerificationAssignment",
    "TradingOrder",
    "ComplianceDeclaration",
    "PenaltyOrder",
    "AnnualSettlement",
    "Objection",
    "EmissionDataLine",
    "SupportingDocument",
    "Trade",
    "AuditLogEntry",
]
