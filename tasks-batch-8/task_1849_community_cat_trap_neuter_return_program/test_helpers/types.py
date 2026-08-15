"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    CARETAKER = "Caretaker"
    CLINIC_STAFF = "ClinicStaff"
    ANIMAL_CONTROL_OFFICER = "AnimalControlOfficer"
    FOSTER_VOLUNTEER = "FosterVolunteer"


class CaretakerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ColonyStatus(str, Enum):
    REGISTERED = "REGISTERED"
    DISSOLVED = "DISSOLVED"


class MonitoringStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WATCH = "WATCH"
    STABLE = "STABLE"


class CatStatus(str, Enum):
    AT_LARGE = "AT_LARGE"
    TRAPPED = "TRAPPED"
    AT_CLINIC = "AT_CLINIC"
    POST_SURGERY = "POST_SURGERY"
    RETURNED = "RETURNED"
    COLONY_STERILIZED = "COLONY_STERILIZED"
    IN_FOSTER = "IN_FOSTER"
    ADOPTION_PIPELINE = "ADOPTION_PIPELINE"
    ADOPTED = "ADOPTED"
    DECEASED = "DECEASED"


class Pathway(str, Enum):
    RETURN_TO_FIELD = "RETURN_TO_FIELD"
    ADOPTION = "ADOPTION"


class Sex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    UNKNOWN = "UNKNOWN"


class ClinicStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ClinicDayStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClinicSlotStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    USED = "USED"
    RELEASED = "RELEASED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    TRAPPED = "TRAPPED"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SurgeryOutcome(str, Enum):
    STERILIZED = "STERILIZED"
    ALREADY_STERILE = "ALREADY_STERILE"
    DIED_IN_SURGERY = "DIED_IN_SURGERY"


class VoucherStatus(str, Enum):
    ISSUED = "ISSUED"
    COMMITTED = "COMMITTED"
    REDEEMED = "REDEEMED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class FundingSource(str, Enum):
    MUNICIPAL_GRANT = "MUNICIPAL_GRANT"
    DONATION_FUND = "DONATION_FUND"


class ComplaintCategory(str, Enum):
    NOISE = "NOISE"
    ODOR = "ODOR"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    WILDLIFE_CONFLICT = "WILDLIFE_CONFLICT"
    OVERPOPULATION = "OVERPOPULATION"


class ComplaintSeverity(str, Enum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    IN_MEDIATION = "IN_MEDIATION"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class FosterHomeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class FosterPlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED_ADOPTION = "ENDED_ADOPTION"
    ENDED_RETURNED = "ENDED_RETURNED"


class Trend(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    DECLINING = "DECLINING"
    GROWING = "GROWING"
    FLAT = "FLAT"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).

class Caretaker(TypedDict, total=False):
    id: str
    full_name: str
    phone: str
    email: str
    certified_tnr: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Colony(TypedDict, total=False):
    id: str
    name: str
    address: str
    caretaker_id: str
    registered_on: str
    estimated_population: int
    monitoring_status: str
    sterilized_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Cat(TypedDict, total=False):
    id: str
    colony_id: str
    intake_tag: str
    sex: str
    approximate_age_months: int
    is_kitten: bool
    ear_tipped: bool
    vaccinated_rabies: bool
    status: str
    pathway: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartnerClinic(TypedDict, total=False):
    id: str
    name: str
    voucher_reimbursement_cents: int
    accepts_vouchers: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ClinicDay(TypedDict, total=False):
    id: str
    clinic_id: str
    service_date: str
    base_capacity: int
    surge_capacity: int
    booked_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClinicSlot(TypedDict, total=False):
    id: str
    clinic_day_id: str
    slot_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrappingAppointment(TypedDict, total=False):
    id: str
    cat_id: str
    clinic_slot_id: str
    trap_date: str
    voucher_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SurgeryRecord(TypedDict, total=False):
    id: str
    appointment_id: str
    surgeon_initials: str
    ear_tipped: bool
    rabies_vaccinated: bool
    complications: bool
    outcome: str
    performed_at: str
    created_at: str
    updated_at: str
    version: int


class Voucher(TypedDict, total=False):
    id: str
    caretaker_id: str
    face_value_cents: int
    funding_source: str
    issued_month: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    colony_id: str
    complainant_name: str
    category: str
    filed_at: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FosterHome(TypedDict, total=False):
    id: str
    volunteer_name: str
    capacity_kittens: int
    current_kittens: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FosterPlacement(TypedDict, total=False):
    id: str
    cat_id: str
    foster_home_id: str
    placed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only field observation: carries ONLY id + created_at (PRD §2.5).
class PopulationSurvey(TypedDict, total=False):
    id: str
    colony_id: str
    surveyed_on: str
    observed_count: int
    eartipped_count: int
    notes: str
    created_at: str
