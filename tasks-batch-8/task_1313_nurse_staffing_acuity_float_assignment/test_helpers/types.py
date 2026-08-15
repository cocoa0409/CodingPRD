"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-4)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UnitType(str, Enum):
    ICU = "ICU"
    STEP_DOWN = "STEP_DOWN"
    MED_SURG = "MED_SURG"
    TELEMETRY = "TELEMETRY"
    EMERGENCY = "EMERGENCY"


class AcuityLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ShiftCode(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"


class EmploymentType(str, Enum):
    CORE = "CORE"
    FLOAT_POOL = "FLOAT_POOL"


class SnapshotStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    STAFFED = "STAFFED"
    LOCKED = "LOCKED"


class StaffingPosture(str, Enum):
    ADEQUATE = "ADEQUATE"
    UNDERSTAFFED = "UNDERSTAFFED"
    CRITICAL = "CRITICAL"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class AssignmentSource(str, Enum):
    DIRECT = "DIRECT"
    FLOAT = "FLOAT"
    INCENTIVE = "INCENTIVE"


class FloatRequestStatus(str, Enum):
    DEPLOYED = "DEPLOYED"
    UNFULFILLED = "UNFULFILLED"
    RELEASED = "RELEASED"


class FloatRequestOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO_ACUITY = "AUTO_ACUITY"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    CLAIMED = "CLAIMED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class OfferOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"


class SitterStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    RELEASED = "RELEASED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


class UserRole(str, Enum):
    NURSE_ADMIN = "NurseAdmin"
    CHARGE_NURSE = "ChargeNurse"
    STAFF_NURSE = "StaffNurse"
    FLOAT_COORDINATOR = "FloatCoordinator"
    REGULATOR = "Regulator"


# All entities carry the common system-managed fields of PRD section 2.4:
# id, created_at, updated_at, version.


class NursingUnit(TypedDict, total=False):
    id: str
    name: str
    unit_type: str
    bed_count: int
    incentive_budget_cents: int
    auto_incentive_multiplier: Optional[float]
    incentive_reserved_cents: int
    incentive_spent_cents: int
    created_at: str
    updated_at: str
    version: int


class Nurse(TypedDict, total=False):
    id: str
    full_name: str
    employment_type: str
    competencies: List[str]
    charge_qualified: bool
    base_hourly_rate_cents: int
    home_unit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffingMatrixRule(TypedDict, total=False):
    id: str
    unit_type: str
    acuity_level: str
    patients_per_nurse: int
    created_at: str
    updated_at: str
    version: int


class AcuitySnapshot(TypedDict, total=False):
    id: str
    unit_id: str
    shift_date: str
    shift_code: str
    census_low: int
    census_moderate: int
    census_high: int
    census_critical: int
    total_census: int
    required_nurses: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    unit_id: str
    shift_date: str
    shift_code: str
    start_at: str
    end_at: str
    governing_snapshot_id: str
    required_nurses: int
    counted_assignments: int
    sitter_diversion_count: int
    effective_assignments: int
    charge_covered: bool
    staffing_posture: str
    status: str
    posture_at_lock: Optional[str]
    counted_at_lock: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict, total=False):
    id: str
    shift_id: str
    nurse_id: str
    is_charge: bool
    source: str
    status: str
    scheduled_hours: float
    premium_multiplier: float
    flat_bonus_cents: int
    provisional_cost_cents: int
    projected_ot_hours: float
    actual_hours_worked: Optional[float]
    missed_breaks: Optional[int]
    final_cost_cents: Optional[int]
    final_ot_hours: Optional[float]
    created_at: str
    updated_at: str
    version: int


class FloatRequest(TypedDict, total=False):
    id: str
    shift_id: str
    origin: str
    status: str
    deployed_nurse_id: Optional[str]
    assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncentiveOffer(TypedDict, total=False):
    id: str
    shift_id: str
    premium_multiplier: float
    flat_bonus_cents: int
    origin: str
    premium_reserve_cents: int
    status: str
    claimed_nurse_id: Optional[str]
    claimed_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SitterRequest(TypedDict, total=False):
    id: str
    unit_id: str
    patient_ref: str
    start_at: str
    end_at: str
    status: str
    assigned_nurse_id: Optional[str]
    covering_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict, total=False):
    id: str
    report_date: str
    status: str
    return_reason: Optional[str]
    shifts_included_count: Optional[int]
    understaffed_shift_count: Optional[int]
    fill_rate_shift_weighted_pct: Optional[float]
    fill_rate_census_weighted_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class WeekLedger(TypedDict, total=False):
    week_start: str
    projected_hours: float
    completed_hours: float
