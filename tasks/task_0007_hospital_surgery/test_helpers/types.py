"""Domain types for the hospital surgery scheduling system."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    SURGICAL_COORDINATOR = "SurgicalCoordinator"
    DEPARTMENT_HEAD = "DepartmentHead"
    SCHEDULER = "Scheduler"
    BILLING_ADMIN = "BillingAdmin"
    ANY = "Any"


class RoomType(str, Enum):
    GENERAL_OR = "GENERAL_OR"
    CARDIAC_OR = "CARDIAC_OR"
    NEURO_OR = "NEURO_OR"
    OBSTETRIC_OR = "OBSTETRIC_OR"


class Specialty(str, Enum):
    GENERAL = "GENERAL"
    CARDIAC = "CARDIAC"
    NEURO = "NEURO"
    OBSTETRIC = "OBSTETRIC"


class StaffQualification(str, Enum):
    GENERAL = "GENERAL"
    CARDIAC = "CARDIAC"
    NEURO = "NEURO"
    OBSTETRIC = "OBSTETRIC"
    PEDIATRIC = "PEDIATRIC"


class StaffRoleType(str, Enum):
    ANESTHESIOLOGIST = "ANESTHESIOLOGIST"
    SCRUB_NURSE = "SCRUB_NURSE"
    CIRCULATING_NURSE = "CIRCULATING_NURSE"


class RoleInCase(str, Enum):
    LEAD_ANESTHESIOLOGIST = "LEAD_ANESTHESIOLOGIST"
    SCRUB_NURSE = "SCRUB_NURSE"
    CIRCULATING_NURSE = "CIRCULATING_NURSE"


class CasePriority(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    EMERGENCY = "EMERGENCY"


class CaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    PREEMPTED = "PREEMPTED"


class AssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"
    PREEMPTED = "PREEMPTED"


class SterilizationStatus(str, Enum):
    SOILED = "SOILED"
    IN_STERILIZATION = "IN_STERILIZATION"
    CLEAN_STERILIZED = "CLEAN_STERILIZED"
    CHECKED_OUT = "CHECKED_OUT"
    EXPIRED = "EXPIRED"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED_SOILED = "RETURNED_SOILED"
    RELEASED = "RELEASED"
    PREEMPTED = "PREEMPTED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    PRE_AUTHORIZED = "PRE_AUTHORIZED"
    ITEMIZED = "ITEMIZED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class OperatingRoom(TypedDict):
    id: str
    room_number: str
    room_type: str
    equipment_list: List[str]
    specialty_required: str
    turnover_buffer_minutes: int
    hourly_rate: float
    created_at: str
    updated_at: str
    version: int


class SurgicalCase(TypedDict):
    id: str
    patient_id: str
    surgery_type: str
    specialty_required: str
    priority: str
    pre_op_assessment_attached: bool
    informed_consent_verified: bool
    planned_start_minute: Optional[int]
    planned_end_minute: Optional[int]
    scheduled_room_id: Optional[str]
    actual_start_minute: Optional[int]
    actual_end_minute: Optional[int]
    implant_cost_estimate: float
    implant_cost_actual: Optional[float]
    status: str
    rejected_reason: Optional[str]
    preempted_at_minute: Optional[int]
    preempted_by_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    staff_name: str
    staff_role: str
    qualifications: List[str]
    hourly_rate: float
    shift_start_minute: int
    shift_end_minute: int
    on_call: bool
    planned_workload_minutes: int
    actual_workload_minutes: int
    created_at: str
    updated_at: str
    version: int


class CaseAssignment(TypedDict):
    id: str
    case_id: str
    staff_id: str
    role_in_case: str
    assigned_start_minute: int
    assigned_end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstrumentSet(TypedDict):
    id: str
    set_name: str
    specialty: str
    sterilization_status: str
    last_sterilized_at_minute: Optional[int]
    current_case_id: Optional[str]
    cycle_count: int
    created_at: str
    updated_at: str
    version: int


class InstrumentBooking(TypedDict):
    id: str
    case_id: str
    instrument_set_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    case_id: str
    status: str
    estimated_total_amount: Optional[float]
    final_total_amount: Optional[float]
    line_items: List[dict]
    insurance_split: List[dict]
    per_payer_amounts: List[dict]
    implant_cost: float
    refund_amount: float
    insurance_pre_auth_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


# AuditEntry — append-only, has only id + created_at (no updated_at, no version)
class AuditEntry(TypedDict):
    id: str
    actor_role: str
    actor_user_id: str
    entity_type: str
    entity_id: str
    action: str
    payload: dict
    occurred_at_minute: int
    created_at: str
