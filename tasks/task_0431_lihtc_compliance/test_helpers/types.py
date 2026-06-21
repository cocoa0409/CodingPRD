"""Domain types for the LIHTC Compliance API: entity TypedDicts, status enums, role enum.

All entities in this system carry the full common-field set (PRD §2.5): id, created_at,
updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ─────────────────────────────
class UserRole(str, Enum):
    OWNER_AGENT = "OwnerAgent"
    STATE_HFA = "StateHFA"


# ─── Status / enum value sets ─────────────────────────
class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    SET_ASIDE_MET = "SET_ASIDE_MET"
    CREDIT_PERIOD = "CREDIT_PERIOD"
    COMPLIANCE_PERIOD = "COMPLIANCE_PERIOD"
    CLOSED = "CLOSED"


class ProjectPosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    NONCOMPLIANT = "NONCOMPLIANT"


class MinimumSetAside(str, Enum):
    TWENTY_FIFTY = "TWENTY_FIFTY"
    FORTY_SIXTY = "FORTY_SIXTY"
    AVERAGE_INCOME = "AVERAGE_INCOME"


class CreditType(str, Enum):
    NINE_PERCENT = "NINE_PERCENT"
    FOUR_PERCENT = "FOUR_PERCENT"


class CreditStatus(str, Enum):
    PRE_ALLOCATION = "PRE_ALLOCATION"
    PROVISIONAL_8609 = "PROVISIONAL_8609"
    FINAL_8609 = "FINAL_8609"
    RECAPTURED = "RECAPTURED"


class AmiDesignation(str, Enum):
    AMI_40 = "AMI_40"
    AMI_50 = "AMI_50"
    AMI_60 = "AMI_60"
    AMI_80 = "AMI_80"
    MARKET = "MARKET"


class LiStatus(str, Enum):
    VACANT_NEVER_OCCUPIED = "VACANT_NEVER_OCCUPIED"
    QUALIFIED = "QUALIFIED"
    OVER_INCOME = "OVER_INCOME"
    DISQUALIFIED = "DISQUALIFIED"
    MARKET_RENTED = "MARKET_RENTED"


class StudentException(str, Enum):
    NONE = "NONE"
    TANF = "TANF"
    JOB_TRAINING = "JOB_TRAINING"
    SINGLE_PARENT = "SINGLE_PARENT"
    MARRIED_JOINT_FILER = "MARRIED_JOINT_FILER"
    FORMER_FOSTER = "FORMER_FOSTER"


class CertType(str, Enum):
    INITIAL = "INITIAL"
    RECERT = "RECERT"


class CertStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LeaseStatus(str, Enum):
    ACTIVE = "ACTIVE"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    CLOSED = "CLOSED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FindingCategory(str, Enum):
    OVER_INCOME_UNCURED = "OVER_INCOME_UNCURED"
    STUDENT_VIOLATION = "STUDENT_VIOLATION"
    RENT_OVERCHARGE = "RENT_OVERCHARGE"
    UPCS_FAIL = "UPCS_FAIL"
    SET_ASIDE_FAILURE = "SET_ASIDE_FAILURE"
    AVAILABLE_UNIT_VIOLATION = "AVAILABLE_UNIT_VIOLATION"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    CORRECTED = "CORRECTED"
    REPORTED_8823 = "REPORTED_8823"


class IssuanceType(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class Form8609Status(str, Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


# ─── Entity TypedDicts (all carry common fields, PRD §2.5) ─────

class Project(TypedDict):
    id: str
    name: str
    area_median_income_cents: int
    minimum_set_aside: str
    placed_in_service_date: str
    status: str
    posture: str
    open_finding_count: int
    created_at: str
    updated_at: str
    version: int


class Building(TypedDict):
    id: str
    project_id: str
    bin: str
    eligible_basis_cents: int
    credit_type: str
    total_residential_units: int
    total_residential_sqft: int
    applicable_fraction: float
    qualified_basis_cents: int
    first_year_fraction: float
    annual_credit_cents: int
    credit_status: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    building_id: str
    unit_number: str
    bedroom_count: int
    sqft: int
    utility_allowance_cents: int
    ami_designation: str
    income_limit_cents: Optional[int]
    gross_rent_ceiling_cents: Optional[int]
    net_max_rent_cents: Optional[int]
    li_status: str
    is_low_income_counted: bool
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict):
    id: str
    project_id: str
    head_name: str
    household_size: int
    all_full_time_students: bool
    student_exception: str
    student_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    household_id: str
    unit_id: str
    cert_type: str
    annual_income_cents: int
    effective_date: str
    status: str
    over_income_threshold_cents: Optional[int]
    is_over_income: bool
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    household_id: str
    unit_id: str
    monthly_rent_cents: int
    rent_start_date: str
    rent_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    building_id: str
    window_start: str
    window_end: str
    inspected_on: str
    deduction_points: List[int]
    has_exigent_health_safety: bool
    score: Optional[int]
    result: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict):
    id: str
    project_id: str
    building_id: str
    inspection_id: Optional[str]
    category: str
    discovered_on: str
    origin_agent_id: str
    status: str
    reported_8823_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Form8609(TypedDict):
    id: str
    building_id: str
    issuance_type: str
    allocated_fraction: float
    allocated_annual_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
