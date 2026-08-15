"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    UNIT_ADMIN = "UnitAdmin"
    SCHEDULING_COORDINATOR = "SchedulingCoordinator"
    ENDOSCOPIST = "Endoscopist"
    ANESTHESIA_PROVIDER = "AnesthesiaProvider"
    REPROCESSING_TECHNICIAN = "ReprocessingTechnician"
    INFECTION_CONTROL_NURSE = "InfectionControlNurse"
    PATHOLOGY_STAFF = "PathologyStaff"
    QUALITY_OFFICER = "QualityOfficer"


class Specialty(str, Enum):
    GASTROENTEROLOGY = "GASTROENTEROLOGY"
    COLORECTAL_SURGERY = "COLORECTAL_SURGERY"


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PrepProtocol(str, Enum):
    NONE = "NONE"
    CLEAR_LIQUIDS = "CLEAR_LIQUIDS"
    SPLIT_DOSE = "SPLIT_DOSE"


class RoomClass(str, Enum):
    STANDARD = "STANDARD"
    ERCP_CAPABLE = "ERCP_CAPABLE"


class RoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ScopeType(str, Enum):
    COLONOSCOPE = "COLONOSCOPE"
    GASTROSCOPE = "GASTROSCOPE"
    SIGMOIDOSCOPE = "SIGMOIDOSCOPE"


class ScopeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    AWAITING_REPROCESS = "AWAITING_REPROCESS"
    REPROCESSING = "REPROCESSING"
    QUARANTINED = "QUARANTINED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class BookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"
    ABORTED_PREP_INADEQUATE = "ABORTED_PREP_INADEQUATE"


class PrepStatus(str, Enum):
    PREP_PENDING = "PREP_PENDING"
    PREP_CONFIRMED = "PREP_CONFIRMED"
    PREP_ADEQUATE = "PREP_ADEQUATE"
    PREP_INADEQUATE = "PREP_INADEQUATE"


class Indication(str, Enum):
    SCREENING = "SCREENING"
    SURVEILLANCE = "SURVEILLANCE"
    DIAGNOSTIC = "DIAGNOSTIC"


class AnesthesiaType(str, Enum):
    NONE = "NONE"
    MAC = "MAC"
    GENERAL = "GENERAL"


class ScopeUsageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class CycleStatus(str, Enum):
    INITIATED = "INITIATED"
    PRECLEANED = "PRECLEANED"
    CLEANED = "CLEANED"
    DISINFECTED = "DISINFECTED"
    DRIED = "DRIED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class CycleStep(str, Enum):
    PRECLEANED = "PRECLEANED"
    CLEANED = "CLEANED"
    DISINFECTED = "DISINFECTED"
    DRIED = "DRIED"
    COMPLETE = "COMPLETE"


class CultureStatus(str, Enum):
    PENDING = "PENDING"
    RESULTED = "RESULTED"


