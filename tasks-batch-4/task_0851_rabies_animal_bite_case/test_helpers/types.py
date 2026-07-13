"""Domain types: entity TypedDicts, status enums, role enum.

All ten resource types are first-class entities carrying the common fields
id, created_at, updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    INTAKE_OFFICER = "IntakeOfficer"
    EPIDEMIOLOGIST = "Epidemiologist"
    VETERINARIAN = "Veterinarian"
    ANIMAL_CONTROL_OFFICER = "AnimalControlOfficer"
    OWNER = "Owner"
    HEALTH_DEPT_ADMIN = "HealthDeptAdmin"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DELINQUENT = "DELINQUENT"


class AnimalStatus(str, Enum):
    REPORTED = "REPORTED"
    AT_LARGE = "AT_LARGE"
    CAPTURED = "CAPTURED"
    UNDER_OBSERVATION = "UNDER_OBSERVATION"
    RELEASED = "RELEASED"
    DECEASED = "DECEASED"
    EUTHANIZED = "EUTHANIZED"


class AnimalDisposition(str, Enum):
    NONE = "NONE"
    RELEASED = "RELEASED"
    DECEASED = "DECEASED"
    EUTHANIZED = "EUTHANIZED"


class ControlStatus(str, Enum):
    NONE = "NONE"
    DISPATCH_REQUESTED = "DISPATCH_REQUESTED"
    CAPTURED = "CAPTURED"


class BiteCaseStatus(str, Enum):
    OPEN = "OPEN"
    OBSERVATION_PENDING = "OBSERVATION_PENDING"
    LAB_PENDING = "LAB_PENDING"
    CONFIRMED_RABID = "CONFIRMED_RABID"
    CLEARED = "CLEARED"
    CLOSED = "CLOSED"


class RiskLevel(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class PepIndication(str, Enum):
    NOT_INDICATED = "NOT_INDICATED"
    DEFER = "DEFER"
    INITIATE = "INITIATE"


class QuarantineOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    BREACHED = "BREACHED"
    CONVERTED_TO_SPECIMEN = "CONVERTED_TO_SPECIMEN"


class ObservationOutcome(str, Enum):
    PENDING = "PENDING"
    HEALTHY = "HEALTHY"
    SYMPTOMATIC = "SYMPTOMATIC"
    DECEASED = "DECEASED"


class SpecimenStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RESULTED = "RESULTED"
    REJECTED = "REJECTED"


class SpecimenResult(str, Enum):
    PENDING = "PENDING"
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    INDETERMINATE = "INDETERMINATE"


class PepStatus(str, Enum):
    NOT_INDICATED = "NOT_INDICATED"
    RECOMMENDED = "RECOMMENDED"
    INITIATED = "INITIATED"
    COMPLETED = "COMPLETED"
    DISCONTINUED = "DISCONTINUED"
    SUPERSEDED = "SUPERSEDED"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    CONTESTED = "CONTESTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    PAID = "PAID"


class AlertStatus(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    OUTBREAK = "OUTBREAK"


class Owner(TypedDict):
    id: str
    full_name: str
    phone: str
    address: Optional[str]
    license_number: Optional[str]
    outstanding_fines_cents: int
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class Animal(TypedDict):
    id: str
    owner_id: Optional[str]
    species: str
    animal_class: str
    identified: bool
    vaccination_status: str
    rabies_vaccine_expiry: Optional[str]
    status: str
    disposition: str
    control_status: str
    created_at: str
    updated_at: str
    version: int


class BiteCase(TypedDict):
    id: str
    case_number: str
    region_code: str
    incident_datetime: str
    exposure_type: str
    body_site: str
    wound_category: str
    victim_name: str
    victim_age: int
    victim_prior_vaccinated: bool
    animal_id: Optional[str]
    status: str
    risk_level: str
    pep_indication: str
    created_at: str
    updated_at: str
    version: int


class QuarantineFacility(TypedDict):
    id: str
    name: str
    facility_type: str
    capacity: int
    daily_boarding_cents: int
    current_occupancy: int
    created_at: str
    updated_at: str
    version: int


class QuarantineOrder(TypedDict):
    id: str
    case_id: str
    animal_id: str
    facility_id: Optional[str]
    order_type: str
    start_date: str
    scheduled_end_date: str
    actual_release_date: Optional[str]
    observation_outcome: str
    status: str
    boarding_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict):
    id: str
    case_id: str
    animal_id: str
    collected_datetime: str
    condition: str
    test_method: Optional[str]
    result: str
    reported_datetime: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PEPRecommendation(TypedDict):
    id: str
    case_id: str
    indication: str
    rig_indicated: bool
    projected_doses: int
    projected_cost_cents: int
    doses_administered: int
    final_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    owner_id: str
    case_id: str
    violations: List[str]
    base_fine_cents: int
    total_fine_cents: int
    issued_date: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveillanceRegion(TypedDict):
    id: str
    region_code: str
    positive_threshold: int
    confirmed_positive_count: int
    wildlife_exposure_count: int
    alert_status: str
    created_at: str
    updated_at: str
    version: int


class WildlifeExposureReport(TypedDict):
    id: str
    region_id: str
    species: str
    exposure_datetime: str
    exposure_type: str
    disposition: str
    created_at: str
    updated_at: str
    version: int
