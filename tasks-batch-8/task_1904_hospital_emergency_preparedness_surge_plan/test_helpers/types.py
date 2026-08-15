"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    EMERGENCY_MANAGER = "EmergencyManager"
    INCIDENT_COMMANDER = "IncidentCommander"
    PLANNING_CHIEF = "PlanningChief"
    LOGISTICS_CHIEF = "LogisticsChief"
    PUBLIC_INFORMATION_OFFICER = "PublicInformationOfficer"
    LIAISON_OFFICER = "LiaisonOfficer"
    HOSPITAL_ADMINISTRATOR = "HospitalAdministrator"
    ON_CALL_STAFF = "OnCallStaff"
    PLATFORM_ADMIN = "PlatformAdmin"


class Department(str, Enum):
    EMERGENCY = "EMERGENCY"
    ICU = "ICU"
    SURGERY = "SURGERY"
    NURSING = "NURSING"
    PHARMACY = "PHARMACY"
    LOGISTICS = "LOGISTICS"
    ADMINISTRATION = "ADMINISTRATION"


class CommandRole(str, Enum):
    INCIDENT_COMMANDER = "INCIDENT_COMMANDER"
    PLANNING_CHIEF = "PLANNING_CHIEF"
    LOGISTICS_CHIEF = "LOGISTICS_CHIEF"
    PUBLIC_INFORMATION_OFFICER = "PUBLIC_INFORMATION_OFFICER"
    LIAISON_OFFICER = "LIAISON_OFFICER"
    SAFETY_OFFICER = "SAFETY_OFFICER"
    MEDICAL_BRANCH_DIRECTOR = "MEDICAL_BRANCH_DIRECTOR"


class HazardAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class PlanRevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ExerciseEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AfterActionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class ImprovementTaskStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    OVERDUE = "OVERDUE"
    VERIFIED_COMPLETE = "VERIFIED_COMPLETE"


class IncidentEventStatus(str, Enum):
    ACTIVATED = "ACTIVATED"
    DEACTIVATED = "DEACTIVATED"


