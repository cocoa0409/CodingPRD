"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources described in the Mobile & House-Call Veterinary Service PRD.
ControlledMedLog is the one append-only resource: it carries only id and
created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, List, Optional


# --- Role enum ---------------------------------------------------------------

class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    CLINICIAN = "Clinician"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --- Status enums ------------------------------------------------------------

class ServiceAreaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClinicianRole(str, Enum):
    VET = "VET"
    TECH = "TECH"


class ClinicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_ROUTE = "ON_ROUTE"
    OFF_DUTY = "OFF_DUTY"


class RollingClinicStatus(str, Enum):
    IN_DEPOT = "IN_DEPOT"
    DEPLOYED = "DEPLOYED"
    MAINTENANCE = "MAINTENANCE"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    OTHER = "OTHER"


class VisitType(str, Enum):
    EXAM = "EXAM"
    VACCINE = "VACCINE"
    EUTHANASIA = "EUTHANASIA"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_VISIT = "IN_VISIT"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    COMPLETED = "COMPLETED"
    REFERRED = "REFERRED"
    CANCELLED = "CANCELLED"


class RouteDayPosture(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    RECONCILED = "RECONCILED"


class RouteStopStatus(str, Enum):
    PLANNED = "PLANNED"
    ARRIVED = "ARRIVED"
    SERVICED = "SERVICED"
    SKIPPED = "SKIPPED"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    INVOICED = "INVOICED"
    VOID = "VOID"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CASH = "CASH"
    CHECK = "CHECK"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class EntryType(str, Enum):
    DISPENSE = "DISPENSE"
    WASTE = "WASTE"


class SpecimenType(str, Enum):
    BLOOD = "BLOOD"
    URINE = "URINE"
    TISSUE = "TISSUE"


class SpecimenStatus(str, Enum):
    COLLECTED = "COLLECTED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


class WellnessPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class ServiceArea(TypedDict):
    id: str
    zip_code: str
    name: str
    travel_surcharge_cents: int
    euthanasia_allowed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict):
    id: str
    full_name: str
    clinician_role: str
    dea_number: Optional[str]
    dea_expires_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RollingClinic(TypedDict):
    id: str
    plate: str
    controlled_stock_ml: float
    controlled_reconciled_ml: float
    vaccine_stock_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    owner_name: str
    species: str
    weight_kg: float
    home_zip: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    patient_id: str
    service_area_id: str
    visit_type: str
    requested_start: str
    requested_end: str
    vaccine_doses: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteDay(TypedDict):
    id: str
    clinician_id: str
    rolling_clinic_id: str
    service_date: str
    stop_count: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_day_id: str
    appointment_id: str
    window_start: str
    window_end: str
    sequence: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    appointment_id: str
    line_items: list
    subtotal_cents: int
    travel_surcharge_cents: int
    estimate_total_cents: int
    invoice_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    estimate_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecimenPickup(TypedDict):
    id: str
    appointment_id: str
    specimen_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WellnessPlan(TypedDict):
    id: str
    patient_id: str
    interval_days: int
    anchor_date: str
    next_reminder_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    appointment_id: str
    hospital_name: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only entity (common_fields: false — only id + created_at) ---

class ControlledMedLog(TypedDict):
    id: str
    rolling_clinic_id: str
    appointment_id: str
    administering_vet_id: str
    witness_vet_id: Optional[str]
    entry_type: str
    amount_ml: float
    created_at: str
