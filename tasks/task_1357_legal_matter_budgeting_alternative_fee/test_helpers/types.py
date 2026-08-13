"""Domain types: entity TypedDicts, status enums, role enum.

All eleven resources carry the standard system-managed fields described in
PRD section 2.4: id, created_at, updated_at, version.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class MatterStatus(str, Enum):
    OPEN = "OPEN"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class LitigationStage(str, Enum):
    INTAKE = "INTAKE"
    PLEADINGS = "PLEADINGS"
    DISCOVERY = "DISCOVERY"
    PRETRIAL = "PRETRIAL"
    TRIAL = "TRIAL"
    APPEAL = "APPEAL"


class ArrangementType(str, Enum):
    FLAT_FEE = "FLAT_FEE"
    CAPPED_FEE = "CAPPED_FEE"
    SUCCESS_FEE = "SUCCESS_FEE"
    COLLAR = "COLLAR"


class FeeArrangementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class PhaseBudgetStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    AMENDED = "AMENDED"
    VOIDED = "VOIDED"


class TimeEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    BILLED = "BILLED"
    WRITTEN_DOWN = "WRITTEN_DOWN"
    REJECTED = "REJECTED"


class TimekeeperRoleTitle(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    PARTNER = "PARTNER"
    OF_COUNSEL = "OF_COUNSEL"
    PARALEGAL = "PARALEGAL"


class TimekeeperStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class WriteDownStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PARTNER = "PENDING_PARTNER"
    PENDING_MANAGING_PARTNER = "PENDING_MANAGING_PARTNER"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class WriteDownReasonCode(str, Enum):
    CLIENT_RELATIONS = "CLIENT_RELATIONS"
    BILLING_ERROR = "BILLING_ERROR"
    SCOPE_DISPUTE = "SCOPE_DISPUTE"
    COLLECTIBILITY = "COLLECTIBILITY"
    COURT_ORDER = "COURT_ORDER"


class AmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class AccrualReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPUTED = "DISPUTED"


class TrueUpStatus(str, Enum):
    COMPUTED = "COMPUTED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class TrueUpDirection(str, Enum):
    REBATE_TO_CLIENT = "REBATE_TO_CLIENT"
    COLLECT_FROM_CLIENT = "COLLECT_FROM_CLIENT"
    IN_BAND = "IN_BAND"


class VarianceAlertLevel(str, Enum):
    NONE = "NONE"
    WATCH = "WATCH"
    WARNING = "WARNING"
    BREACH = "BREACH"


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    PRICING_ANALYST = "PricingAnalyst"
    BILLING_PARTNER = "BillingPartner"
    MANAGING_PARTNER = "ManagingPartner"
    TIMEKEEPER = "Timekeeper"
    CLIENT_CONTACT = "ClientContact"


# --- Entity TypedDicts ---
# Every resource carries id / created_at / updated_at / version (PRD 2.4).


class Firm(TypedDict, total=False):
    id: str
    name: str
    fiscal_year_start_month: int
    current_period_index: int
    closed_through_period_index: int
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    firm_id: str
    display_name: str
    client_number: str
    accrual_reporting_required: bool
    accrual_reporting_cadence_periods: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Matter(TypedDict, total=False):
    id: str
    client_id: str
    firm_id: str
    matter_number: str
    title: str
    litigation_stage: str
    responsible_partner_id: str
    status: str
    fee_arrangement_id: Optional[str]
    budget_total_cents: int
    actual_fees_cents: int
    write_down_total_cents: int
    variance_cents: int
    variance_pct_bp: Optional[int]
    variance_alert_level: str
    revised_forecast_cents: int
    realization_rate_bp: int
    last_activity_period_index: int
    created_at: str
    updated_at: str
    version: int


class FeeArrangement(TypedDict, total=False):
    id: str
    matter_id: str
    firm_id: str
    arrangement_type: str
    flat_fee_cents: Optional[int]
    capped_fee_cents: Optional[int]
    success_fee_uplift_pct_bp: Optional[int]
    collar_lower_bound_cents: Optional[int]
    collar_upper_bound_cents: Optional[int]
    collar_share_pct_bp: Optional[int]
    fiscal_year_index: int
    status: str
    submitted_period_index: Optional[int]
    activated_period_index: Optional[int]
    supersedes_arrangement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PhaseBudget(TypedDict, total=False):
    id: str
    matter_id: str
    firm_id: str
    litigation_stage: str
    task_code: str
    original_budget_cents: int
    current_budget_cents: int
    actual_to_date_cents: int
    etc_cents: int
    status: str
    version_in_force: int
    created_at: str
    updated_at: str
    version: int


class TimeEntry(TypedDict, total=False):
    id: str
    matter_id: str
    firm_id: str
    timekeeper_id: str
    task_code: str
    litigation_stage: str
    hours_worked_milli: int
    hourly_rate_cents: int
    billable_amount_cents: int
    entry_date: str
    period_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Timekeeper(TypedDict, total=False):
    id: str
    firm_id: str
    full_name: str
    bar_number: str
    role_title: str
    standard_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WriteDownRequest(TypedDict, total=False):
    id: str
    matter_id: str
    firm_id: str
    time_entry_ids: List[str]
    requested_amount_cents: int
    approved_amount_cents: Optional[int]
    reason_code: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    decided_period_index: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetAmendment(TypedDict, total=False):
    id: str
    matter_id: str
    firm_id: str
    phase_budget_id: str
    delta_cents: int
    scope_change_reason: str
    supersedes_amendment_id: Optional[str]
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccrualReport(TypedDict, total=False):
    id: str
    matter_id: str
    firm_id: str
    period_index: int
    accrued_fees_cents: int
    unbilled_wip_cents: int
    forecast_at_complete_cents: Optional[int]
    variance_at_submission_cents: Optional[int]
    submitted_period_index: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CollarTrueUp(TypedDict, total=False):
    id: str
    matter_id: str
    firm_id: str
    fee_arrangement_id: str
    fiscal_year_index: int
    actual_year_fees_cents: int
    true_up_amount_cents: int
    direction: str
    status: str
    created_at: str
    updated_at: str
    version: int
