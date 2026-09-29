"""Domain types for the percentage-rent and retail sales reporting service.

Status enums, role names and entity shapes exactly as the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CENTER_ADMIN = "CenterAdmin"
    LEASE_ADMINISTRATOR = "LeaseAdministrator"
    TENANT_USER = "TenantUser"
    AUDITOR = "Auditor"
    OWNERSHIP_ANALYST = "OwnershipAnalyst"


class TenantCategory(str, Enum):
    ANCHOR = "ANCHOR"
    JUNIOR_ANCHOR = "JUNIOR_ANCHOR"
    INLINE = "INLINE"
    FOOD = "FOOD"
    KIOSK = "KIOSK"


class TenantStatus(str, Enum):
    PROSPECT = "PROSPECT"
    OPERATING = "OPERATING"
    DARK = "DARK"
    VACATED = "VACATED"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RELIEF_ACTIVE = "RELIEF_ACTIVE"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"


class CoTenancyPosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    VIOLATION_OPEN = "VIOLATION_OPEN"
    RELIEF_ACTIVE = "RELIEF_ACTIVE"


class WatchlistStatus(str, Enum):
    NORMAL = "NORMAL"
    WATCHLIST = "WATCHLIST"


class BreakpointType(str, Enum):
    NATURAL = "NATURAL"
    ARTIFICIAL = "ARTIFICIAL"


class BillingMode(str, Enum):
    CUMULATIVE_YTD = "CUMULATIVE_YTD"
    PERIOD_STANDALONE = "PERIOD_STANDALONE"


class ReportingFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class ExclusionProfile(str, Enum):
    STANDARD = "STANDARD"
    RESTRICTIVE = "RESTRICTIVE"


class LeaseYearStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILING = "RECONCILING"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"


class SalesReportStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    UNDER_AUDIT = "UNDER_AUDIT"
    DISPUTED = "DISPUTED"
    AMENDED = "AMENDED"
    ADJUSTED = "ADJUSTED"
    ESTIMATED = "ESTIMATED"
    VOID = "VOID"


class SalesReportSource(str, Enum):
    TENANT_REPORTED = "TENANT_REPORTED"
    LANDLORD_ESTIMATE = "LANDLORD_ESTIMATE"
    AUDIT_ADJUSTED = "AUDIT_ADJUSTED"


class ExclusionCode(str, Enum):
    RETURNS_AND_ALLOWANCES = "RETURNS_AND_ALLOWANCES"
    SALES_TAX = "SALES_TAX"
    GIFT_CARD_ISSUANCE = "GIFT_CARD_ISSUANCE"
    INTERCOMPANY_TRANSFER = "INTERCOMPANY_TRANSFER"
    EMPLOYEE_DISCOUNT = "EMPLOYEE_DISCOUNT"
    ONLINE_SHIP_FROM_STORE = "ONLINE_SHIP_FROM_STORE"
    VENDING_AND_SERVICE = "VENDING_AND_SERVICE"


class ExclusionStatus(str, Enum):
    CLAIMED = "CLAIMED"
    ALLOWED = "ALLOWED"
    PARTIALLY_ALLOWED = "PARTIALLY_ALLOWED"
    DISALLOWED = "DISALLOWED"


class ChargeType(str, Enum):
    PERIODIC = "PERIODIC"
    ESTIMATE = "ESTIMATE"
    TRUE_UP = "TRUE_UP"
    CREDIT = "CREDIT"


class BillingStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID = "VOID"


class CollectionStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class MonitoringStatus(str, Enum):
    SATISFIED = "SATISFIED"
    VIOLATED = "VIOLATED"


class ReliefType(str, Enum):
    RENT_REDUCTION = "RENT_REDUCTION"
    ALTERNATIVE_SALES_RENT = "ALTERNATIVE_SALES_RENT"


class CoTenancyEventType(str, Enum):
    ANCHOR_WENT_DARK = "ANCHOR_WENT_DARK"
    OCCUPANCY_BELOW_FLOOR = "OCCUPANCY_BELOW_FLOOR"


class CoTenancyEventStatus(str, Enum):
    OPEN = "OPEN"
    CURE_PENDING = "CURE_PENDING"
    RELIEF_ACTIVE = "RELIEF_ACTIVE"
    CURED = "CURED"
    TERMINATION_ELECTED = "TERMINATION_ELECTED"


class KickOutStatus(str, Enum):
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    WAIVED = "WAIVED"
    EXERCISED = "EXERCISED"
    EXPIRED = "EXPIRED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    SETTLED = "SETTLED"
    RESCINDED = "RESCINDED"


class LedgerEntryType(str, Enum):
    REPORT_ACCEPTED = "REPORT_ACCEPTED"
    REPORT_WITHDRAWN = "REPORT_WITHDRAWN"
    ESTIMATE_ISSUED = "ESTIMATE_ISSUED"
    ESTIMATE_VOIDED = "ESTIMATE_VOIDED"
    PERIODIC_CHARGE_ISSUED = "PERIODIC_CHARGE_ISSUED"
    TRUE_UP_ISSUED = "TRUE_UP_ISSUED"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    AUDIT_ADJUSTMENT = "AUDIT_ADJUSTMENT"
    AUDIT_RESCINDED = "AUDIT_RESCINDED"


# The counted set: reports whose net sales feed every cumulative figure.
COUNTED_REPORT_STATUSES = [
    SalesReportStatus.ACCEPTED.value,
    SalesReportStatus.UNDER_AUDIT.value,
    SalesReportStatus.DISPUTED.value,
    SalesReportStatus.ADJUSTED.value,
    SalesReportStatus.ESTIMATED.value,
]


# ─── Entity shapes ────────────────────────────────────────────────────────
# Every entity below carries id / created_at / updated_at / version, except
# ReportingLedgerEntry, which is append-only and carries only id / created_at.

class ShoppingCenter(TypedDict):
    id: str
    name: str
    code: str
    total_gla_sqft: int
    anchor_gla_sqft: int
    fiscal_year_start_month: int
    occupied_gla_sqft: int
    occupancy_bps: int
    open_anchor_count: int
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict):
    id: str
    center_id: str
    legal_name: str
    trade_name: str
    category: str
    gla_sqft: int
    is_anchor: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    center_id: str
    tenant_id: str
    suite_code: str
    leased_sqft: int
    annual_base_rent_cents: int
    percentage_rate_bps: int
    breakpoint_type: str
    artificial_breakpoint_cents: Optional[int]
    natural_breakpoint_cents: int
    effective_breakpoint_cents: int
    billing_mode: str
    reporting_frequency: str
    reporting_deadline_days: int
    exclusion_profile: str
    status: str
    co_tenancy_status: str
    effective_monthly_rent_cents: int
    relief_monthly_credit_cents: int
    relief_approved_by_user_id: Optional[str]
    waiver_approved_by_user_id: Optional[str]
    delinquency_strikes: int
    ytd_occupancy_cost_cents: int
    occupancy_cost_ratio_bps: int
    watchlist_status: str
    created_at: str
    updated_at: str
    version: int


class LeaseYear(TypedDict):
    id: str
    lease_id: str
    year_index: int
    period_start: str
    period_end: str
    breakpoint_cents: int
    percentage_rate_bps_snapshot: int
    billing_mode_snapshot: str
    cumulative_net_sales_cents: int
    cumulative_billed_cents: int
    true_up_delta_cents: Optional[int]
    open_audit_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesReport(TypedDict):
    id: str
    lease_year_id: str
    period_start: str
    period_end: str
    due_at: str
    submitted_at: Optional[str]
    gross_sales_cents: Optional[int]
    allowed_exclusions_cents: int
    net_sales_cents: int
    source: str
    amendment_round: int
    is_delinquent: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesExclusion(TypedDict):
    id: str
    sales_report_id: str
    code: str
    claimed_cents: int
    allowed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PercentageRentCharge(TypedDict):
    id: str
    lease_year_id: str
    sales_report_id: Optional[str]
    supersedes_charge_id: Optional[str]
    charge_type: str
    amount_cents: int
    billing_status: str
    collection_status: str
    paid_cents: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoTenancyClause(TypedDict):
    id: str
    lease_id: str
    required_open_anchor_count: int
    required_occupancy_bps: int
    cure_period_days: int
    relief_type: str
    relief_pct_bps: int
    termination_right_after_days: int
    monitoring_status: str
    created_at: str
    updated_at: str
    version: int


class CoTenancyEvent(TypedDict):
    id: str
    clause_id: str
    trigger_tenant_id: Optional[str]
    event_type: str
    observed_at: str
    cure_deadline_at: str
    relief_started_at: Optional[str]
    relief_ended_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class KickOutClause(TypedDict):
    id: str
    lease_id: str
    measurement_year_index: int
    threshold_sales_cents: int
    election_window_days: int
    triggered_at: Optional[str]
    election_deadline_at: Optional[str]
    waiver_consideration_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesAudit(TypedDict):
    id: str
    lease_id: str
    sales_report_id: str
    audit_window_start: str
    audit_window_end: str
    proposed_adjustment_cents: Optional[int]
    settled_adjustment_cents: Optional[int]
    auditor_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReportingLedgerEntry(TypedDict):
    """Append-only: carries id and created_at only — no updated_at, no version."""
    id: str
    lease_year_id: str
    entry_type: str
    delta_net_sales_cents: int
    delta_billed_cents: int
    note: str
    created_at: str


class CenterSalesTrend(TypedDict):
    tenant_count: int
    comp_sqft: int
    current_net_sales_cents: int
    prior_net_sales_cents: int
    comp_growth_bps: int
    percentage_rent_cents: int
    sales_psf_cents: int
    occupancy_cost_ratio_bps: int


__all__: List[str] = [
    "UserRole", "TenantCategory", "TenantStatus", "LeaseStatus",
    "CoTenancyPosture", "WatchlistStatus", "BreakpointType", "BillingMode",
    "ReportingFrequency", "ExclusionProfile", "LeaseYearStatus",
    "SalesReportStatus", "SalesReportSource", "ExclusionCode",
    "ExclusionStatus", "ChargeType", "BillingStatus", "CollectionStatus",
    "MonitoringStatus", "ReliefType", "CoTenancyEventType",
    "CoTenancyEventStatus", "KickOutStatus", "AuditStatus", "LedgerEntryType",
    "COUNTED_REPORT_STATUSES", "ShoppingCenter", "Tenant", "Lease",
    "LeaseYear", "SalesReport", "SalesExclusion", "PercentageRentCharge",
    "CoTenancyClause", "CoTenancyEvent", "KickOutClause", "SalesAudit",
    "ReportingLedgerEntry", "CenterSalesTrend",
]
