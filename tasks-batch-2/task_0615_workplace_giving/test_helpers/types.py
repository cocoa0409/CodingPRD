"""Domain types: entity TypedDicts, status enums, role enum.

All entities in the Workplace Giving API are mutable and therefore carry the
common fields id, created_at, updated_at, and version (PRD 2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum -------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    GIVING_ADMIN = "GivingAdmin"
    EMPLOYEE = "Employee"
    SYSTEM = "system"


# --- Status enums ----------------------------------------------------------
class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CharityStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class DonationStatus(str, Enum):
    PLEDGED = "PLEDGED"
    AUTHORIZED = "AUTHORIZED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class DonationType(str, Enum):
    ONE_TIME = "ONE_TIME"
    RECURRING = "RECURRING"


class FundingMethod(str, Enum):
    PAYROLL_DEDUCTION = "PAYROLL_DEDUCTION"
    CREDIT = "CREDIT"


class ScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class MatchingGiftStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FINALIZED = "FINALIZED"
    CAPPED = "CAPPED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class VolunteerLogStatus(str, Enum):
    LOGGED = "LOGGED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class DisbursementBatchStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class GrantStatus(str, Enum):
    STAGED = "STAGED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class GrantSourceType(str, Enum):
    DONATION = "DONATION"
    MATCH = "MATCH"
    DFD = "DFD"


class TaxStatementStatus(str, Enum):
    GENERATED = "GENERATED"
    FINAL = "FINAL"


# --- Entity TypedDicts (all common_fields: true) ---------------------------
class Program(TypedDict, total=False):
    id: str
    name: str
    tax_year: int
    match_ratio: float
    tiered_matching_enabled: bool
    tier_1_ceiling_cents: int
    tier_1_rate: float
    tier_2_rate: float
    annual_match_cap_cents: int
    dfd_rate_cents_per_hour: int
    dfd_annual_cap_cents: int
    roundup_enabled: bool
    processing_fee_tier_threshold_cents: int
    processing_fee_low_rate: float
    processing_fee_high_rate: float
    disbursement_admin_fee_rate: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    program_id: str
    email: str
    full_name: str
    annual_salary_cents: int
    match_consumed_ytd_cents: int
    dfd_consumed_ytd_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Charity(TypedDict, total=False):
    id: str
    program_id: str
    legal_name: str
    ein: str
    claimed_501c3: bool
    total_received_cents: int
    review_rounds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    program_id: str
    charity_id: str
    name: str
    goal_cents: int
    window_start: str
    window_end: str
    raised_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict, total=False):
    id: str
    program_id: str
    employee_id: str
    campaign_id: str
    donation_type: str
    funding_method: str
    base_amount_cents: int
    roundup_increment_cents: int
    subtotal_cents: int
    processing_fee_cents: int
    total_charged_cents: int
    tax_deductible: bool
    schedule_id: Optional[str]
    settled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PayrollDeductionSchedule(TypedDict, total=False):
    id: str
    program_id: str
    employee_id: str
    campaign_id: str
    per_period_amount_cents: int
    window_start: str
    window_end: str
    occurrences_generated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MatchingGift(TypedDict, total=False):
    id: str
    program_id: str
    donation_id: str
    employee_id: str
    raw_match_cents: int
    estimated_match_cents: int
    matched_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VolunteerLog(TypedDict, total=False):
    id: str
    program_id: str
    employee_id: str
    charity_id: str
    minutes: int
    activity_date: str
    raw_grant_cents: int
    grant_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DisbursementBatch(TypedDict, total=False):
    id: str
    program_id: str
    charity_id: str
    period_start: str
    period_end: str
    gross_total_cents: int
    admin_fee_cents: int
    net_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict, total=False):
    id: str
    program_id: str
    batch_id: str
    charity_id: str
    source_type: str
    source_id: str
    gross_amount_cents: int
    admin_fee_cents: int
    net_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxStatement(TypedDict, total=False):
    id: str
    program_id: str
    employee_id: str
    tax_year: int
    deductible_donations_cents: int
    matched_total_cents: int
    line_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
