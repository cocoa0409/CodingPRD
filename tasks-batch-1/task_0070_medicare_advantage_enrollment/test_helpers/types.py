"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity definitions. Beneficiary, Plan, PartBEnrollment,
PartCEnrollment, PartDEnrollment, MedigapPolicy, and PenaltyAssessment carry the
common system fields (id, created_at, updated_at, version). EnrollmentPeriod and
DrugClaim are immutable computed records carrying only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ENROLLMENT_ADMIN = "EnrollmentAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class BeneficiaryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FRAUD_HOLD = "FRAUD_HOLD"
    DECEASED = "DECEASED"


class PartABStatus(str, Enum):
    NONE = "NONE"
    ENROLLED = "ENROLLED"


class PlanType(str, Enum):
    PART_C = "PART_C"
    PART_D = "PART_D"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PeriodType(str, Enum):
    IEP = "IEP"
    AEP = "AEP"
    SEP_5STAR = "SEP_5STAR"
    GI_MEDIGAP = "GI_MEDIGAP"


class PartBEnrollmentStatus(str, Enum):
    FILED = "FILED"
    ACTIVE = "ACTIVE"
    DROPPED = "DROPPED"
    VOIDED = "VOIDED"


class PartCEnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DISENROLLED = "DISENROLLED"
    VOIDED = "VOIDED"


class PartDEnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DISENROLLED = "DISENROLLED"
    VOIDED = "VOIDED"


class DrugPhase(str, Enum):
    DEDUCTIBLE = "DEDUCTIBLE"
    INITIAL = "INITIAL"
    GAP = "GAP"
    CATASTROPHIC = "CATASTROPHIC"


class MedigapPolicyStatus(str, Enum):
    ISSUED = "ISSUED"
    LAPSED = "LAPSED"
    VOIDED = "VOIDED"


class PenaltyType(str, Enum):
    PART_B = "PART_B"
    PART_D = "PART_D"


class PenaltyAssessmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    WAIVED = "WAIVED"


# ---- common_fields: true (id + created_at + updated_at + version) ----

class Beneficiary(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    part_a_status: str
    part_b_status: str
    part_b_effective_date: Optional[str]
    part_d_creditable_since: Optional[str]
    enrollment_lock: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict):
    id: str
    name: str
    part_type: str
    monthly_premium_cents: int
    star_rating: float
    includes_drug_coverage: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PartBEnrollment(TypedDict):
    id: str
    beneficiary_id: str
    enrollment_period_id: str
    requested_at: str
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PartCEnrollment(TypedDict):
    id: str
    beneficiary_id: str
    plan_id: str
    enrollment_period_id: str
    requested_at: str
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PartDEnrollment(TypedDict):
    id: str
    beneficiary_id: str
    plan_id: str
    enrollment_period_id: str
    requested_at: str
    uncovered_months: int
    lep_premium_cents: int
    total_drug_cost_cents: int
    member_oop_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MedigapPolicy(TypedDict):
    id: str
    beneficiary_id: str
    enrollment_period_id: str
    requested_at: str
    coverage_start: str
    coverage_end: str
    guaranteed_issue: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PenaltyAssessment(TypedDict):
    id: str
    beneficiary_id: str
    penalty_type: str
    uncovered_months: int
    monthly_penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---- common_fields: false (id + created_at only; no updated_at, no version) ----

class EnrollmentPeriod(TypedDict):
    id: str
    beneficiary_id: str
    period_type: str
    window_start: str
    window_end: str
    source_event_date: Optional[str]
    created_at: str


class DrugClaim(TypedDict):
    id: str
    part_d_enrollment_id: str
    list_price_cents: int
    incurred_at: str
    phase_at_post: str
    member_share_cents: int
    created_at: str
