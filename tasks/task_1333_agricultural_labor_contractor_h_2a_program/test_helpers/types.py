"""Domain types: entity TypedDicts, status enums, role enum (PRD 2.1, 2.5, 3.x).

Money is integer cents; calendar dates are ISO YYYY-MM-DD strings (PRD 2.6).
Entities documented as append-only ledger entries (housing inspections and
work logs, PRD 2.5) carry only ``id`` and ``created_at`` — no ``updated_at``
and no ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CONTRACTOR_ADMIN = "ContractorAdmin"
    GROWER_REP = "GrowerRep"
    PROGRAM_REVIEWER = "ProgramReviewer"
    HOUSING_INSPECTOR = "HousingInspector"
    VISA_OFFICER = "VisaOfficer"
    WAGE_AUDITOR = "WageAuditor"
    SYSTEM_ADMIN = "SystemAdmin"


class GrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEBARRED = "DEBARRED"


class WageDeterminationStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class Activity(str, Enum):
    HARVEST = "HARVEST"
    PACKING = "PACKING"
    PLANTING = "PLANTING"
    GENERAL = "GENERAL"


class JobOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DEFICIENCY = "DEFICIENCY"
    CERTIFIED = "CERTIFIED"
    RECRUITING = "RECRUITING"
    PETITIONING = "PETITIONING"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationStatus(str, Enum):
    APPLIED = "APPLIED"
    HIRED = "HIRED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class Qualification(str, Enum):
    QUALIFIED = "QUALIFIED"
    UNQUALIFIED = "UNQUALIFIED"


class Decision(str, Enum):
    HIRE = "HIRE"
    REJECT = "REJECT"


class WorkerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    PETITIONED = "PETITIONED"
    VISA_ISSUED = "VISA_ISSUED"
    WORKING = "WORKING"
    DEPARTED = "DEPARTED"
    ABANDONED = "ABANDONED"


class PetitionStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    RFE = "RFE"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class AdjudicationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AppointmentOutcome(str, Enum):
    ISSUED = "ISSUED"
    REFUSED = "REFUSED"
    NO_SHOW = "NO_SHOW"


class HousingInspectionStatus(str, Enum):
    UNINSPECTED = "UNINSPECTED"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class HousingAssignmentStatus(str, Enum):
    OCCUPIED = "OCCUPIED"
    VACATED = "VACATED"


class AssignmentStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class EndReason(str, Enum):
    COMPLETED = "COMPLETED"
    FOR_CAUSE = "FOR_CAUSE"
    ABANDONED = "ABANDONED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class TransferStatus(str, Enum):
    PENDING = "PENDING"
    GROWER_APPROVED = "GROWER_APPROVED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class TransferReason(str, Enum):
    CONTRACT_IMPOSSIBILITY = "CONTRACT_IMPOSSIBILITY"
    GROWER_REQUEST = "GROWER_REQUEST"
    WORKER_REQUEST = "WORKER_REQUEST"


class AuditCaseStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    RESOLVED_PENALTY = "RESOLVED_PENALTY"
    RESOLVED_DEBARMENT = "RESOLVED_DEBARMENT"


class TriggerSource(str, Enum):
    MANUAL = "MANUAL"
    ABANDONMENT = "ABANDONMENT"
    HOUSING = "HOUSING"
    WAGE_DISCREPANCY = "WAGE_DISCREPANCY"


class ViolationCode(str, Enum):
    WAGE_UNDERPAYMENT = "WAGE_UNDERPAYMENT"
    HOUSING_SUBSTANDARD = "HOUSING_SUBSTANDARD"
    TRANSPORT_VIOLATION = "TRANSPORT_VIOLATION"
    RECRUITMENT_VIOLATION = "RECRUITMENT_VIOLATION"
    RECORDKEEPING = "RECORDKEEPING"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common fields: id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Grower(TypedDict):
    id: str
    legal_name: str
    fein: str
    state_code: str
    status: str
    debarment_ends_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WageDetermination(TypedDict):
    id: str
    state_code: str
    crop: str
    activity: str
    effective_year: int
    aewr_hourly_cents: int
    prevailing_hourly_cents: int
    prevailing_piece_rate_cents_per_unit: Optional[int]
    piece_unit_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class JobOrder(TypedDict):
    id: str
    grower_id: str
    wage_determination_id: str
    title: str
    crop: str
    activity: str
    worksite_state: str
    work_start_date: str
    work_end_date: str
    daily_standard_hours: int
    workers_requested: int
    offered_hourly_cents: int
    offered_piece_rate_cents_per_unit: Optional[int]
    inbound_transport_cents: int
    outbound_transport_cents: int
    status: str
    deficiency_note: Optional[str]
    locked_aewr_hourly_cents: Optional[int]
    locked_prevailing_hourly_cents: Optional[int]
    locked_prevailing_piece_rate_cents_per_unit: Optional[int]
    required_hourly_floor_cents: int
    effective_piece_rate_cents_per_unit: Optional[int]
    total_calendar_days: int
    total_workdays: int
    recruitment_cutoff_date: str
    transport_threshold_date: str
    domestic_hired_count: int
    visa_worker_ceiling: int
    created_at: str
    updated_at: str
    version: int


class DomesticApplication(TypedDict):
    id: str
    job_order_id: str
    applicant_name: str
    contact_phone: str
    applied_on: str
    status: str
    qualification: Optional[str]
    decided_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    full_name: str
    passport_number: str
    date_of_birth: str
    country_code: str
    status: str
    petition_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VisaPetition(TypedDict):
    id: str
    job_order_id: str
    receipt_code: str
    requested_worker_count: int
    approved_worker_count: Optional[int]
    rfe_count: int
    filed_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsularAppointment(TypedDict):
    id: str
    worker_id: str
    petition_id: str
    consulate_code: str
    appointment_date: str
    status: str
    outcome: Optional[str]
    completed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HousingUnit(TypedDict):
    id: str
    grower_id: str
    name: str
    capacity: int
    inspection_status: str
    certified_on: Optional[str]
    certification_valid_until: Optional[str]
    occupied_count: int
    created_at: str
    updated_at: str
    version: int


class HousingInspection(TypedDict):
    # Append-only ledger entry (PRD 2.5): only id + created_at system fields.
    id: str
    housing_unit_id: str
    inspected_on: str
    result: str
    deficiency_codes: List[str]
    created_at: str


class HousingAssignment(TypedDict):
    id: str
    housing_unit_id: str
    worker_id: str
    worker_assignment_id: str
    move_in_date: str
    move_out_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkerAssignment(TypedDict):
    id: str
    worker_id: str
    job_order_id: str
    started_on: Optional[str]
    ended_on: Optional[str]
    end_reason: Optional[str]
    guarantee_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkLog(TypedDict):
    # Append-only ledger entry (PRD 2.5): only id + created_at system fields.
    id: str
    worker_assignment_id: str
    work_date: str
    hours_worked: float
    units_picked: int
    created_at: str


class WageReconciliation(TypedDict):
    id: str
    worker_assignment_id: str
    status: str
    computed_through_date: str
    total_units: int
    piece_earnings_cents: int
    hourly_floor_earnings_cents: int
    makeup_pay_cents: int
    guarantee_basis_workdays: int
    guaranteed_quarters: int
    worked_quarters: int
    shortfall_quarters: int
    guarantee_pay_cents: int
    guarantee_applied: bool
    inbound_transport_owed_cents: int
    outbound_transport_owed_cents: int
    total_due_cents: int
    finalized_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    worker_id: str
    from_assignment_id: str
    to_job_order_id: str
    reason: str
    requested_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    violation_code: str
    count: int
    willful: bool


class AuditCase(TypedDict):
    id: str
    grower_id: str
    job_order_id: Optional[str]
    trigger_source: str
    note: Optional[str]
    opened_on: str
    status: str
    findings: List[AuditFinding]
    provisional_exposure_cents: Optional[int]
    final_penalty_cents: Optional[int]
    debarment_years: Optional[int]
    closed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int
