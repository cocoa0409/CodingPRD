"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Community Solar API resource model from PRD §2 and §3.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────

class UserRole(str, Enum):
    GRID_OPERATOR = "GridOperator"
    PROGRAM_ADMIN = "ProgramAdmin"
    SUBSCRIBER = "Subscriber"


# ─── Status enums ─────────────────────────────────────────────────────

class ProjectStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class EnrollmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    ACTIVATED = "ACTIVATED"
    REJECTED = "REJECTED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TRANSFERRING = "TRANSFERRING"
    CANCELLED = "CANCELLED"


class WaitlistStatus(str, Enum):
    QUEUED = "QUEUED"
    PROMOTED = "PROMOTED"
    WITHDRAWN = "WITHDRAWN"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    METERED = "METERED"
    RECONCILED = "RECONCILED"
    TRUED_UP = "TRUED_UP"
    CLOSED = "CLOSED"


class AllocationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    VOID = "VOID"


class CreditStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    APPLIED = "APPLIED"


class DisputeStatus(str, Enum):
    NONE = "NONE"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class RECBatchStatus(str, Enum):
    MINTED = "MINTED"
    ALLOCATED = "ALLOCATED"
    RETIRED = "RETIRED"
    TRANSFERRED = "TRANSFERRED"


# ─── Entity TypedDicts ────────────────────────────────────────────────
# Entities below carry common fields id + created_at + updated_at + version,
# except CarveOutAdjustment which is an append-only audit record (id + created_at only).


class SolarProject(TypedDict):
    id: str
    name: str
    state_code: str
    nameplate_capacity_kw: float
    carve_out_pct: float
    credit_rate_cents_per_kwh: int
    program_fee_rate: float
    committed_kw: float
    carve_out_committed_kw: float
    available_kw: float
    carve_out_available_kw: float
    rec_minted_total: int
    rec_retired_total: int
    rec_available_balance: int
    total_net_savings_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict):
    id: str
    full_name: str
    utility_account_no: str
    state_code: str
    is_low_income: bool
    annual_usage_kwh: int
    churn_risk_score: int
    lifetime_savings_cents: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    project_id: str
    subscriber_id: str
    requested_share_kw: float
    status: str
    rejection_reason: Optional[str]
    subscription_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    project_id: str
    subscriber_id: str
    enrollment_id: str
    share_kw: float
    is_carve_out: bool
    status: str
    transferred_from_subscription_id: Optional[str]
    cancellation_effective_period_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    project_id: str
    subscriber_id: str
    requested_share_kw: float
    queued_at: str
    status: str
    promoted_enrollment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict):
    id: str
    project_id: str
    period_month: str
    sequence_index: int
    forecast_production_kwh: int
    metered_production_kwh: Optional[int]
    status: str
    distributable_kwh: int
    allocated_kwh_total: int
    overproduction_kwh: int
    rollover_kwh: int
    forfeited_kwh: int
    rollover_credit_cents: int
    rec_minted_count: int
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    period_id: str
    subscription_id: str
    share_kw_snapshot: float
    allocated_kwh: int
    provisional_credit_cents: int
    final_credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Reconciliation(TypedDict):
    id: str
    subscription_id: str
    period_id: str
    allocation_id: str
    gross_credit_cents: int
    program_fee_cents: int
    net_savings_cents: int
    credit_status: str
    dispute_status: str
    created_at: str
    updated_at: str
    version: int


class RECBatch(TypedDict):
    id: str
    project_id: str
    period_id: str
    rec_count: int
    retirement_beneficiary: Optional[str]
    transfer_counterparty: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields:false — append-only audit record (PRD §2.4): id + created_at only.
class CarveOutAdjustment(TypedDict):
    id: str
    project_id: str
    previous_carve_out_pct: float
    new_carve_out_pct: float
    reason: str
    created_at: str
