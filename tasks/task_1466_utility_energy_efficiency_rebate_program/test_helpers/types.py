"""Domain types: entity TypedDicts, status enums, role enum.

Entities with the full system-managed quartet carry id + created_at +
updated_at + version. Append-only records (savings claims, fraud flags)
carry only id + created_at and MUST NOT list updated_at / version.
"""
from enum import Enum
from typing import Optional, TypedDict


class ProgramYearStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REPORTED = "REPORTED"


class TradeAllyEnrollStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class StandingTier(str, Enum):
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    PROBATION = "PROBATION"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PRE_INSPECTION = "PRE_INSPECTION"
    POST_INSPECTION = "POST_INSPECTION"
    VERIFIED = "VERIFIED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AutoFlagStatus(str, Enum):
    CLEAR = "CLEAR"
    SUSPECT = "SUSPECT"


class PacingTier(str, Enum):
    STANDARD_TIER = "STANDARD_TIER"
    MID_TIER = "MID_TIER"
    HIGH_TIER = "HIGH_TIER"


class InspectionKind(str, Enum):
    PRE = "PRE"
    POST = "POST"


class InspectionOutcome(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ClaimMethod(str, Enum):
    DEEMED = "DEEMED"
    MEASURED = "MEASURED"


class FraudFlagKind(str, Enum):
    SAME_SERVICE_ADDRESS = "SAME_SERVICE_ADDRESS"
    ALLY_BURST = "ALLY_BURST"
    INVOICE_GAP_SMALL = "INVOICE_GAP_SMALL"


class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    TRADE_ALLY = "TradeAlly"
    VERIFICATION_INSPECTOR = "VerificationInspector"
    PAYMENT_PROCESSOR = "PaymentProcessor"
    REGULATOR_ANALYST = "RegulatorAnalyst"


class ProgramYear(TypedDict, total=False):
    id: str
    program_code: str
    program_year_label: str
    budget_cap_cents: int
    savings_goal_kwh: int
    committed_cents: int
    paid_cents: int
    reported_kwh: int
    adjusted_kwh: int
    goal_attainment_pct: int
    status: str
    opened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Measure(TypedDict, total=False):
    id: str
    program_year_id: str
    measure_code: str
    measure_name: str
    base_rate_cents: int
    deemed_kwh_per_unit: int
    requires_post_inspection: bool
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class TradeAlly(TypedDict, total=False):
    id: str
    ally_name: str
    license_number: str
    performance_score: int
    standing_tier: str
    enroll_status: str
    created_at: str
    updated_at: str
    version: int


class RebateApplication(TypedDict, total=False):
    id: str
    program_year_id: str
    trade_ally_id: str
    customer_account_number: str
    service_address: str
    invoice_number: str
    invoice_date: str
    incentive_total_cents: int
    claimed_kwh: int
    final_kwh: int
    inspection_required: bool
    risk_score: int
    auto_flag_status: str
    status: str
    submitted_at: Optional[str]
    verified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApplicationLineItem(TypedDict, total=False):
    id: str
    application_id: str
    measure_id: str
    quantity: int
    pacing_tier_at_submit: Optional[str]
    incentive_cents: Optional[int]
    claimed_kwh: Optional[int]
    measured_kwh: Optional[int]
    final_kwh: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SavingsClaim(TypedDict, total=False):
    # Append-only record: carries only id + created_at (no updated_at, no version)
    id: str
    line_item_id: str
    claim_method: str
    pre_annual_kwh: Optional[int]
    post_annual_kwh: Optional[int]
    computed_kwh: Optional[int]
    created_at: str


class Inspection(TypedDict, total=False):
    id: str
    application_id: str
    inspection_kind: str
    scheduled_on: str
    completed_on: Optional[str]
    outcome: str
    fail_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvaluationAdjustment(TypedDict, total=False):
    id: str
    program_year_id: str
    realization_rate_pct: int
    effective_on: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudFlag(TypedDict, total=False):
    # Append-only record: carries only id + created_at (no updated_at, no version)
    id: str
    application_id: str
    flag_kind: str
    weight: int
    detail: str
    created_at: str
