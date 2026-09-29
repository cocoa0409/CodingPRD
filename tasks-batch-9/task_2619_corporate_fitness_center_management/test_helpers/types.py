"""Domain types for the Corporate Fitness Center Management API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    OPERATOR_ADMIN = "OperatorAdmin"
    SITE_MANAGER = "SiteManager"
    FITNESS_STAFF = "FitnessStaff"
    CLIENT_SPONSOR = "ClientSponsor"
    MEMBER = "Member"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


# --------------------------------------------------------------------------
# Status / enum vocabularies
# --------------------------------------------------------------------------
class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CLIENT_APPROVAL = "PENDING_CLIENT_APPROVAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"


class FeeStructure(str, Enum):
    MANAGEMENT_FEE = "MANAGEMENT_FEE"
    COST_PLUS = "COST_PLUS"


class StaffingModel(str, Enum):
    OPERATOR_EMPLOYED = "OPERATOR_EMPLOYED"
    CLIENT_EMPLOYED = "CLIENT_EMPLOYED"
    HYBRID = "HYBRID"


class StaffRoleType(str, Enum):
    SITE_MANAGER = "SITE_MANAGER"
    GROUP_EX_INSTRUCTOR = "GROUP_EX_INSTRUCTOR"
    PERSONAL_TRAINER = "PERSONAL_TRAINER"
    WELLNESS_COORDINATOR = "WELLNESS_COORDINATOR"


class DutyStatus(str, Enum):
    ACTIVE_DUTY = "ACTIVE_DUTY"
    SUSPENDED_FROM_DUTY = "SUSPENDED_FROM_DUTY"
    OFFBOARDED = "OFFBOARDED"


class CredentialType(str, Enum):
    CPR_AED = "CPR_AED"
    FIRST_AID = "FIRST_AID"
    GROUP_EX_CERT = "GROUP_EX_CERT"
    PT_CERT = "PT_CERT"


class CredentialStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class RoomType(str, Enum):
    STUDIO = "STUDIO"
    WEIGHT_FLOOR = "WEIGHT_FLOOR"
    CARDIO_FLOOR = "CARDIO_FLOOR"
    WELLNESS_SUITE = "WELLNESS_SUITE"


class RoomState(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class AssetType(str, Enum):
    AED = "AED"
    CARDIO = "CARDIO"
    STRENGTH = "STRENGTH"


class AssetStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    MAINTENANCE_DUE = "MAINTENANCE_DUE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ReadinessStatus(str, Enum):
    READY = "READY"
    PADS_EXPIRING = "PADS_EXPIRING"
    NOT_READY = "NOT_READY"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ServiceEventType(str, Enum):
    AED_INSPECTION = "AED_INSPECTION"
    PREVENTIVE_SERVICE = "PREVENTIVE_SERVICE"
    TAKE_OUT_OF_SERVICE = "TAKE_OUT_OF_SERVICE"
    REPAIR_COMPLETE = "REPAIR_COMPLETE"


class ProgramType(str, Enum):
    GROUP_EXERCISE = "GROUP_EXERCISE"
    PERSONAL_TRAINING = "PERSONAL_TRAINING"
    WELLNESS_CHALLENGE = "WELLNESS_CHALLENGE"


class OfferingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CLOSED = "CLOSED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    STAFFED = "STAFFED"
    STAFFING_AT_RISK = "STAFFING_AT_RISK"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED_NO_COVER = "CANCELLED_NO_COVER"
    CANCELLED_CLIENT = "CANCELLED_CLIENT"
    CANCELLED_FACILITY = "CANCELLED_FACILITY"


class CancelReason(str, Enum):
    NO_COVER = "NO_COVER"
    CLIENT_REQUEST = "CLIENT_REQUEST"
    FACILITY = "FACILITY"


class AssignmentRole(str, Enum):
    LEAD = "LEAD"
    SUPPORT = "SUPPORT"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    VACANT_NEEDS_COVER = "VACANT_NEEDS_COVER"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class MemberClass(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    DEPENDENT = "DEPENDENT"
    RETIREE = "RETIREE"


class EligibilityStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ELIGIBLE = "ELIGIBLE"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class AccessStatus(str, Enum):
    NO_BADGE = "NO_BADGE"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class WaiverStatus(str, Enum):
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class ParticipationStatus(str, Enum):
    COUNTED = "COUNTED"
    VOIDED = "VOIDED"


class RecordedByRole(str, Enum):
    MEMBER = "MEMBER"
    FITNESS_STAFF = "FITNESS_STAFF"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SERIOUS = "SERIOUS"


class CauseCategory(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    MEDICAL = "MEDICAL"
    SLIP_FALL = "SLIP_FALL"
    OTHER = "OTHER"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLAIM_FILED = "CLAIM_FILED"
    CLOSED_NO_CLAIM = "CLOSED_NO_CLAIM"
    CLAIM_CLOSED = "CLAIM_CLOSED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------
# Entity shapes.  Records carrying `updated_at` + `version` are the ones the
# PRD describes as "most records"; the participation record is the documented
# exception and carries only `id` and `created_at`.
# --------------------------------------------------------------------------
class ClientContract(TypedDict):
    id: str
    client_name: str
    site_code: str
    fee_structure: str
    staffing_model: str
    management_fee_cents: Optional[int]
    not_to_exceed_cents: Optional[int]
    budgeted_staff_fte: float
    participation_target_pct: int
    term_start_on: str
    term_end_on: str
    supersedes_contract_id: Optional[str]
    status: str
    revision_round: int
    ytd_billed_cents: int
    pending_penalty_cents: int
    uncovered_session_count: int
    eligible_member_count: int
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    contract_id: str
    full_name: str
    role_type: str
    employment_type: str
    hourly_cost_cents: int
    duty_status: str
    readiness_index: int
    last_drill_on: Optional[str]
    committed_minutes_current_period: int
    required_credential_types: List[str]
    created_at: str
    updated_at: str
    version: int


class StaffCredential(TypedDict):
    id: str
    staff_member_id: str
    credential_type: str
    issuer: str
    credential_number: str
    expires_on: str
    status: str
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class FacilityRoom(TypedDict):
    id: str
    contract_id: str
    room_name: str
    room_type: str
    max_occupancy: int
    room_state: str
    last_inspection_on: Optional[str]
    last_cleanliness_score: Optional[int]
    open_deficiency_count: int
    created_at: str
    updated_at: str
    version: int


class FacilityAsset(TypedDict):
    id: str
    contract_id: str
    room_id: str
    asset_type: str
    asset_tag: str
    status: str
    readiness_status: str
    pad_expiry_on: Optional[str]
    battery_expiry_on: Optional[str]
    service_interval_days: int
    last_inspection_on: Optional[str]
    last_service_on: Optional[str]
    out_of_service_since: Optional[str]
    out_of_service_days_current_period: int
    created_at: str
    updated_at: str
    version: int


class ProgramOffering(TypedDict):
    id: str
    contract_id: str
    lead_staff_id: str
    program_type: str
    title: str
    participation_target: int
    max_participants_per_session: int
    eligible_member_classes: List[str]
    required_credential_type: str
    status: str
    provisional_attainment_pct: float
    final_attainment_pct: float
    counted_participation_total: int
    coverage_gap_count: int
    created_at: str
    updated_at: str
    version: int


class ProgramSession(TypedDict):
    id: str
    offering_id: str
    room_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    forecast_attendance: int
    direct_supply_cost_cents: int
    status: str
    scheduled_minutes: int
    actual_attendance: int
    cancel_reason: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict):
    id: str
    session_id: str
    staff_member_id: str
    role_on_session: str
    status: str
    paid_minutes: int
    labor_cost_cents: int
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    contract_id: str
    sponsor_member_id: Optional[str]
    member_class: str
    full_name: str
    employee_number: Optional[str]
    eligibility_status: str
    access_status: str
    health_data_consent: bool
    incentive_points_balance: int
    current_waiver_id: Optional[str]
    last_check_in_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiabilityWaiver(TypedDict):
    id: str
    member_id: str
    waiver_version_code: str
    expires_on: str
    acknowledged_health_disclosure: bool
    signed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ParticipationRecord(TypedDict):
    """Append-only check-in event: only `id` and `created_at` — no
    `updated_at` and no `version`."""
    id: str
    member_id: str
    session_id: str
    check_in_utc: str
    points_awarded: int
    points_capped: bool
    streak_bonus_applied: bool
    recorded_by_role: str
    health_metrics_note: Optional[str]
    status: str
    void_reason: Optional[str]
    created_at: str


class IncidentReport(TypedDict):
    id: str
    contract_id: str
    reported_by_staff_id: str
    member_id: Optional[str]
    asset_id: Optional[str]
    occurred_at_utc: str
    severity: str
    cause_category: str
    narrative: str
    aed_deployed: bool
    status: str
    reviewed_by_user_id: Optional[str]
    return_count: int
    claim_reference: Optional[str]
    closure_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonthlyInvoice(TypedDict):
    id: str
    contract_id: str
    period_month: str
    fee_structure_snapshot: str
    labor_subtotal_cents: int
    program_direct_cost_cents: int
    admin_markup_cents: int
    volume_credit_cents: int
    downtime_credit_cents: int
    coverage_penalty_cents: int
    gross_amount_cents: int
    net_amount_cents: int
    nte_capped: bool
    status: str
    dispute_reason: Optional[str]
    rebill_count: int
    issued_at: Optional[str]
    disputed_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
