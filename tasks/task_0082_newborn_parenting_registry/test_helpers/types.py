"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources and lifecycle states defined in the PRD (Newborn / Parenting
Registry API). Lifecycle-bearing resources expose their position through `status`
(or `clinical_status` for the newborn); the audit record is immutable and carries
only `id` and `created_at`.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    INTAKE_CLERK = "IntakeClerk"
    ATTENDING_NURSE = "AttendingNurse"
    NEONATOLOGIST = "Neonatologist"
    BENEFITS_COORDINATOR = "BenefitsCoordinator"
    VITAL_RECORDS_OFFICER = "VitalRecordsOfficer"
    REGISTRY_SUPERVISOR = "RegistrySupervisor"


# --- Status enums ---
class PreRegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADMITTED = "ADMITTED"
    BIRTH_RECORDED = "BIRTH_RECORDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ClinicalStatus(str, Enum):
    BORN = "BORN"
    ROOMING_IN = "ROOMING_IN"
    NICU_ADMITTED = "NICU_ADMITTED"
    STEP_DOWN = "STEP_DOWN"
    DISCHARGE_READY = "DISCHARGE_READY"
    DISCHARGED = "DISCHARGED"


class CareLocation(str, Enum):
    WELL_BABY_NURSERY = "WELL_BABY_NURSERY"
    MOTHER_ROOM = "MOTHER_ROOM"
    NICU = "NICU"
    STEP_DOWN_UNIT = "STEP_DOWN_UNIT"
    RELEASED = "RELEASED"


class PlanType(str, Enum):
    EMPLOYER_GROUP = "EMPLOYER_GROUP"
    MARKETPLACE = "MARKETPLACE"
    MEDICAID = "MEDICAID"


class LactationConsultStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    FEEDING_AT_RISK = "FEEDING_AT_RISK"
    CANCELLED = "CANCELLED"


class AcuityLevel(str, Enum):
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    LEVEL_4 = "LEVEL_4"


class BedOccupancyStatus(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class NicuStayStatus(str, Enum):
    PENDING_BED = "PENDING_BED"
    ACTIVE = "ACTIVE"
    STEPPED_DOWN = "STEPPED_DOWN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class DischargeBagStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSEMBLED = "ASSEMBLED"
    ISSUED = "ISSUED"
    RECALLED = "RECALLED"


class LineItemCategory(str, Enum):
    FORMULA = "FORMULA"
    DIAPERS = "DIAPERS"
    EDUCATION = "EDUCATION"
    CARSEAT_VOUCHER = "CARSEAT_VOUCHER"
    MEDICATION = "MEDICATION"


class FollowUpTaskType(str, Enum):
    WEIGHT_CHECK = "WEIGHT_CHECK"
    JAUNDICE_CHECK = "JAUNDICE_CHECK"
    FEEDING_CHECK = "FEEDING_CHECK"
    SAFETY_CALL = "SAFETY_CALL"


class FollowUpTaskStatus(str, Enum):
    OPEN = "OPEN"
    ATTEMPTED = "ATTEMPTED"
    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class DependentEnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ENROLLED = "ENROLLED"
    SEP_EXPIRED = "SEP_EXPIRED"
    DENIED = "DENIED"
    TERMINATED = "TERMINATED"


class FilingType(str, Enum):
    BIRTH_CERTIFICATE = "BIRTH_CERTIFICATE"
    SSN_APPLICATION = "SSN_APPLICATION"


class GovernmentFilingStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    LATE_FLAGGED = "LATE_FLAGGED"
    CANCELLED = "CANCELLED"


class AuditEventType(str, Enum):
    BIRTH_RECORDED = "BIRTH_RECORDED"
    NICU_ESCALATED = "NICU_ESCALATED"
    NICU_BED_ASSIGNED = "NICU_BED_ASSIGNED"
    STEP_DOWN = "STEP_DOWN"
    DISCHARGED = "DISCHARGED"
    BAG_ISSUED = "BAG_ISSUED"
    DEPENDENT_ENROLLED = "DEPENDENT_ENROLLED"
    SEP_EXPIRED = "SEP_EXPIRED"
    FILING_SUBMITTED = "FILING_SUBMITTED"
    FILING_LATE_FLAGGED = "FILING_LATE_FLAGGED"
    FOLLOWUP_ESCALATED = "FOLLOWUP_ESCALATED"


# --- Entity TypedDicts ---
# Resources below carry the four common system fields id/created_at/updated_at/version
# (PRD §2.4), except AuditEvent, which is immutable and omits updated_at + version.

class PreRegistration(TypedDict, total=False):
    id: str
    mother_full_name: str
    mother_dob: str
    due_date: str
    payer_policy_id: str
    planned_delivery_facility: str
    birth_plan_flags: dict
    status: str
    admitted_at: Optional[str]
    newborn_count: int
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    carrier_name: str
    subscriber_name: str
    plan_type: str
    coverage_effective_date: str
    dependent_slots_max: int
    dependents_added_count: int
    created_at: str
    updated_at: str
    version: int


class Newborn(TypedDict, total=False):
    id: str
    pre_registration_id: str
    birth_datetime: str
    birth_sequence: int
    weight_grams: int
    gestational_age_weeks: int
    apgar_5min: int
    legal_name: Optional[str]
    clinical_status: str
    care_location: str
    discharge_readiness_score: int
    discharged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LactationConsult(TypedDict, total=False):
    id: str
    newborn_id: str
    consult_datetime: str
    latch_score: Optional[int]
    status: str
    feeding_adequate: bool
    created_at: str
    updated_at: str
    version: int


class NicuBed(TypedDict, total=False):
    id: str
    bed_label: str
    acuity_level: str
    occupancy_status: str
    current_stay_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NicuStay(TypedDict, total=False):
    id: str
    newborn_id: str
    nicu_bed_id: Optional[str]
    required_level: str
    admitted_at: str
    discharged_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DischargeBag(TypedDict, total=False):
    id: str
    newborn_id: str
    line_items: List[dict]
    status: str
    total_value_cents: int
    requires_pharmacy_signoff: bool
    created_at: str
    updated_at: str
    version: int


class FollowUpTask(TypedDict, total=False):
    id: str
    newborn_id: str
    task_type: str
    due_at: str
    scheduled_at: Optional[str]
    attempt_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DependentEnrollment(TypedDict, total=False):
    id: str
    newborn_id: str
    policy_id: str
    requested_at: str
    sep_deadline: str
    status: str
    retroactive_effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GovernmentFiling(TypedDict, total=False):
    id: str
    newborn_id: str
    filing_type: str
    filing_deadline: str
    submitted_at: Optional[str]
    acknowledged_at: Optional[str]
    reference_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable audit record (PRD §2.4 / §2.10): id + created_at only, no updated_at/version.
class AuditEvent(TypedDict, total=False):
    id: str
    newborn_id: Optional[str]
    actor_role: str
    event_type: str
    detail: dict
    created_at: str
