"""Domain types: entity TypedDicts, status enums, role enum for the Backflow Prevention API."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    UTILITY_ADMIN = "UtilityAdmin"
    TESTER = "Tester"
    PREMISES_OWNER = "PremisesOwner"


# --- Status / enum value sets ---
class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    NON_COMPLIANT = "NON_COMPLIANT"
    SHUTOFF = "SHUTOFF"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class HazardClass(str, Enum):
    HIGH_HAZARD = "HIGH_HAZARD"
    LOW_HAZARD = "LOW_HAZARD"


class DeviceType(str, Enum):
    RP = "RP"
    DC = "DC"
    PVB = "PVB"
    DCDA = "DCDA"


class HazardRating(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class DeviceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NEEDS_REPAIR = "NEEDS_REPAIR"
    REPLACED = "REPLACED"
    REMOVED = "REMOVED"


class TesterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SurveyStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class NoticeReason(str, Enum):
    OVERDUE_TEST = "OVERDUE_TEST"
    FAILED_TEST = "FAILED_TEST"
    UNREPAIRED_DEVICE = "UNREPAIRED_DEVICE"


class NoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    RESCINDED = "RESCINDED"
    ENFORCED = "ENFORCED"


class OrderType(str, Enum):
    REPAIR = "REPAIR"
    REPLACEMENT = "REPLACEMENT"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReminderType(str, Enum):
    UPCOMING_DUE = "UPCOMING_DUE"
    OVERDUE = "OVERDUE"


# --- Entity TypedDicts (all entities carry id/created_at/updated_at/version) ---
class ServiceConnection(TypedDict):
    id: str
    account_number: str
    address: str
    owner_user_id: str
    hazard_class: str
    compliance_posture: str
    risk_tier: str
    water_service_active: bool
    protected_device_count: int
    overdue_device_count: int
    open_notice_count: int
    total_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class BackflowDevice(TypedDict):
    id: str
    service_connection_id: str
    serial_number: str
    device_type: str
    hazard_rating: str
    test_interval_months: int
    install_date: str
    last_pass_date: Optional[str]
    next_test_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Tester(TypedDict):
    id: str
    name: str
    certification_number: str
    cert_effective_date: str
    cert_expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TestAppointment(TypedDict):
    id: str
    device_id: str
    tester_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TestReport(TypedDict):
    id: str
    device_id: str
    tester_id: str
    test_date: str
    relief_valve_differential_psid: float
    check_valve_1_psid: float
    check_valve_2_psid: float
    result: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HazardSurvey(TypedDict):
    id: str
    service_connection_id: str
    premise_use_score: int
    chemical_exposure_score: int
    auxiliary_supply_score: int
    assessed_risk_tier: str
    effective_risk_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShutoffNotice(TypedDict):
    id: str
    service_connection_id: str
    reason: str
    issued_date: str
    grace_days: int
    enforcement_due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    device_id: str
    order_type: str
    description: str
    replacement_serial_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Reminder(TypedDict):
    id: str
    device_id: str
    reminder_type: str
    generated_date: str
    days_until_due: int
    created_at: str
    updated_at: str
    version: int
