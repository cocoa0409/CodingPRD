"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Traffic Enforcement PRD (Sections 2.4, 3.1-3.8).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD 2.1: six recognized roles, spelled exactly) ---
class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    PROGRAM_ADMIN = "ProgramAdmin"
    REVIEW_OFFICER = "ReviewOfficer"
    ADJUDICATOR = "Adjudicator"
    REGISTERED_OWNER = "RegisteredOwner"
    AUDITOR = "Auditor"


# --- Status enums ---
class CameraStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DECOMMISSIONED = "DECOMMISSIONED"


class CameraType(str, Enum):
    RED_LIGHT = "RED_LIGHT"
    SPEED = "SPEED"


class CalibrationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CitationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    REJECTED = "REJECTED"
    CITED = "CITED"
    CONTESTED = "CONTESTED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    ADJUDICATED_UPHELD = "ADJUDICATED_UPHELD"
    ADJUDICATED_DISMISSED = "ADJUDICATED_DISMISSED"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"
    VOID = "VOID"


class EscalationStage(str, Enum):
    NONE = "NONE"
    DELINQUENT = "DELINQUENT"


class ContestGround(str, Enum):
    NOT_THE_DRIVER = "NOT_THE_DRIVER"
    PLATE_MISREAD = "PLATE_MISREAD"
    SIGNAL_MALFUNCTION = "SIGNAL_MALFUNCTION"
    CALIBRATION_LAPSED = "CALIBRATION_LAPSED"
    EMERGENCY = "EMERGENCY"


class ContestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCHEDULED = "SCHEDULED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RULED = "RULED"
    ADJOURNED = "ADJOURNED"


class HearingOutcome(str, Enum):
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    REDUCED = "REDUCED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CHECK = "CHECK"
    CASH = "CASH"


class PaymentStatus(str, Enum):
    INITIATED = "INITIATED"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class VendorContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class NoticeType(str, Enum):
    INITIAL = "INITIAL"
    DELINQUENT = "DELINQUENT"


# --- Entity TypedDicts ---
# Full common fields (id, created_at, updated_at, version) — PRD 2.4.

class Program(TypedDict):
    id: str
    jurisdiction_name: str
    base_red_light_fine_cents: int
    base_speed_fine_cents: int
    admin_fee_cents: int
    late_fee_cents: int
    response_window_days: int
    repeat_offender_window_days: int
    repeat_offender_surcharge_pct: float
    created_at: str
    updated_at: str
    version: int


class Camera(TypedDict):
    id: str
    program_id: str
    intersection_code: str
    camera_type: str
    speed_limit_mph: Optional[int]
    status: str
    certified_until_clock: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegisteredOwner(TypedDict):
    id: str
    program_id: str
    plate_number: str
    full_name: str
    mailing_address: str
    portal_access_pin: str
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    program_id: str
    camera_id: str
    registered_owner_id: Optional[str]
    captured_plate_number: str
    event_at_utc: str
    measured_speed_mph: Optional[int]
    status: str
    notice_issued_at_utc: Optional[str]
    due_at_utc: Optional[str]
    escalation_stage: str
    assessed_amount_cents: Optional[int]
    adjudicated_amount_cents: Optional[int]
    amount_paid_cents: int
    review_officer_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contest(TypedDict):
    id: str
    citation_id: str
    submitted_by_owner_id: str
    ground: str
    statement: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    contest_id: str
    citation_id: str
    scheduled_at_utc: str
    adjudicator_ref: str
    outcome: Optional[str]
    reduced_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    citation_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorContract(TypedDict):
    id: str
    program_id: str
    vendor_name: str
    revenue_share_pct: float
    monthly_cap_cents: Optional[int]
    accrued_vendor_share_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit artifacts — carry ONLY id + created_at (PRD 2.4).
class CalibrationRecord(TypedDict):
    id: str
    camera_id: str
    performed_at_utc: str
    valid_until_utc: str
    technician_ref: str
    result: str
    notes: Optional[str]
    created_at: str


class NoticeRecord(TypedDict):
    id: str
    citation_id: str
    registered_owner_id: str
    notice_type: str
    issued_at_clock: str
    amount_owed_snapshot_cents: int
    created_at: str
