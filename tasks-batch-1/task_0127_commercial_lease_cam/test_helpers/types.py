"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Commercial Lease & CAM Reconciliation PRD. Mutable entities
carry id/created_at/updated_at/version; append-only entities (SalesReport,
LedgerEntry) carry only id/created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────────────────

class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    HOLDOVER = "HOLDOVER"
    TERMINATED = "TERMINATED"


class TiDrawStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReconciliationStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    POSTED = "POSTED"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class EstoppelStatus(str, Enum):
    ISSUED = "ISSUED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"


class ExpensePoolStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class ProRataDenominator(str, Enum):
    TOTAL_RENTABLE = "TOTAL_RENTABLE"
    OCCUPIED = "OCCUPIED"


class Recoverability(str, Enum):
    RECOVERABLE = "RECOVERABLE"
    NON_RECOVERABLE = "NON_RECOVERABLE"
    CAPPED_CONTROLLABLE = "CAPPED_CONTROLLABLE"


class EscalationType(str, Enum):
    FIXED_PCT = "FIXED_PCT"
    CPI = "CPI"
    NONE = "NONE"


class ExpenseCategory(str, Enum):
    LANDSCAPING = "LANDSCAPING"
    SECURITY = "SECURITY"
    UTILITIES = "UTILITIES"
    INSURANCE = "INSURANCE"
    MANAGEMENT = "MANAGEMENT"
    TAXES = "TAXES"
    REPAIRS = "REPAIRS"
    SNOW_REMOVAL = "SNOW_REMOVAL"


class LedgerEntryType(str, Enum):
    BASE_RENT = "BASE_RENT"
    PCT_RENT = "PCT_RENT"
    CAM_ESTIMATE = "CAM_ESTIMATE"
    CAM_TRUEUP = "CAM_TRUEUP"
    TI_DRAW = "TI_DRAW"
    PAYMENT = "PAYMENT"
    CREDIT_ADJUSTMENT = "CREDIT_ADJUSTMENT"


class TenantResponse(str, Enum):
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"


class UserRole(str, Enum):
    PROPERTY_MANAGER = "PropertyManager"
    ACCOUNTANT = "Accountant"
    TENANT = "Tenant"


# ─── Mutable entities (id + created_at + updated_at + version) ────────────

class Property(TypedDict):
    id: str
    name: str
    total_rentable_sqft: int
    occupied_sqft: int
    gross_up_occupancy_pct: float
    created_at: str
    updated_at: str
    version: int


class ExpensePool(TypedDict):
    id: str
    property_id: str
    pool_year: int
    pro_rata_denominator: str
    admin_fee_pct: float
    status: str
    total_recoverable_cents: int
    created_at: str
    updated_at: str
    version: int


class ExpenseLineItem(TypedDict):
    id: str
    pool_id: str
    category: str
    amount_cents: int
    recoverability: str
    is_variable: bool
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    property_id: str
    tenant_id: str
    leased_sqft: int
    base_rent_cents_annual: int
    escalation_type: str
    escalation_rate: float
    cpi_base_index: Optional[float]
    pct_rent_rate: float
    pct_rent_breakpoint_cents: int
    controllable_cap_pct: float
    prior_year_capped_base_cents: int
    ti_allowance_cents: int
    ti_drawn_cents: int
    estimated_cam_cents_monthly: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TiDraw(TypedDict):
    id: str
    lease_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reconciliation(TypedDict):
    id: str
    lease_id: str
    pool_id: str
    recon_year: int
    pro_rata_share_pct: float
    reconciled_cam_cents: int
    estimated_cam_billed_cents: int
    true_up_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EstoppelCertificate(TypedDict):
    id: str
    lease_id: str
    asserted_balance_cents: int
    asserted_base_rent_cents_annual: int
    tenant_response: Optional[str]
    dispute_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entities (id + created_at only) ──────────────────────────

class SalesReport(TypedDict):
    id: str
    lease_id: str
    period_year: int
    gross_sales_cents: int
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    lease_id: str
    entry_type: str
    amount_cents: int
    source_reconciliation_id: Optional[str]
    created_at: str
