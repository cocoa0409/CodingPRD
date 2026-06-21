"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources described in the Calibration & Gage Management PRD §3 and
the common-resource rules in §2.4. Entities carry id/created_at/updated_at/version
except the singleton logical clock (ClockState), which carries only id/created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    TECHNICIAN = "Technician"
    QUALITY_ENGINEER = "QualityEngineer"
    METROLOGIST = "Metrologist"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class StandardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AccreditationBody(str, Enum):
    A2LA = "A2LA"
    NVLAP = "NVLAP"
    UKAS = "UKAS"
    NONE = "NONE"


class LifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class CalibrationStatus(str, Enum):
    UNCALIBRATED = "UNCALIBRATED"
    IN_TOLERANCE = "IN_TOLERANCE"
    OUT_OF_TOLERANCE = "OUT_OF_TOLERANCE"
    OVERDUE = "OVERDUE"


class Criticality(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class CalibrationEventStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CalibrationResult(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ImpactStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    DISPOSITIONED = "DISPOSITIONED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


class Disposition(str, Enum):
    USE_AS_IS = "USE_AS_IS"
    REWORK = "REWORK"
    RECALL = "RECALL"
    SCRAP = "SCRAP"


class AffectedProductStatus(str, Enum):
    FLAGGED = "FLAGGED"
    RECALLED = "RECALLED"
    CLEARED = "CLEARED"


class GageRRStudyStatus(str, Enum):
    DRAFT = "DRAFT"
    COLLECTING = "COLLECTING"
    ANALYZED = "ANALYZED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class Acceptability(str, Enum):
    ACCEPTABLE = "ACCEPTABLE"
    MARGINAL = "MARGINAL"
    UNACCEPTABLE = "UNACCEPTABLE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
class CalibrationStandard(TypedDict, total=False):
    id: str
    name: str
    nist_test_number: str
    parent_standard_id: Optional[str]
    nominal_value: float
    standard_unit: str
    uncertainty: float
    certified_through_epoch: int
    traceability_depth: int
    is_traceable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CalibrationVendor(TypedDict, total=False):
    id: str
    name: str
    accreditation_body: str
    accreditation_number: Optional[str]
    accredited_through_epoch: int
    is_accreditation_current: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Instrument(TypedDict, total=False):
    id: str
    asset_tag: str
    description: str
    nominal_value: float
    tolerance_plus: float
    tolerance_minus: float
    measurement_unit: str
    calibration_interval_epochs: int
    criticality: str
    last_calibration_epoch: Optional[int]
    next_due_epoch: Optional[int]
    lifecycle_status: str
    calibration_status: str
    open_oot_count: int
    created_at: str
    updated_at: str
    version: int


class CalibrationEvent(TypedDict, total=False):
    id: str
    instrument_id: str
    standard_id: str
    vendor_id: Optional[str]
    performed_by_user_id: str
    scheduled_epoch: int
    result: Optional[str]
    as_found_in_tolerance: Optional[bool]
    as_left_in_tolerance: Optional[bool]
    max_abs_deviation: Optional[float]
    tur: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class MeasurementPoint(TypedDict, total=False):
    id: str
    calibration_event_id: str
    point_label: str
    nominal: float
    tol_plus: float
    tol_minus: float
    as_found_value: float
    as_left_value: float
    as_found_pass: bool
    as_left_pass: bool
    created_at: str
    updated_at: str
    version: int


class CalibrationCertificate(TypedDict, total=False):
    id: str
    calibration_event_id: str
    vendor_id: str
    certificate_number: str
    issued_epoch: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OutOfToleranceImpact(TypedDict, total=False):
    id: str
    instrument_id: str
    triggering_event_id: str
    prior_calibration_epoch: Optional[int]
    suspect_window_start_epoch: int
    suspect_window_end_epoch: int
    dispositioned_by_user_id: Optional[str]
    disposition: Optional[str]
    affected_product_count: int
    recalled_product_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AffectedProduct(TypedDict, total=False):
    id: str
    impact_id: str
    product_serial: str
    measured_epoch: int
    in_suspect_window: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class GageRRStudy(TypedDict, total=False):
    id: str
    instrument_id: str
    operator_count: int
    part_count: int
    trial_count: int
    process_tolerance: float
    ev_repeatability: Optional[float]
    av_reproducibility: Optional[float]
    grr: Optional[float]
    pct_grr: Optional[float]
    acceptability: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GageRRTrial(TypedDict, total=False):
    id: str
    study_id: str
    operator_index: int
    part_index: int
    trial_index: int
    measured_value: float
    created_at: str
    updated_at: str
    version: int


# common_fields: false — the singleton logical clock carries ONLY id + created_at
class ClockState(TypedDict, total=False):
    id: str
    current_epoch: int
    created_at: str
