"""Domain types for the Stock Option Incentive API.

Entity TypedDicts, status enums, and role enum. Mutable entities carry
id + created_at + updated_at + version; append-only entities carry only
id + created_at (no updated_at, no version) per PRD §2.4.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    BOARD_SECRETARY = "BoardSecretary"
    SHAREHOLDER_REGISTRAR = "ShareholderRegistrar"
    GRANTEE = "Grantee"
    AUDIT_VIEWER = "AuditViewer"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class OptionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class GrantBatchStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_FOR_GRANTS = "OPEN_FOR_GRANTS"
    LOCKED = "LOCKED"


class GranteeEligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    DEPARTED = "DEPARTED"


class GrantStatus(str, Enum):
    DRAFT = "DRAFT"
    BOARD_APPROVED = "BOARD_APPROVED"
    SHAREHOLDER_APPROVED = "SHAREHOLDER_APPROVED"
    AGREEMENT_SIGNED = "AGREEMENT_SIGNED"
    LIVE = "LIVE"
    FROZEN = "FROZEN"
    TERMINATED = "TERMINATED"


class ExerciseWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class ExerciseApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ELIGIBILITY_VERIFIED = "ELIGIBILITY_VERIFIED"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    TAX_WITHHELD = "TAX_WITHHELD"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DepartureRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    SETTLED = "SETTLED"


class SettlementMode(str, Enum):
    SHARE_ISSUANCE = "SHARE_ISSUANCE"
    CASH_SETTLEMENT = "CASH_SETTLEMENT"


class JurisdictionCode(str, Enum):
    US = "US"
    UK = "UK"
    CN = "CN"
    SG = "SG"


class VestingAlgorithm(str, Enum):
    ANNIVERSARY_BATCH = "ANNIVERSARY_BATCH"
    CONTINUOUS_DAILY = "CONTINUOUS_DAILY"


class VestingPeriod(int, Enum):
    MONTHLY = 1
    QUARTERLY = 3
    ANNUAL = 12


class CorporateEventType(str, Enum):
    EARNINGS_BLACKOUT = "EARNINGS_BLACKOUT"
    MATERIAL_EVENT_BLACKOUT = "MATERIAL_EVENT_BLACKOUT"
    STOCK_SPLIT = "STOCK_SPLIT"
    CASH_DIVIDEND = "CASH_DIVIDEND"
    RESTRUCTURING = "RESTRUCTURING"
    CHANGE_OF_CONTROL = "CHANGE_OF_CONTROL"
    IPO = "IPO"


class PriceVersionCause(str, Enum):
    INITIAL = "INITIAL"
    STOCK_SPLIT = "STOCK_SPLIT"
    CASH_DIVIDEND = "CASH_DIVIDEND"
    RESTRUCTURING = "RESTRUCTURING"


class VestingRecordCause(str, Enum):
    CLIFF = "CLIFF"
    PERIODIC = "PERIODIC"
    PERFORMANCE_ATTEST = "PERFORMANCE_ATTEST"
    ACCELERATION_CHANGE_OF_CONTROL = "ACCELERATION_CHANGE_OF_CONTROL"
    ACCELERATION_IPO = "ACCELERATION_IPO"


class TaxEventType(str, Enum):
    GRANT = "GRANT"
    VEST = "VEST"
    EXERCISE = "EXERCISE"
    SALE = "SALE"


class DepartureType(str, Enum):
    RESIGNATION = "RESIGNATION"
    TERMINATION = "TERMINATION"
    RETIREMENT = "RETIREMENT"
    DEATH = "DEATH"


class LeaverClass(str, Enum):
    GOOD_LEAVER = "GOOD_LEAVER"
    BAD_LEAVER = "BAD_LEAVER"


class AuditActionCode(str, Enum):
    GRANT_CREATED = "GRANT_CREATED"
    GRANT_BOARD_APPROVED = "GRANT_BOARD_APPROVED"
    GRANT_SHAREHOLDER_APPROVED = "GRANT_SHAREHOLDER_APPROVED"
    GRANT_AGREEMENT_SIGNED = "GRANT_AGREEMENT_SIGNED"
    GRANT_TERMINATED = "GRANT_TERMINATED"
    EXERCISE_SUBMITTED = "EXERCISE_SUBMITTED"
    EXERCISE_SETTLED = "EXERCISE_SETTLED"
    EXERCISE_REJECTED = "EXERCISE_REJECTED"
    PRICE_VERSION_CREATED = "PRICE_VERSION_CREATED"
    DEPARTURE_SETTLED = "DEPARTURE_SETTLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — mutable entities (common_fields: true)
# carry id, created_at, updated_at, version (PRD §2.4)
# ---------------------------------------------------------------------------
class OptionPlan(TypedDict, total=False):
    id: str
    name: str
    pool_total_options: int
    pool_reserved_options: int
    pool_remaining_options: int
    jurisdiction_code: str
    current_clock_ts: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantBatch(TypedDict, total=False):
    id: str
    plan_id: str
    batch_label: str
    cliff_months: int
    vesting_total_months: int
    vesting_period_months: int
    vesting_algorithm: str
    performance_condition_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Grantee(TypedDict, total=False):
    id: str
    plan_id: str
    hr_employee_id: str
    full_name: str
    tax_residency: str
    eligibility_status: str
    departed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict, total=False):
    id: str
    plan_id: str
    batch_id: str
    grantee_id: str
    quantity: int
    grant_date: Optional[str]
    grant_date_fair_value_cents: int
    pinned_price_version_id: Optional[str]
    board_approval_actor_id: Optional[str]
    shareholder_approval_actor_id: Optional[str]
    submitted_by_actor_id: str
    vested_quantity: int
    exercised_quantity: int
    forfeited_quantity: int
    outstanding_quantity: int
    performance_attested_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExerciseWindow(TypedDict, total=False):
    id: str
    plan_id: str
    label: str
    open_ts: str
    close_ts: str
    status: str
    notified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExerciseApplication(TypedDict, total=False):
    id: str
    plan_id: str
    grant_id: str
    window_id: str
    pinned_price_version_id: str
    requested_quantity: int
    settlement_mode: str
    gross_proceeds_cents: Optional[int]
    withholding_tax_cents: Optional[int]
    net_proceeds_cents: Optional[int]
    payment_reference: Optional[str]
    share_registry_reference: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DepartureRecord(TypedDict, total=False):
    id: str
    grantee_id: str
    departure_type: str
    leaver_class: Optional[str]
    departed_ts: str
    post_departure_window_days: int
    post_departure_exercise_deadline_ts: Optional[str]
    forfeited_options_total: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (common_fields: false) — only id and created_at
# per PRD §2.4
# ---------------------------------------------------------------------------
class CorporateEvent(TypedDict, total=False):
    id: str
    plan_id: str
    event_type: str
    effective_ts: str
    blackout_end_ts: Optional[str]
    split_ratio_numerator: Optional[int]
    split_ratio_denominator: Optional[int]
    dividend_amount_cents: Optional[int]
    restructure_factor_bps: Optional[int]
    created_at: str


class ExercisePriceVersion(TypedDict, total=False):
    id: str
    plan_id: str
    batch_id: str
    version_index: int
    parent_version_id: Optional[str]
    cause: str
    corporate_event_id: Optional[str]
    price_per_option_cents: int
    effective_from_ts: str
    disclosed_at: Optional[str]
    created_at: str


class VestingRecord(TypedDict, total=False):
    id: str
    grant_id: str
    tranche_index: int
    vested_ts: str
    tranche_quantity: int
    cause: str
    archived: bool
    created_at: str


class TaxEventRecord(TypedDict, total=False):
    id: str
    grant_id: str
    exercise_application_id: Optional[str]
    event_type: str
    taxable_amount_cents: int
    withheld_amount_cents: int
    deferred: bool
    jurisdiction_code: str
    document_id: Optional[str]
    event_ts: str
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    plan_id: str
    actor_id: str
    actor_role: str
    action_code: str
    target_entity: str
    target_id: str
    payload_summary: dict
    occurred_ts: str
    created_at: str


__all__ = [
    "UserRole",
    "OptionPlanStatus",
    "GrantBatchStatus",
    "GranteeEligibilityStatus",
    "GrantStatus",
    "ExerciseWindowStatus",
    "ExerciseApplicationStatus",
    "DepartureRecordStatus",
    "SettlementMode",
    "JurisdictionCode",
    "VestingAlgorithm",
    "VestingPeriod",
    "CorporateEventType",
    "PriceVersionCause",
    "VestingRecordCause",
    "TaxEventType",
    "DepartureType",
    "LeaverClass",
    "AuditActionCode",
    "OptionPlan",
    "GrantBatch",
    "Grantee",
    "Grant",
    "ExerciseWindow",
    "ExerciseApplication",
    "DepartureRecord",
    "CorporateEvent",
    "ExercisePriceVersion",
    "VestingRecord",
    "TaxEventRecord",
    "AuditLogEntry",
]
