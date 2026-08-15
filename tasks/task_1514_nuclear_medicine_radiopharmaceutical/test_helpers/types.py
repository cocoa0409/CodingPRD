"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD resource descriptions. DoseAdministration and
RadiationSurvey are append-only records: they carry only ``id`` and
``created_at`` — neither ``updated_at`` nor ``version`` (PRD §2.11).
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    DEPARTMENT_ADMIN = "DepartmentAdmin"
    AUTHORIZED_USER = "AuthorizedUser"
    RADIOPHARMACIST = "Radiopharmacist"
    NUCLEAR_MEDICINE_TECHNOLOGIST = "NuclearMedicineTechnologist"
    RADIATION_SAFETY_OFFICER = "RadiationSafetyOfficer"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AuthorizedUserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RoomStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    CONTAMINATED = "CONTAMINATED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECEIVED = "RECEIVED"
    FAILED = "FAILED"


class DoseOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    DOSE_PREPARED = "DOSE_PREPARED"
    ON_HOLD = "ON_HOLD"
    ADMINISTERED = "ADMINISTERED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class HoldReason(str, Enum):
    LICENSE_SUSPENDED = "LICENSE_SUSPENDED"
    SPILL_CONTAMINATION = "SPILL_CONTAMINATION"


class DoseVialStatus(str, Enum):
    PREPARED = "PREPARED"
    CALIBRATED = "CALIBRATED"
    QUARANTINED = "QUARANTINED"
    DECAYED = "DECAYED"
    ADMINISTERED = "ADMINISTERED"
    DISPOSED = "DISPOSED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    AUTO_VOIDED = "AUTO_VOIDED"


class WasteContainerStatus(str, Enum):
    FILLING = "FILLING"
    SEALED = "SEALED"
    CLEARED = "CLEARED"


class SurveyResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SpillStatus(str, Enum):
    REPORTED = "REPORTED"
    CONTAINED = "CONTAINED"
    DECONTAMINATED = "DECONTAMINATED"
    CLEARED = "CLEARED"


class SpillClassification(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class UseType(str, Enum):
    DIAGNOSTIC = "DIAGNOSTIC"
    THERAPEUTIC = "THERAPEUTIC"


class Scope(str, Enum):
    DIAGNOSTIC = "DIAGNOSTIC"
    THERAPEUTIC = "THERAPEUTIC"
    BOTH = "BOTH"


class EvaluationVariant(str, Enum):
    ACTIVITY_BASED = "ACTIVITY_BASED"
    MEASURED_RATE_BASED = "MEASURED_RATE_BASED"


class IsotopeProduct(TypedDict, total=False):
    id: str
    name: str
    half_life_minutes: float
    decay_constant_per_minute: float
    spill_major_threshold_mbq: float
    release_activity_limit_mbq: float
    min_usable_activity_mbq: float
    created_at: str
    updated_at: str
    version: int


class RadiopharmacyLicense(TypedDict, total=False):
    id: str
    license_number: str
    max_possession_mbq: float
    isotope_conditions: list
    expires_at: str
    status: str
    current_possession_mbq: float
    created_at: str
    updated_at: str
    version: int


class AuthorizedUser(TypedDict, total=False):
    id: str
    full_name: str
    license_id: str
    scope: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    weight_kg: float
    date_of_birth: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImagingRoom(TypedDict, total=False):
    id: str
    name: str
    cleanup_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IsotopeDelivery(TypedDict, total=False):
    id: str
    isotope_product_id: str
    scheduled_arrival_at: str
    reference_activity_mbq: float
    reference_time_at: str
    received_at: Optional[str]
    measured_activity_mbq: Optional[float]
    failure_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DoseOrder(TypedDict, total=False):
    id: str
    patient_id: str
    isotope_product_id: str
    authorized_user_id: str
    use_type: str
    prescribed_activity_mbq: float
    administration_scheduled_at: str
    expires_at: str
    hold_reason: Optional[str]
    hold_previous_status: Optional[str]
    replaces_order_id: Optional[str]
    superseded_by_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DoseVial(TypedDict, total=False):
    id: str
    order_id: str
    delivery_id: str
    waste_container_id: Optional[str]
    prepared_at: str
    required_activity_mbq: float
    measured_activity_mbq: Optional[float]
    calibrated_at: Optional[str]
    calibrated_by_user_id: Optional[str]
    status: str
    disposed_at: Optional[str]
    residual_activity_mbq: Optional[float]
    decay_loss_mbq: Optional[float]
    created_at: str
    updated_at: str
    version: int


class DoseAdministration(TypedDict, total=False):
    """Append-only record: id + created_at only; no updated_at, no version."""

    id: str
    order_id: str
    vial_id: str
    administered_at: str
    administered_by_user_id: str
    assayed_activity_exact_mbq: float
    assayed_activity_tabular_mbq: float
    within_admin_window: bool
    created_at: str


class ProcedureAppointment(TypedDict, total=False):
    id: str
    order_id: str
    room_id: str
    start_at: str
    end_at: str
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WasteContainer(TypedDict, total=False):
    id: str
    isotope_product_id: str
    room_id: str
    status: str
    sealed_at: Optional[str]
    sealed_by_user_id: Optional[str]
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]
    intake_activity_mbq: float
    current_activity_mbq: float
    clearable_after_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RadiationSurvey(TypedDict, total=False):
    """Append-only record: id + created_at only; no updated_at, no version."""

    id: str
    room_id: str
    surveyed_at: str
    ambient_dose_rate_usv_h: float
    result: str
    performed_by_user_id: str
    created_at: str


class SpillIncident(TypedDict, total=False):
    id: str
    room_id: str
    isotope_product_id: str
    estimated_activity_mbq: float
    occurred_at: str
    classification: str
    reported_by_user_id: str
    status: str
    contained_at: Optional[str]
    decontaminated_at: Optional[str]
    cleared_at: Optional[str]
    cleared_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PatientReleaseInstruction(TypedDict, total=False):
    id: str
    administration_id: str
    evaluation_variant: str
    measured_dose_rate_at_1m_usv_h: Optional[float]
    releasable: bool
    status: str
    issued_by_user_id: str
    created_at: str
    updated_at: str
    version: int
