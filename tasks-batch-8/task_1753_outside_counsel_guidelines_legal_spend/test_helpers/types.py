"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    LEGAL_OPS_REVIEWER = "LegalOpsReviewer"
    PANEL_FIRM_USER = "PanelFirmUser"


class PanelFirmStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class GuidelineVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class AcknowledgmentStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    OVERDUE = "OVERDUE"


class MatterEngagementStatus(str, Enum):
    PENDING = "PENDING"
    ENGAGED = "ENGAGED"
    CLOSED = "CLOSED"


class RateCardStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class TkClass(str, Enum):
    PARTNER = "PARTNER"
    ASSOCIATE = "ASSOCIATE"
    PARALEGAL = "PARALEGAL"


class QualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"


class InvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    VOID = "VOID"


class LineReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    ADJUSTED_APPROVED = "ADJUSTED_APPROVED"
    REJECTED = "REJECTED"
    REINSTATED = "REINSTATED"
    UPHELD = "UPHELD"


class RejectionReasonCode(str, Enum):
    BLOCK_BILLING = "BLOCK_BILLING"
    RATE_EXCEEDS_APPROVED = "RATE_EXCEEDS_APPROVED"
    UNAPPROVED_TIMEKEEPER = "UNAPPROVED_TIMEKEEPER"
    STAFFING_RATIO = "STAFFING_RATIO"
    OVER_BUDGET = "OVER_BUDGET"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


# All resources carry the common system-managed fields of PRD §2.4
# (id, created_at, updated_at, version).

class LegalDepartment(TypedDict):
    id: str
    name: str
    annual_rate_increase_cap_pct: float
    partner_ratio_min_pct: float
    partner_ratio_max_pct: float
    guideline_notice_days: int
    acknowledgment_window_days: int
    created_at: str
    updated_at: str
    version: int


class PanelFirm(TypedDict):
    id: str
    legal_department_id: str
    firm_name: str
    status: str
    scorecard_overall_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class GuidelineVersion(TypedDict):
    id: str
    legal_department_id: str
    version_label: str
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GuidelineAcknowledgment(TypedDict):
    id: str
    panel_firm_id: str
    guideline_version_id: str
    status: str
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Matter(TypedDict):
    id: str
    legal_department_id: str
    panel_firm_id: str
    title: str
    engagement_status: str
    budget_cents: int
    billed_to_date_cents: int
    accrual_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    panel_firm_id: str
    effective_year: int
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Timekeeper(TypedDict):
    id: str
    panel_firm_id: str
    full_name: str
    tk_class: str
    qualification_status: str
    created_at: str
    updated_at: str
    version: int


class TimekeeperRate(TypedDict):
    id: str
    rate_card_id: str
    timekeeper_id: str
    hourly_rate_cents: int
    approved_rate_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InvoiceLineItemInput(TypedDict):
    timekeeper_id: str
    utbms_task_code: str
    narrative: str
    hours: float
    rate_cents: int


class Invoice(TypedDict):
    id: str
    matter_id: str
    panel_firm_id: str
    invoice_number: str
    billing_period_start: str
    billing_period_end: str
    status: str
    submitted_total_cents: int
    approved_total_cents: int
    final_payable_cents: int
    created_at: str
    updated_at: str
    version: int


class InvoiceLineItem(TypedDict):
    id: str
    invoice_id: str
    timekeeper_id: str
    utbms_task_code: str
    narrative: str
    hours: float
    rate_cents: int
    amount_cents: int
    review_status: str
    adjusted_amount_cents: Optional[int]
    rejection_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    invoice_line_item_id: str
    rationale: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Accrual(TypedDict):
    id: str
    matter_id: str
    period_year: int
    period_month: int
    amount_cents: int
    matched_invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatterForecast(TypedDict):
    id: str
    matter_id: str
    lifecycle_estimate_cents: int
    wip_estimate_cents: int
    variance_cents: int
    created_at: str
    updated_at: str
    version: int


class ScorecardSnapshot(TypedDict):
    id: str
    panel_firm_id: str
    period_year: int
    period_month: int
    on_time_ack_pct: float
    rejection_rate_pct: float
    appeal_uphold_rate_pct: float
    accrual_timeliness_pct: float
    overall_pct: float
    created_at: str
    updated_at: str
    version: int
