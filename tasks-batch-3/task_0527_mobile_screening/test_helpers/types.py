"""Domain types: entity TypedDicts, status enums, role enum for the Mobile Screening API."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (§2.1) ---
class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    CLINICAL_STAFF = "ClinicalStaff"
    BILLING_CLERK = "BillingClerk"
    PATIENT_NAVIGATOR = "PatientNavigator"
    SPONSOR_VIEWER = "SponsorViewer"


# --- Modality enum ---
class Modality(str, Enum):
    MAMMOGRAPHY = "MAMMOGRAPHY"
    BLOOD_PANEL = "BLOOD_PANEL"
    BONE_DENSITY = "BONE_DENSITY"
    SKIN = "SKIN"


# --- Status enums ---
class MobileUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RETIRED = "RETIRED"


class StaffStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class StaffRoleType(str, Enum):
    TECHNOLOGIST = "TECHNOLOGIST"
    RADIOLOGIST = "RADIOLOGIST"
    NAVIGATOR = "NAVIGATOR"
    PHLEBOTOMIST = "PHLEBOTOMIST"


class SponsorType(str, Enum):
    EMPLOYER = "EMPLOYER"
    GRANT = "GRANT"


class ScreeningEventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PayType(str, Enum):
    INSURANCE = "INSURANCE"
    SELF_PAY = "SELF_PAY"
    GRANT = "GRANT"


class ParticipantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    SCREENED = "SCREENED"
    RESULT_READY = "RESULT_READY"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class AppointmentResult(str, Enum):
    NORMAL = "NORMAL"
    ABNORMAL = "ABNORMAL"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    CONTACTED = "CONTACTED"
    SCHEDULED_FOLLOWUP = "SCHEDULED_FOLLOWUP"
    RESOLVED = "RESOLVED"
    LOST_TO_FOLLOWUP = "LOST_TO_FOLLOWUP"


class ReferralPriority(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


class ChargeStatus(str, Enum):
    DRAFT = "DRAFT"
    ADJUDICATED = "ADJUDICATED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class ReminderStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    CANCELLED = "CANCELLED"


class ReminderChannel(str, Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"


# --- Entity TypedDicts (all carry common fields: id, created_at, updated_at, version) ---

class MobileUnit(TypedDict):
    id: str
    name: str
    modality: str
    daily_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    full_name: str
    role_type: str
    modality: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Sponsor(TypedDict):
    id: str
    name: str
    sponsor_type: str
    viewer_user_id: str
    created_at: str
    updated_at: str
    version: int


class Grant(TypedDict):
    id: str
    sponsor_id: str
    name: str
    total_budget_cents: int
    committed_cents: int
    settled_cents: int
    remaining_cents: int
    is_depleted: bool
    created_at: str
    updated_at: str
    version: int


class ScreeningEvent(TypedDict):
    id: str
    sponsor_id: str
    mobile_unit_id: str
    modality: str
    site_label: str
    event_date: str
    window_start_min: int
    window_end_min: int
    booked_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    pay_type: str
    insurance_member_id: Optional[str]
    grant_id: Optional[str]
    no_show_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    event_id: str
    participant_id: str
    slot_start_min: int
    slot_duration_min: int
    consent_signed: bool
    consent_signed_at: Optional[str]
    result: Optional[str]
    result_delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    appointment_id: str
    participant_id: str
    priority: str
    due_by_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    appointment_id: str
    participant_id: str
    grant_id: Optional[str]
    list_price_cents: int
    pay_type: str
    insurance_allowed_cents: Optional[int]
    grant_covered_cents: int
    provisional_patient_responsibility_cents: int
    final_patient_responsibility_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Reminder(TypedDict):
    id: str
    appointment_id: str
    send_at_min: int
    channel: str
    status: str
    created_at: str
    updated_at: str
    version: int