class CultureResult(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class QuarantineCaseStatus(str, Enum):
    OPEN = "OPEN"
    RECULTURING = "RECULTURING"
    RELEASED = "RELEASED"
    SCOPE_RETIRED = "SCOPE_RETIRED"


class SpecimenType(str, Enum):
    POLYP = "POLYP"
    BIOPSY = "BIOPSY"
    OTHER = "OTHER"


class SpecimenStatus(str, Enum):
    COLLECTED = "COLLECTED"
    LABELED = "LABELED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED_BY_LAB = "RECEIVED_BY_LAB"
    RESULTED = "RESULTED"
    REJECTED_BY_LAB = "REJECTED_BY_LAB"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MetricVariant(str, Enum):
    STRICT = "STRICT"
    EXPANDED = "EXPANDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Primary resources carry id/created_at/updated_at/version
# (PRD §2.5); QualityMetricReport is the sole exception (id + created_at only).
# ---------------------------------------------------------------------------

class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    contact_phone: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    full_name: str
    specialty: str
    credential_status: str
    created_at: str
    updated_at: str
    version: int


class ProcedureType(TypedDict, total=False):
    id: str
    code: str
    display_name: str
    base_duration_minutes: int
    prep_protocol: str
    colonoscopy_family: bool
    adr_relevant: bool
    required_scope_type: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    id: str
    name: str
    room_class: str
    supports_anesthesia: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AnesthesiaProvider(TypedDict, total=False):
    id: str
    full_name: str
    credential_status: str
    scheduled_minutes: int
    created_at: str
    updated_at: str
    version: int


class Scope(TypedDict, total=False):
    id: str
    serial_number: str
    scope_type: str
    status: str
    storage_expires_at: Optional[str]
    awaiting_reprocess_since: Optional[str]
    use_count: int
    is_storage_current: bool
    created_at: str
    updated_at: str
    version: int


class ProcedureBooking(TypedDict, total=False):
    id: str
    patient_id: str
    provider_id: str
    procedure_type_id: str
    room_id: str
    indication: str
    anesthesia_type: str
    notes: Optional[str]
    scheduled_start: str
    procedure_minutes: int
    scheduled_end: str
    room_block_end: str
    status: str
    prep_status: str
    bbps_left: Optional[int]
    bbps_right: Optional[int]
    bbps_transverse: Optional[int]
    actual_start: Optional[str]
    actual_end: Optional[str]
    actual_duration_minutes: Optional[int]
    cecum_intubated: Optional[bool]
    withdrawal_time_seconds: Optional[int]
    adenomas_detected: Optional[int]
    notification_flag: bool
    rescheduled_from_id: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScopeUsage(TypedDict, total=False):
    id: str
    booking_id: str
    scope_id: str
    patient_id: str
    used_at: str
    status: str
    void_reason: Optional[str]
    exposure_flagged: bool
    created_at: str
    updated_at: str
    version: int


class ReprocessingCycle(TypedDict, total=False):
    id: str
    scope_id: str
    booking_id: Optional[str]
    technician_id: str
    status: str
    is_reculture: bool
    requires_extended_soak: bool
    hld_solution_lot: Optional[str]
    hld_concentration_ppm: Optional[float]
    initiated_at: str
    precleaned_at: Optional[str]
    cleaned_at: Optional[str]
    disinfected_at: Optional[str]
    dried_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScopeCultureTest(TypedDict, total=False):
    id: str
    scope_id: str
    reprocessing_cycle_id: str
    recorded_by: str
    sampled_at: str
    status: str
    result: Optional[str]
    organism: Optional[str]
    cfu_count: Optional[int]
    resulted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuarantineCase(TypedDict, total=False):
    id: str
    scope_id: str
    triggering_culture_id: str
    status: str
    opened_at: str
    exposure_window_start: Optional[str]
    exposure_window_end: Optional[str]
    reculture_cycle_id: Optional[str]
    released_by: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict, total=False):
    id: str
    booking_id: str
    patient_id: str
    specimen_type: str
    container_count: int
    status: str
    collected_at: str
    labeled_at: Optional[str]
    labeled_by: Optional[str]
    handed_off_at: Optional[str]
    handed_off_by: Optional[str]
    courier_id: Optional[str]
    received_at: Optional[str]
    received_by: Optional[str]
    reject_reason: Optional[str]
    adenoma_confirmed: Optional[bool]
    resulted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityMetricReport(TypedDict, total=False):
    """Immutable snapshot (PRD §2.5): only id + created_at are guaranteed."""
    id: str
    provider_id: str
    period_start: str
    period_end: str
    metric_variant: str
    adenoma_detection_rate: Optional[float]
    adr_numerator: int
    adr_denominator: int
    withdrawal_time_avg_seconds: Optional[float]
    withdrawal_sample_size: int
    cecal_intubation_rate: Optional[float]
    prep_adequacy_rate: Optional[float]
    created_at: str


class AnesthesiaAssignment(TypedDict, total=False):
    id: str
    booking_id: str
    anesthesia_provider_id: str
    minutes: int
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
