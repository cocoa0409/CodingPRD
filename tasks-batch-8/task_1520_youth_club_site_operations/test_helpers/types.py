"""Domain types: entity TypedDicts, status enums, role enum (PRD Sections 2-4)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SITE_DIRECTOR = "SiteDirector"
    FRONTLINE_STAFF = "FrontlineStaff"
    STATE_AGENCY_REVIEWER = "StateAgencyReviewer"
    FUNDER_CONTACT = "FunderContact"


class MemberStatus(str, Enum):
    APPLIED = "APPLIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class EligibilityTier(str, Enum):
    FREE = "FREE"
    REDUCED = "REDUCED"
    PAID = "PAID"


class GuardianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class FundStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AwardStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    CANCELLED = "CANCELLED"
    EXHAUSTED = "EXHAUSTED"


class ClubDayStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class ClubDayPosture(str, Enum):
    NORMAL = "NORMAL"
    RATIO_STRAINED = "RATIO_STRAINED"
    OVER_CAPACITY = "OVER_CAPACITY"


class AttendanceStatus(str, Enum):
    ON_SITE = "ON_SITE"
    SIGNED_OUT = "SIGNED_OUT"
    MISSING_SIGNOUT = "MISSING_SIGNOUT"


class SignOutType(str, Enum):
    AUTHORIZED_PICKUP = "AUTHORIZED_PICKUP"
    WALKER = "WALKER"
    BUS = "BUS"


class RiskTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"


class RotationBlock(str, Enum):
    BLOCK_A = "BLOCK_A"
    BLOCK_B = "BLOCK_B"
    BLOCK_C = "BLOCK_C"


class RotationKind(str, Enum):
    YOUTH = "YOUTH"
    STAFF = "STAFF"


class RotationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    MOVED = "MOVED"


class RideStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class IncidentCategory(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class AdjudicationStatus(str, Enum):
    REPORTED = "REPORTED"
    ADJUDICATED = "ADJUDICATED"
    DISMISSED = "DISMISSED"


class SuspensionStatus(str, Enum):
    NONE = "NONE"
    IMPOSED = "IMPOSED"
    ACTIVE = "ACTIVE"
    APPEALED = "APPEALED"
    SERVED = "SERVED"
    RESCINDED = "RESCINDED"


class StaffPosition(str, Enum):
    DIRECTOR = "DIRECTOR"
    FRONTLINE = "FRONTLINE"


class StaffStatus(str, Enum):
    HIRED = "HIRED"
    ACTIVE = "ACTIVE"


class ComplianceStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    LAPSED = "LAPSED"
    EXPIRING = "EXPIRING"
    COMPLIANT = "COMPLIANT"


class FunderType(str, Enum):
    UNITED_WAY = "UNITED_WAY"
    STATE_GRANT = "STATE_GRANT"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class MealType(str, Enum):
    BREAKFAST = "BREAKFAST"
    SNACK = "SNACK"
    SUPPER = "SUPPER"


class CredentialKind(str, Enum):
    BACKGROUND_CHECK = "BACKGROUND_CHECK"
    TRAINING = "TRAINING"


# --- Entity TypedDicts -------------------------------------------------------
# Every resource carries the four audit fields id / created_at / updated_at /
# version (PRD Section 2.5: "no resource in this system omits any of the four").


class Site(TypedDict, total=False):
    id: str
    name: str
    youth_capacity: int
    standard_ratio: int
    elevated_ratio: int
    base_weekly_fee_cents: int
    registration_fee_cents: int
    max_arrears_cents: int
    fee_accrual_weekday: int
    meal_rates_cents: dict
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    site_id: str
    legal_name: str
    date_of_birth: str
    grade: int
    household_size: int
    household_income_cents: int
    walker_ok: bool
    status: str
    eligibility_tier: Optional[str]
    weekly_fee_cents: Optional[int]
    fee_balance_cents: int
    behavior_points: int
    discipline_watch: bool
    approved_at: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Guardian(TypedDict, total=False):
    id: str
    member_id: str
    full_name: str
    relation: str
    phone: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScholarshipFund(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    budget_cents: int
    reserved_cents: int
    disbursed_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScholarshipAward(TypedDict, total=False):
    id: str
    fund_id: str
    member_id: str
    discount_pct: float
    weekly_cap_cents: int
    annual_cap_cents: int
    disbursed_cents: int
    remaining_cap_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClubDay(TypedDict, total=False):
    id: str
    site_id: str
    date: str
    status: str
    present_count: int
    signed_out_count: int
    missing_signout_count: int
    meal_counts: dict
    posture: str
    weekly_fees_accrued: bool
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict, total=False):
    id: str
    club_day_id: str
    member_id: str
    sign_in_at: str
    sign_out_at: Optional[str]
    sign_out_type: Optional[str]
    pickup_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramArea(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    capacity: int
    risk_tier: str
    ratio_override: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RotationAssignment(TypedDict, total=False):
    id: str
    club_day_id: str
    area_id: str
    block: str
    kind: str
    member_id: Optional[str]
    staff_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportRoute(TypedDict, total=False):
    id: str
    site_id: str
    route_name: str
    school_name: str
    seat_capacity: int
    created_at: str
    updated_at: str
    version: int


class RideAssignment(TypedDict, total=False):
    id: str
    route_id: str
    member_id: str
    effective_start_date: str
    effective_end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MealClaim(TypedDict, total=False):
    id: str
    site_id: str
    claim_month: str
    status: str
    rate_snapshot: dict
    provisional_total_cents: int
    final_total_cents: Optional[int]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BehaviorIncident(TypedDict, total=False):
    id: str
    member_id: str
    incident_date: str
    category: str
    points: int
    description: Optional[str]
    adjudication_status: str
    suspension_status: str
    suspension_start_date: Optional[str]
    suspension_days: Optional[int]
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Staff(TypedDict, total=False):
    id: str
    site_id: str
    full_name: str
    position: str
    status: str
    background_check_expires_at: Optional[str]
    training_expires_at: Optional[str]
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class FunderReport(TypedDict, total=False):
    id: str
    site_id: str
    report_month: str
    funder_type: str
    status: str
    operating_days: int
    member_days_attended: int
    member_days_enrolled: int
    average_daily_attendance: float
    attendance_rate_enrollment_basis: float
    attendance_rate_capacity_basis: float
    headline_attendance_rate: float
    meals_served_total: int
    incidents_total: int
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
