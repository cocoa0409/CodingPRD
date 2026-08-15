"""Domain types: entity TypedDicts, status enums, role enum.

All ten resources carry the PRD's common properties (id, created_at,
updated_at, version). TypedDicts are total=False so optional/nullable
fields (extended_due_date, filed_on, measured_on, settled_amount_cents,
approved_by_user_id, reviewed_by_user_id, proposed/agreed adjustment)
may be absent or null without type noise.
"""
from enum import Enum
from typing import Optional, TypedDict


class TaxYearStatus(str, Enum):
    OPEN = "OPEN"
    PROVISION_LOCKED = "PROVISION_LOCKED"
    RETURNS_FILED = "RETURNS_FILED"
    CLOSED = "CLOSED"


class JurisdictionLevel(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    FOREIGN = "FOREIGN"


class DifferenceType(str, Enum):
    TEMPORARY = "TEMPORARY"
    PERMANENT = "PERMANENT"


class DifferenceStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    REVIEWED = "REVIEWED"
    LOCKED = "LOCKED"
    REJECTED = "REJECTED"


class DeferredItemKind(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"


class AllowanceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class PositionStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    MEASURED = "MEASURED"
    DISCLOSED = "DISCLOSED"
    SETTLED = "SETTLED"
    LAPSED = "LAPSED"


class PaymentMethod(str, Enum):
    PRIOR_YEAR_SAFE_HARBOR = "PRIOR_YEAR_SAFE_HARBOR"
    CURRENT_YEAR_ANNUALIZED = "CURRENT_YEAR_ANNUALIZED"


class PaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    LATE = "LATE"
    PAID = "PAID"


class FilingStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    AMENDED = "AMENDED"


class ExtensionStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class NoticeType(str, Enum):
    INFORMATION_REQUEST = "INFORMATION_REQUEST"
    AUDIT_OPENING = "AUDIT_OPENING"
    PROPOSED_ADJUSTMENT = "PROPOSED_ADJUSTMENT"
    PENALTY_ASSESSMENT = "PENALTY_ASSESSMENT"


class NoticeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    OVERDUE = "OVERDUE"
    RESPONDED = "RESPONDED"
    RESOLVED = "RESOLVED"


class AuditStatus(str, Enum):
    UNDER_EXAMINATION = "UNDER_EXAMINATION"
    ADJUSTMENT_PROPOSED = "ADJUSTMENT_PROPOSED"
    NEGOTIATING = "NEGOTIATING"
    CLOSED_AGREED = "CLOSED_AGREED"
    CLOSED_NO_CHANGE = "CLOSED_NO_CHANGE"


class UserRole(str, Enum):
    TAX_ACCOUNTANT = "TaxAccountant"
    TAX_MANAGER = "TaxManager"
    TAX_DIRECTOR = "TaxDirector"
    AUDITOR = "Auditor"
    PLATFORM_ADMIN = "PlatformAdmin"


class TaxYear(TypedDict, total=False):
    id: str
    fiscal_year_label: str
    period_start_date: str
    period_end_date: str
    enacted_federal_rate_bp: int
    pretax_book_income_cents: int
    prior_year_total_tax_cents: int
    status: str
    current_provision_cents: int
    deferred_expense_cents: int
    net_deferred_asset_cents: int
    valuation_allowance_cents: int
    utp_liability_cents: int
    return_to_provision_adjustment_cents: int
    forecast_etr_bp: int
    actual_etr_bp: int
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict, total=False):
    id: str
    code: str
    name: str
    level: str
    statutory_rate_bp: int
    apportionment_pct_bp: int
    return_due_month: int
    return_due_day: int
    extension_months: int
    created_at: str
    updated_at: str
    version: int


class BookTaxDifference(TypedDict, total=False):
    id: str
    tax_year_id: str
    jurisdiction_id: Optional[str]
    description: str
    book_amount_cents: int
    tax_amount_cents: int
    difference_cents: int
    difference_type: str
    status: str
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeferredTaxItem(TypedDict, total=False):
    id: str
    tax_year_id: str
    source_difference_id: str
    item_kind: str
    opening_balance_cents: int
    movement_cents: int
    closing_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ValuationAllowance(TypedDict, total=False):
    id: str
    tax_year_id: str
    more_likely_than_not: bool
    projected_taxable_income_cents: int
    reversing_dtl_cents: int
    assessment_note: Optional[str]
    allowance_amount_cents: int
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UncertainTaxPosition(TypedDict, total=False):
    id: str
    tax_year_id: str
    jurisdiction_id: str
    description: str
    position_amount_cents: int
    cumulative_probability_bp: int
    recognized_benefit_cents: int
    liability_cents: int
    measured_on: Optional[str]
    interest_accrued_cents: int
    disclosure_required: bool
    settled_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class EstimatedPayment(TypedDict, total=False):
    id: str
    tax_year_id: str
    jurisdiction_id: str
    quarter_index: int
    period_start_date: str
    period_end_date: str
    due_date: str
    method: str
    base_scheduled_amount_cents: int
    scheduled_amount_cents: int
    paid_amount_cents: int
    penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Filing(TypedDict, total=False):
    id: str
    tax_year_id: str
    jurisdiction_id: str
    original_due_date: str
    extended_due_date: Optional[str]
    extension_status: str
    status: str
    return_tax_liability_cents: int
    estimated_liability_cents: int
    filed_on: Optional[str]
    is_late: bool
    created_at: str
    updated_at: str
    version: int


class TaxNotice(TypedDict, total=False):
    id: str
    jurisdiction_id: str
    audit_case_id: Optional[str]
    notice_type: str
    received_on: str
    response_due_on: str
    response_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict, total=False):
    id: str
    tax_year_id: str
    jurisdiction_id: str
    exam_period_start: str
    exam_period_end: str
    opened_on: str
    proposed_adjustment_cents: Optional[int]
    agreed_adjustment_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