class SurgeTier(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


class CommandRoleAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELIEVED = "RELIEVED"


class CallBackRequestStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class StockTransactionType(str, Enum):
    RECEIVE = "RECEIVE"
    ISSUE = "ISSUE"
    RETURN = "RETURN"
    ADJUST = "ADJUST"


class AlternateCareSiteStatus(str, Enum):
    STANDBY = "STANDBY"
    COMMITTED = "COMMITTED"
    ACTIVATED = "ACTIVATED"
    DEMOBILIZED = "DEMOBILIZED"


class PatientTrackRecordStatus(str, Enum):
    TRACKED = "TRACKED"
    TRANSFERRED = "TRANSFERRED"
    DISCHARGED = "DISCHARGED"


class TriageCategory(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    DELAYED = "DELAYED"
    MINOR = "MINOR"
    EXPECTANT = "EXPECTANT"


class FamilyInquiryStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    REUNITED = "REUNITED"
    CLOSED_NO_MATCH = "CLOSED_NO_MATCH"


class ExternalReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class ReportType(str, Enum):
    SITREP = "SITREP"
    SURGE_CAPACITY = "SURGE_CAPACITY"
    AAR_SUMMARY = "AAR_SUMMARY"
    RESOURCE_REQUEST = "RESOURCE_REQUEST"


class ReportAudience(str, Enum):
    REGIONAL_COALITION = "REGIONAL_COALITION"
    STATE_DOH = "STATE_DOH"
    CMS = "CMS"
    LOCAL_EMA = "LOCAL_EMA"


class HazardCategory(str, Enum):
    NATURAL = "NATURAL"
    TECHNOLOGICAL = "TECHNOLOGICAL"
    HUMAN = "HUMAN"
    HAZMAT = "HAZMAT"


class IncidentType(str, Enum):
    NATURAL = "NATURAL"
    TECHNOLOGICAL = "TECHNOLOGICAL"
    HUMAN = "HUMAN"
    HAZMAT = "HAZMAT"
    INFECTIOUS = "INFECTIOUS"


class ScoringModel(str, Enum):
    TWO_FACTOR = "TWO_FACTOR"
    THREE_FACTOR_MITIGATION = "THREE_FACTOR_MITIGATION"


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    badge_number: str
    department: str
    role_qualifications: List[str]
    is_active: bool
    callback_eligible: bool
    callback_seniority_score: int
    created_at: str
    updated_at: str
    version: int


class HazardEntry(TypedDict, total=False):
    entry_key: str
    hazard_name: str
    category: str
    probability: int
    severity: int
    preparedness: int
    risk_score: int


class HazardAssessment(TypedDict, total=False):
    id: str
    fiscal_year: str
    scoring_model: str
    hazard_entries: List[HazardEntry]
    max_risk_score: int
    plan_review_triggered: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanRevision(TypedDict, total=False):
    id: str
    revision_label: str
    change_summary: str
    effective_date: str
    supersedes_revision_id: Optional[str]
    source_hva_id: Optional[str]
    status: str
    created_by_id: str
    approved_by_id: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExerciseEvent(TypedDict, total=False):
    id: str
    exercise_name: str
    exercise_type: str
    scenario_category: str
    scheduled_start: str
    scheduled_end: str
    plan_revision_id: str
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AfterActionReport(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    summary: str
    status: str
    created_by_id: str
    submitted_at: Optional[str]
    approved_by_id: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImprovementTask(TypedDict, total=False):
    id: str
    after_action_report_id: str
    description: str
    priority: str
    due_date: str
    assigned_department: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IncidentEvent(TypedDict, total=False):
    id: str
    incident_name: str
    incident_type: str
    declared_at: str
    status: str
    activation_count: int
    activated_at: str
    deactivated_at: Optional[str]
    staffed_bed_count: Optional[int]
    projected_census: Optional[int]
    licensed_surge_capacity: Optional[int]
    operational_surge_capacity: Optional[int]
    current_surge_tier: Optional[str]
    committed_staff_count: int
    created_at: str
    updated_at: str
    version: int


class CommandRoleAssignment(TypedDict, total=False):
    id: str
    incident_id: str
    staff_member_id: str
    command_role: str
    status: str
    assigned_at: str
    created_at: str
    updated_at: str
    version: int


class CallBackRequest(TypedDict, total=False):
    id: str
    incident_id: str
    staff_member_id: str
    response_window_hours: int
    status: str
    expires_at: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplyItem(TypedDict, total=False):
    id: str
    item_name: str
    category: str
    unit: str
    reorder_min_days: int
    quantity_on_hand: int
    observed_daily_burn_rate: float
    projected_daily_burn_rate: float
    days_of_supply: Optional[int]
    below_reorder_level: bool
    created_at: str
    updated_at: str
    version: int


class StockTransaction(TypedDict, total=False):
    # Append-only ledger entry: id + created_at only — no updated_at, no version
    # (PRD §2.4 ledger exception).
    id: str
    supply_item_id: str
    transaction_type: str
    quantity: int
    occurred_at: str
    incident_id: Optional[str]
    note: Optional[str]
    created_at: str


class SiteCommitment(TypedDict, total=False):
    incident_id: str
    window_start: str
    window_end: str


class AlternateCareSite(TypedDict, total=False):
    id: str
    site_name: str
    address: str
    bed_capacity: int
    status: str
    commitments: List[SiteCommitment]
    activated_incident_id: Optional[str]
    current_census: int
    created_at: str
    updated_at: str
    version: int


class PatientTrackRecord(TypedDict, total=False):
    id: str
    incident_id: str
    patient_ref: str
    triage_category: str
    arrival_at: str
    status: str
    transfer_site_id: Optional[str]
    transferred_at: Optional[str]
    discharged_at: Optional[str]
    reunified: bool
    created_at: str
    updated_at: str
    version: int


class FamilyInquiry(TypedDict, total=False):
    id: str
    incident_id: str
    inquirer_name: str
    inquirer_phone: str
    sought_patient_ref: str
    status: str
    matched_patient_record_id: Optional[str]
    matched_at: Optional[str]
    reunited_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExternalReport(TypedDict, total=False):
    id: str
    audience: str
    report_type: str
    incident_id: Optional[str]
    period_start: str
    period_end: str
    body_summary: str
    due_at: str
    status: str
    created_by_id: str
    submitted_at: Optional[str]
    submitted_late: Optional[bool]
    hours_late: Optional[float]
    created_at: str
    updated_at: str
    version: int
