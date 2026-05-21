"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 splits entities into two shapes:

    common-fields (Veteran, Dependent, Claim, School, Enrollment,
    YellowRibbonContribution, VocRehabPlan):
        id, created_at, updated_at, version

    append-only (HousingPayment, PaymentLedgerEntry):
        "Two entities in this domain are append-only ledger rows and
        therefore carry only id and created_at: HousingPayment and
        PaymentLedgerEntry. Once written, neither row is updated, so
        neither carries updated_at or version."
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    VETERAN = "Veteran"
    VA_CLERK = "VAClerk"
    RATER = "Rater"
    COUNSELOR = "Counselor"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class Branch(str, Enum):
    ARMY = "ARMY"
    NAVY = "NAVY"
    AIR_FORCE = "AIR_FORCE"
    MARINES = "MARINES"
    COAST_GUARD = "COAST_GUARD"
    SPACE_FORCE = "SPACE_FORCE"


class DischargeStatus(str, Enum):
    HONORABLE = "HONORABLE"
    GENERAL = "GENERAL"
    OTHER_THAN_HONORABLE = "OTHER_THAN_HONORABLE"
    BAD_CONDUCT = "BAD_CONDUCT"
    DISHONORABLE = "DISHONORABLE"


class Relationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARENT = "PARENT"


class DependentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ClaimType(str, Enum):
    ORIGINAL = "ORIGINAL"
    SUPPLEMENTAL = "SUPPLEMENTAL"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    DENIED_FINAL = "DENIED_FINAL"


class ProgramType(str, Enum):
    PUBLIC_IN_STATE = "PUBLIC_IN_STATE"
    PRIVATE_NATIONAL = "PRIVATE_NATIONAL"
    FOREIGN = "FOREIGN"
    VOC_TECH = "VOC_TECH"


class TrainingTime(str, Enum):
    FULL_TIME = "FULL_TIME"
    THREE_QUARTER = "THREE_QUARTER"
    HALF_TIME = "HALF_TIME"
    LESS_THAN_HALF = "LESS_THAN_HALF"


class DeliveryMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    ONLINE_ONLY = "ONLINE_ONLY"


class EnrollmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    CANCELED = "CANCELED"


class ComputationBasis(str, Enum):
    IN_PERSON_TIERED = "IN_PERSON_TIERED"
    ONLINE_HALF_NATIONAL = "ONLINE_HALF_NATIONAL"
    PRORATED_PARTIAL_MONTH = "PRORATED_PARTIAL_MONTH"


class VocRehabTrainingMode(str, Enum):
    FULL_TIME_INSTITUTIONAL = "FULL_TIME_INSTITUTIONAL"
    THREE_QUARTER_INSTITUTIONAL = "THREE_QUARTER_INSTITUTIONAL"
    HALF_TIME_INSTITUTIONAL = "HALF_TIME_INSTITUTIONAL"
    FARM_COOP = "FARM_COOP"
    NON_PAY_OJT = "NON_PAY_OJT"


class VocRehabPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class PaymentLedgerSource(str, Enum):
    TUITION_PAYMENT = "TUITION_PAYMENT"
    HOUSING_PAYMENT = "HOUSING_PAYMENT"
    YELLOW_RIBBON_VA_MATCH = "YELLOW_RIBBON_VA_MATCH"
    VOC_REHAB_SUBSISTENCE = "VOC_REHAB_SUBSISTENCE"
    ENTITLEMENT_DEBIT = "ENTITLEMENT_DEBIT"


# ---------------------------------------------------------------------------
# Common-fields entities — PRD §2.4
# ---------------------------------------------------------------------------
class Veteran(TypedDict, total=False):
    id: str
    full_name: str
    branch: str
    aggregate_active_duty_days: int
    discharge_status: str
    combined_rating: int
    post_911_eligibility_tier: int
    months_entitlement_used: float
    created_at: str
    updated_at: str
    version: int


class Dependent(TypedDict, total=False):
    id: str
    veteran_id: str
    relationship: str
    date_of_birth: str
    school_enrolled: bool
    status: str
    removed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    veteran_id: str
    condition_code: str
    claim_type: str
    original_claim_id: Optional[str]
    status: str
    proposed_rating: int
    granted_rating: Optional[int]
    decided_at: Optional[str]
    rater_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class School(TypedDict, total=False):
    id: str
    name: str
    facility_code: str
    program_type: str
    yellow_ribbon_enrolled: bool
    yellow_ribbon_max_per_year: float
    zip_bah_code: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    veteran_id: str
    school_id: str
    term_start: str
    term_end: str
    tuition_charged: float
    training_time: str
    delivery_mode: str
    status: str
    months_consumed: float
    certified_tuition_payable: Optional[float]
    created_at: str
    updated_at: str
    version: int


class YellowRibbonContribution(TypedDict, total=False):
    id: str
    enrollment_id: str
    tuition_gap: float
    school_contribution: float
    va_match: float
    student_responsibility: float
    created_at: str
    updated_at: str
    version: int


class VocRehabPlan(TypedDict, total=False):
    id: str
    veteran_id: str
    training_mode: str
    counselor_id: Optional[str]
    status: str
    suspension_count: int
    monthly_subsistence: Optional[float]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — PRD §2.4: id + created_at only
# ---------------------------------------------------------------------------
class HousingPayment(TypedDict, total=False):
    id: str
    enrollment_id: str
    month_year: str
    amount: float
    computation_basis: str
    created_at: str


class PaymentLedgerEntry(TypedDict, total=False):
    id: str
    veteran_id: str
    source_entity: str
    source_id: str
    amount_dollars: float
    posted_at: str
    created_at: str


__all__ = [
    "UserRole",
    "Branch",
    "DischargeStatus",
    "Relationship",
    "DependentStatus",
    "ClaimType",
    "ClaimStatus",
    "ProgramType",
    "TrainingTime",
    "DeliveryMode",
    "EnrollmentStatus",
    "ComputationBasis",
    "VocRehabTrainingMode",
    "VocRehabPlanStatus",
    "PaymentLedgerSource",
    "Veteran",
    "Dependent",
    "Claim",
    "School",
    "Enrollment",
    "YellowRibbonContribution",
    "VocRehabPlan",
    "HousingPayment",
    "PaymentLedgerEntry",
]
