"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Benefits Open Enrollment PRD (Sections 2-3). Mutable, versioned
resources carry id/created_at/updated_at/version; the two immutable ledger events
(DeductionLine, CarrierFeedRecord) carry only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────

class UserRole(str, Enum):
    BENEFITS_ADMIN = "BenefitsAdmin"
    DEPENDENT_VERIFIER = "DependentVerifier"
    PAYROLL_OFFICER = "PayrollOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ─── Status / value enums ─────────────────────────────

class EligibilityStatus(str, Enum):
    WAITING = "WAITING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    TERMINATED = "TERMINATED"


class EmploymentType(str, Enum):
    FULL_TIME = "FULL_TIME"
    PART_TIME = "PART_TIME"
    SEASONAL = "SEASONAL"


class PayrollSchedule(str, Enum):
    SEMI_MONTHLY = "SEMI_MONTHLY"
    BIWEEKLY = "BIWEEKLY"


class WaitingPeriodWindowType(str, Enum):
    INITIAL = "INITIAL"
    REINSTATEMENT = "REINSTATEMENT"


class WaitingPeriodStatus(str, Enum):
    PENDING = "PENDING"
    ELAPSED = "ELAPSED"


class BenefitType(str, Enum):
    MEDICAL = "MEDICAL"
    DENTAL = "DENTAL"
    VISION = "VISION"
    VOLUNTARY_LIFE = "VOLUNTARY_LIFE"


class PlanOfferingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class CoverageLevel(str, Enum):
    EMPLOYEE_ONLY = "EMPLOYEE_ONLY"
    EMPLOYEE_PLUS_SPOUSE = "EMPLOYEE_PLUS_SPOUSE"
    EMPLOYEE_PLUS_CHILDREN = "EMPLOYEE_PLUS_CHILDREN"
    EMPLOYEE_PLUS_FAMILY = "EMPLOYEE_PLUS_FAMILY"


class DependentRelationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    INFO_REQUESTED = "INFO_REQUESTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class EnrollmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_EOI = "PENDING_EOI"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class LifeEventType(str, Enum):
    BIRTH = "BIRTH"
    MARRIAGE = "MARRIAGE"
    DIVORCE = "DIVORCE"
    LOSS_OF_COVERAGE = "LOSS_OF_COVERAGE"


class AdjustmentMode(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    RETROACTIVE = "RETROACTIVE"


class LifeEventStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EOIDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DeductionLineType(str, Enum):
    REGULAR = "REGULAR"
    RETRO_ADJUSTMENT = "RETRO_ADJUSTMENT"


class CarrierTransactionSet(str, Enum):
    ADD = "ADD"
    TERM = "TERM"
    CHANGE = "CHANGE"


class Form1095CStatus(str, Enum):
    GENERATED = "GENERATED"
    FILED = "FILED"


class AffordabilityIndicator(str, Enum):
    AFFORDABLE = "AFFORDABLE"
    UNAFFORDABLE = "UNAFFORDABLE"


# ─── Entity TypedDicts (mutable, versioned) ───────────

class Employee(TypedDict):
    id: str
    full_name: str
    hire_date: str
    employment_type: str
    payroll_schedule: str
    monthly_household_income_cents: int
    eligibility_status: str
    pay_periods_processed: int
    created_at: str
    updated_at: str
    version: int


class WaitingPeriod(TypedDict):
    id: str
    employee_id: str
    window_type: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanOffering(TypedDict):
    id: str
    benefit_type: str
    name: str
    requires_eoi: bool
    guaranteed_issue_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanTier(TypedDict):
    id: str
    plan_offering_id: str
    coverage_level: str
    monthly_premium_cents: int
    employer_contribution_pct: float
    rate_per_1000_monthly_cents: int
    is_lowest_cost_self_only: bool
    created_at: str
    updated_at: str
    version: int


class Dependent(TypedDict):
    id: str
    employee_id: str
    relationship: str
    full_name: str
    date_of_birth: str
    verification_status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    employee_id: str
    plan_tier_id: str
    benefit_type: str
    coverage_amount_cents: int
    coverage_start_date: str
    coverage_end_date: Optional[str]
    monthly_employee_cost_cents: int
    per_paycheck_deduction_cents: int
    covered_dependent_count: int
    source_life_event_id: Optional[str]
    superseded_by_enrollment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LifeEvent(TypedDict):
    id: str
    employee_id: str
    event_type: str
    event_date: str
    requested_plan_tier_id: str
    requested_coverage_amount_cents: int
    submitted_by_user_id: str
    adjustment_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EOIRequest(TypedDict):
    id: str
    enrollment_id: str
    excess_coverage_cents: int
    decision: str
    created_at: str
    updated_at: str
    version: int


class Form1095C(TypedDict):
    id: str
    employee_id: str
    tax_year: int
    lowest_cost_monthly_premium_cents: int
    affordability_threshold_cents: int
    affordability_indicator: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Immutable ledger events (id + created_at only) ───

class DeductionLine(TypedDict):
    id: str
    enrollment_id: str
    employee_id: str
    pay_period_index: int
    line_type: str
    amount_cents: int
    created_at: str


class CarrierFeedRecord(TypedDict):
    id: str
    enrollment_id: str
    transaction_set: str
    reconciled_monthly_premium_cents: int
    created_at: str
