"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status / enum values ---

class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    OOS_ORDERED = "OOS_ORDERED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OOS = "OOS"


class HosStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    VIOLATION = "VIOLATION"


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class BayStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_ORDER = "OUT_OF_ORDER"


class ScreeningStatus(str, Enum):
    SCREENED = "SCREENED"
    CLEARED = "CLEARED"
    REFERRED = "REFERRED"
    INSPECTED = "INSPECTED"


class ScreeningDecision(str, Enum):
    BYPASS = "BYPASS"
    PULL_IN = "PULL_IN"


class ReferralReason(str, Enum):
    NONE = "NONE"
    PRISM_TARGET = "PRISM_TARGET"
    OVERWEIGHT = "OVERWEIGHT"
    OVERSIZE = "OVERSIZE"
    CREDENTIAL = "CREDENTIAL"
    HAZMAT = "HAZMAT"


class InspectionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    CLEARED = "CLEARED"
    OOS_ISSUED = "OOS_ISSUED"
    REINSPECTION = "REINSPECTION"
    CANCELLED = "CANCELLED"


class InspectionLevel(str, Enum):
    LEVEL_I = "LEVEL_I"
    LEVEL_II = "LEVEL_II"
    LEVEL_III = "LEVEL_III"


class InspectionResult(str, Enum):
    NONE = "NONE"
    CLEAR = "CLEAR"
    OOS = "OOS"


class ViolationCategory(str, Enum):
    VEHICLE = "VEHICLE"
    DRIVER = "DRIVER"
    HAZMAT = "HAZMAT"
    HOS = "HOS"
    CREDENTIAL = "CREDENTIAL"
    WEIGHT = "WEIGHT"


class CitationKind(str, Enum):
    OVERWEIGHT = "OVERWEIGHT"
    CREDENTIAL = "CREDENTIAL"
    HAZMAT = "HAZMAT"
    HOS = "HOS"
    EQUIPMENT = "EQUIPMENT"


class CitationStatus(str, Enum):
    ASSESSED = "ASSESSED"
    CONTESTED = "CONTESTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    SETTLED = "SETTLED"


class DutyEntryType(str, Enum):
    DRIVING = "DRIVING"
    ON_DUTY = "ON_DUTY"
    OFF_DUTY = "OFF_DUTY"
    SLEEPER = "SLEEPER"


class SnapshotMethod(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"


class UserRole(str, Enum):
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    SCREENER = "Screener"
    INSPECTOR = "Inspector"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    CARRIER_REP = "CarrierRep"


# --- Entity TypedDicts (all entities carry the full common-field set) ---

class Carrier(TypedDict):
    id: str
    usdot_number: str
    legal_name: str
    irp_status: str
    ifta_status: str
    ucr_status: str
    oos_points: int
    unpaid_fines_cents: int
    iss_score: int
    certified_iss_score: int
    prism_flagged: bool
    registration_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    carrier_id: str
    cdl_number: str
    full_name: str
    hos_status: str
    driving_minutes_window: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WeighStation(TypedDict):
    id: str
    name: str
    state_code: str
    gross_weight_limit_lbs: int
    single_axle_limit_lbs: int
    iss_bypass_threshold: int
    created_at: str
    updated_at: str
    version: int


class InspectionBay(TypedDict):
    id: str
    station_id: str
    label: str
    reserved_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Screening(TypedDict):
    id: str
    station_id: str
    carrier_id: str
    driver_id: str
    vehicle_plate: str
    axle_count: int
    gross_weight_lbs: int
    heaviest_axle_lbs: int
    hazmat_placarded: bool
    oversize: bool
    overweight: bool
    credentials_valid: bool
    decision: str
    referral_reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    screening_id: str
    driver_id: str
    bay_id: str
    level: str
    scheduled_start: str
    scheduled_end: str
    result: str
    oos_flag: bool
    reinspection_count: int
    oos_points_applied: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    inspection_id: str
    code: str
    category: str
    severity_weight: int
    oos: bool
    description: str
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    inspection_id: str
    carrier_id: str
    kind: str
    assessed_fine_cents: int
    final_fine_cents: int
    certified_gross_lbs: int
    certified_axle_lbs: int
    contest_reason: str
    issued_by_user_id: str
    adjudicated_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DutyLogEntry(TypedDict):
    id: str
    driver_id: str
    entry_type: str
    start_utc: str
    end_utc: str
    created_at: str
    updated_at: str
    version: int


class ScoreSnapshot(TypedDict):
    id: str
    carrier_id: str
    method: str
    iss_score: int
    inspection_count: int
    is_current: bool
    computed_at: str
    created_at: str
    updated_at: str
    version: int
