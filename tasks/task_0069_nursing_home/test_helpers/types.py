"""Domain types for the Nursing Home API.

TypedDicts mirror the entity field surface described in the PRD §1 (introduction
+ structure) and §3 (workflows). Status / role enums encode the only legal
values the API will accept or emit. Entities whose stored history is
append-only (CareTaskExecution, MedicationAdministration, MedicationErrorReport,
AuditLog, ExternalEvent, WaitlistEntry) carry only ``id`` and ``created_at`` —
the PRD explicitly excludes ``updated_at`` and ``version`` for these rows.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, List, Optional, TypedDict


# ===========================================================================
# Roles (PRD §2.1)
# ===========================================================================
class UserRole(str, Enum):
    ADMIN = "Admin"
    SUPERVISOR = "Supervisor"
    PHYSICIAN = "Physician"
    NURSE = "Nurse"
    CAREGIVER = "Caregiver"
    FAMILY = "Family"
    FINANCE = "Finance"
    SYSTEM_SYNC = "SystemSync"


# ===========================================================================
# Status enums
# ===========================================================================
class ElderStatus(str, Enum):
    PENDING_ADMISSION = "PENDING_ADMISSION"
    ADMITTED = "ADMITTED"
    ON_LEAVE = "ON_LEAVE"
    DISCHARGED = "DISCHARGED"


class BedStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    MAINTENANCE = "MAINTENANCE"


class BedType(str, Enum):
    SINGLE = "SINGLE"
    DOUBLE = "DOUBLE"
    MULTI = "MULTI"
    INTENSIVE_CARE = "INTENSIVE_CARE"


class RoomType(str, Enum):
    STANDARD = "STANDARD"
    INTENSIVE_CARE = "INTENSIVE_CARE"


class WaitlistStatus(str, Enum):
    QUEUED = "QUEUED"
    OFFERED = "OFFERED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class CareAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CareLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    INTENSIVE = "INTENSIVE"


class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class TaskType(str, Enum):
    BATHING = "BATHING"
    FEEDING = "FEEDING"
    TURNING = "TURNING"
    MEDICATION = "MEDICATION"
    VITALS = "VITALS"


class TaskOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"
    OMITTED = "OMITTED"


class PrescriptionStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISCONTINUED = "DISCONTINUED"


class MedicationOutcome(str, Enum):
    ADMINISTERED = "ADMINISTERED"
    REFUSED = "REFUSED"
    OMITTED = "OMITTED"
    ERROR = "ERROR"


class MedicationErrorType(str, Enum):
    WRONG_DRUG = "WRONG_DRUG"
    WRONG_DOSE = "WRONG_DOSE"
    WRONG_TIME = "WRONG_TIME"
    INTERACTION = "INTERACTION"
    OTHER = "OTHER"


class MedicationErrorSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class VisitorRelation(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    SIBLING = "SIBLING"
    OTHER_FAMILY = "OTHER_FAMILY"
    FRIEND = "FRIEND"
    OTHER = "OTHER"


class VisitReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DENIED = "DENIED"


class EpidemicMode(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    LOCKDOWN = "LOCKDOWN"


class BillingMode(str, Enum):
    PACKAGE = "PACKAGE"
    A_LA_CARTE = "A_LA_CARTE"


class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    ADJUSTED = "ADJUSTED"


class LineItemCategory(str, Enum):
    BED = "BED"
    CARE = "CARE"
    MEAL = "MEAL"
    MEDICAL = "MEDICAL"


class ExternalEventSource(str, Enum):
    PAYMENT = "PAYMENT"
    IM = "IM"
    HOSPITAL = "HOSPITAL"
    GOVT_SUBSIDY = "GOVT_SUBSIDY"


class ExternalEventResultStatus(str, Enum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    REJECTED = "REJECTED"


class AuditEntityType(str, Enum):
    CARE_PLAN = "CarePlan"
    PRESCRIPTION = "Prescription"
    MEDICATION_ADMINISTRATION = "MedicationAdministration"
    CARE_ASSESSMENT = "CareAssessment"


# ===========================================================================
# Entity TypedDicts
# ===========================================================================
class EmergencyContact(TypedDict, total=False):
    name: str
    relation: str
    phone: str


class AdvanceDirective(TypedDict, total=False):
    dnr: bool
    dni: bool
    organ_donation: bool
    signed_at: Optional[str]


class Elder(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    gender: str
    id_card_number: str
    medical_history: List[Any]
    allergies: List[str]
    dietary_requirements: List[str]
    emergency_contacts: List[Any]
    advance_directive: AdvanceDirective
    status: str
    admission_history: List[Any]
    current_bed_id: Optional[str]
    current_care_level: Optional[str]
    deposit_balance_cents: int
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    id: str
    room_number: str
    floor: int
    room_type: str
    created_at: str
    updated_at: str
    version: int


class Bed(TypedDict, total=False):
    id: str
    room_id: str
    bed_code: str
    bed_type: str
    monthly_bed_fee_cents: int
    status: str
    current_elder_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# WaitlistEntry: PRD §2.4 — common_fields false, only id + created_at
class WaitlistEntry(TypedDict, total=False):
    id: str
    elder_id: str
    requested_bed_type: str
    priority_score: int
    queued_at: str
    status: str
    offered_bed_id: Optional[str]
    created_at: str


class CareAssessment(TypedDict, total=False):
    id: str
    elder_id: str
    adl_score: int
    cognitive_score: int
    medical_condition_score: int
    composite_score: float
    classification: Optional[str]
    status: str
    assessor_id: str
    approver_id: Optional[str]
    effective_from: Optional[str]
    due_for_reassessment_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DailyTask(TypedDict, total=False):
    task_type: str
    frequency_per_day: int
    notes: str


class CarePlan(TypedDict, total=False):
    id: str
    elder_id: str
    based_on_assessment_id: str
    care_level_snapshot: Optional[str]
    status: str
    daily_tasks: List[DailyTask]
    review_cycle_days: Optional[int]
    next_review_due_at: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# CareTaskExecution: PRD §2.4 — common_fields false
class CareTaskExecution(TypedDict, total=False):
    id: str
    care_plan_id: str
    task_type: str
    scheduled_for: str
    executed_at: str
    caregiver_id: str
    outcome: str
    notes: Optional[str]
    created_at: str


class Prescription(TypedDict, total=False):
    id: str
    elder_id: str
    drug_code: str
    drug_name: str
    is_controlled_substance: bool
    contraindicated_allergens: List[str]
    interacts_with_drug_codes: List[str]
    dose_mg: float
    frequency_per_day: int
    prescriber_id: str
    status: str
    starts_on: str
    ends_on: str
    created_at: str
    updated_at: str
    version: int


# MedicationAdministration: PRD §2.4 — common_fields false
class MedicationAdministration(TypedDict, total=False):
    id: str
    prescription_id: str
    scheduled_slot_at: str
    administered_at: str
    nurse_id: str
    witness_id: Optional[str]
    outcome: str
    error_report_id: Optional[str]
    created_at: str


# MedicationErrorReport: PRD §2.4 — common_fields false
class MedicationErrorReport(TypedDict, total=False):
    id: str
    administration_id: Optional[str]
    prescription_id: Optional[str]
    elder_id: str
    error_type: str
    severity: str
    description: str
    created_at: str


class HealthScreening(TypedDict, total=False):
    temperature_c: float
    symptoms: List[str]
    recent_exposure: bool


class VisitReservation(TypedDict, total=False):
    id: str
    elder_id: str
    visitor_name: str
    visitor_id_number: str
    visitor_relation: str
    slot_start_at: str
    slot_end_at: str
    status: str
    health_screening: Optional[HealthScreening]
    epidemic_mode_at_reservation: str
    check_in_at: Optional[str]
    check_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillLineItem(TypedDict, total=False):
    category: str
    description: str
    amount_cents: int


class Bill(TypedDict, total=False):
    id: str
    elder_id: str
    cycle_start_date: str
    cycle_end_date: str
    billing_mode: str
    line_items: List[BillLineItem]
    subtotal_cents: int
    government_subsidy_cents: int
    insurance_offset_cents: int
    deposit_applied_cents: int
    amount_due_cents: int
    status: str
    finalized_at: Optional[str]
    paid_at: Optional[str]
    external_payment_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EpidemicConfig(TypedDict, total=False):
    id: str
    mode: str
    max_temperature_c: float
    max_visitors_per_day: int
    created_at: str
    updated_at: str
    version: int


# AuditLog: PRD §2.4 — common_fields false
class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    entity_type: str
    entity_id: str
    action: str
    previous_state: Optional[str]
    new_state: Optional[str]
    occurred_at: str
    created_at: str


# ExternalEvent: PRD §2.4 — common_fields false
class ExternalEvent(TypedDict, total=False):
    id: str
    source: str
    idempotency_key: str
    event_type: str
    payload: Any
    applied_at: str
    result_status: str
    created_at: str


__all__ = [
    "UserRole",
    "ElderStatus", "BedStatus", "BedType", "RoomType",
    "WaitlistStatus", "CareAssessmentStatus", "CareLevel",
    "CarePlanStatus", "TaskType", "TaskOutcome",
    "PrescriptionStatus", "MedicationOutcome",
    "MedicationErrorType", "MedicationErrorSeverity",
    "VisitorRelation", "VisitReservationStatus", "EpidemicMode",
    "BillingMode", "BillStatus", "LineItemCategory",
    "ExternalEventSource", "ExternalEventResultStatus",
    "AuditEntityType",
    "EmergencyContact", "AdvanceDirective",
    "Elder", "Room", "Bed", "WaitlistEntry",
    "CareAssessment", "DailyTask", "CarePlan", "CareTaskExecution",
    "Prescription", "MedicationAdministration", "MedicationErrorReport",
    "HealthScreening", "VisitReservation", "BillLineItem", "Bill",
    "EpidemicConfig", "AuditLog", "ExternalEvent",
]
