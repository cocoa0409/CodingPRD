"""Domain types for the research security and foreign influence disclosure API.

Entity TypedDicts, enum vocabularies and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #

class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    RESEARCH_SECURITY_OFFICER = "ResearchSecurityOfficer"
    CONFLICT_REVIEW_OFFICIAL = "ConflictReviewOfficial"
    AGENCY_LIAISON = "AgencyLiaison"
    INVESTIGATOR = "Investigator"


# --------------------------------------------------------------------------- #
# Investigator
# --------------------------------------------------------------------------- #

class AppointmentType(str, Enum):
    FACULTY = "FACULTY"
    RESEARCH_STAFF = "RESEARCH_STAFF"
    POSTDOC = "POSTDOC"


class DisclosurePosture(str, Enum):
    CLEAR = "CLEAR"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class Investigator(TypedDict):
    id: str
    full_name: str
    email: str
    appointment_type: str
    home_department: str
    institutional_base_effort_pct: float
    committed_effort_pct: float
    outside_effort_pct: float
    total_commitment_pct: float
    overcommitment_pct: float
    risk_score: int
    substantiated_incident_count: int
    material_discrepancy_count: int
    training_compliant: bool
    disclosure_posture: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# ForeignOrganization
# --------------------------------------------------------------------------- #

class OrgType(str, Enum):
    UNIVERSITY = "UNIVERSITY"
    INSTITUTE = "INSTITUTE"
    COMPANY = "COMPANY"
    GOVERNMENT_AGENCY = "GOVERNMENT_AGENCY"
    TALENT_PROGRAM = "TALENT_PROGRAM"


class Designation(str, Enum):
    NONE = "NONE"
    UNVERIFIED_END_USER = "UNVERIFIED_END_USER"
    ENTITY_LIST = "ENTITY_LIST"
    FOREIGN_MILITARY = "FOREIGN_MILITARY"
    MALIGN_TALENT_PROGRAM = "MALIGN_TALENT_PROGRAM"
    SDN = "SDN"


class ForeignOrganization(TypedDict):
    id: str
    legal_name: str
    country_code: str
    org_type: str
    parent_organization_id: Optional[str]
    parent_ownership_pct: float
    own_designation: str
    designated_on: Optional[str]
    effective_designation: str
    effective_designation_depth: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Project
# --------------------------------------------------------------------------- #

class AgencyCode(str, Enum):
    NIH = "NIH"
    NSF = "NSF"
    DOD = "DOD"
    DOE = "DOE"
    NASA = "NASA"


class SensitivityLevel(str, Enum):
    STANDARD = "STANDARD"
    CONTROLLED = "CONTROLLED"
    RESTRICTED = "RESTRICTED"


class AwardStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVATION_PENDING = "ACTIVATION_PENDING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class SecurityStatus(str, Enum):
    PENDING_CLEARANCE = "PENDING_CLEARANCE"
    CLEARED = "CLEARED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SecurityStatusReason(str, Enum):
    NONE = "NONE"
    OFFICER_ACTION = "OFFICER_ACTION"
    SUBAWARD_BLOCKED = "SUBAWARD_BLOCKED"
    INVESTIGATOR_SUSPENDED = "INVESTIGATOR_SUSPENDED"
    INCIDENT_NOTIFICATION = "INCIDENT_NOTIFICATION"


class ControlledAreaPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    LOCKED_DOWN = "LOCKED_DOWN"


class ActivationBlocker(str, Enum):
    SECURITY_NOT_CLEARED = "SECURITY_NOT_CLEARED"
    DISCLOSURE_NOT_CERTIFIED = "DISCLOSURE_NOT_CERTIFIED"
    TRAINING_INCOMPLETE = "TRAINING_INCOMPLETE"
    SUBAWARD_BLOCKED = "SUBAWARD_BLOCKED"
    SUPPORT_INCONSISTENT = "SUPPORT_INCONSISTENT"
    PERSONNEL_MISSING_PI = "PERSONNEL_MISSING_PI"
    INVESTIGATOR_SUSPENDED = "INVESTIGATOR_SUSPENDED"


class Project(TypedDict):
    id: str
    title: str
    agency_code: str
    sensitivity_level: str
    award_amount_cents: int
    period_start: str
    period_end: str
    controlled_area_capacity: int
    award_status: str
    security_status: str
    security_status_reason: str
    activation_blockers: List[str]
    active_grant_count: int
    controlled_area_posture: str
    open_incident_count: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# ProjectPersonnel
# --------------------------------------------------------------------------- #

class PersonnelRole(str, Enum):
    PI = "PI"
    CO_PI = "CO_PI"
    SENIOR_PERSONNEL = "SENIOR_PERSONNEL"
    KEY_PERSON = "KEY_PERSON"


class PersonnelStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ProjectPersonnel(TypedDict):
    id: str
    project_id: str
    investigator_id: str
    role_on_project: str
    committed_person_months: float
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Disclosure
# --------------------------------------------------------------------------- #

class DisclosureType(str, Enum):
    ANNUAL = "ANNUAL"
    EVENT_DRIVEN = "EVENT_DRIVEN"
    PROPOSAL = "PROPOSAL"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PlanStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PLAN_REQUIRED = "PLAN_REQUIRED"
    PLAN_ISSUED = "PLAN_ISSUED"
    PLAN_ACKNOWLEDGED = "PLAN_ACKNOWLEDGED"
    PLAN_WAIVED = "PLAN_WAIVED"
    PLAN_TERMINATED = "PLAN_TERMINATED"


class CompletenessTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class ReviewAction(str, Enum):
    BEGIN_REVIEW = "BEGIN_REVIEW"
    RETURN_FOR_REVISION = "RETURN_FOR_REVISION"
    CERTIFY = "CERTIFY"
    REJECT = "REJECT"
    REQUIRE_PLAN = "REQUIRE_PLAN"


class PlanAction(str, Enum):
    ISSUE = "ISSUE"
    ACKNOWLEDGE = "ACKNOWLEDGE"
    WAIVE = "WAIVE"
    TERMINATE = "TERMINATE"


class Disclosure(TypedDict):
    id: str
    investigator_id: str
    cycle_label: str
    disclosure_type: str
    review_status: str
    plan_status: str
    revision_round: int
    item_count: int
    late_item_count: int
    undisclosed_item_count: int
    completeness_score: int
    completeness_tier: str
    submitted_at: Optional[str]
    certified_at: Optional[str]
    reviewer_user_id: Optional[str]
    plan_effort_cap_pct: Optional[float]
    plan_required_actions: List[str]
    plan_effective_from: Optional[str]
    plan_expires_on: Optional[str]
    plan_approver_user_id: Optional[str]
    plan_acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# DisclosureItem
# --------------------------------------------------------------------------- #

class ItemType(str, Enum):
    FOREIGN_APPOINTMENT = "FOREIGN_APPOINTMENT"
    TALENT_PROGRAM = "TALENT_PROGRAM"
    OUTSIDE_SUPPORT = "OUTSIDE_SUPPORT"
    IN_KIND_RESOURCE = "IN_KIND_RESOURCE"
    VISITING_SCHOLAR = "VISITING_SCHOLAR"


class ItemStatus(str, Enum):
    DECLARED = "DECLARED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    WITHDRAWN = "WITHDRAWN"


class ItemSource(str, Enum):
    SELF_REPORTED = "SELF_REPORTED"
    INCIDENT_REMEDIATION = "INCIDENT_REMEDIATION"


class DisclosureItem(TypedDict):
    id: str
    disclosure_id: str
    item_type: str
    foreign_organization_id: str
    annual_effort_hours: float
    compensation_usd_cents: int
    in_kind_value_cents: int
    start_date: str
    end_date: Optional[str]
    is_paid: bool
    item_risk_points: int
    status: str
    source: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# SupportStatement
# --------------------------------------------------------------------------- #

class DocumentType(str, Enum):
    CURRENT_AND_PENDING = "CURRENT_AND_PENDING"
    BIOSKETCH = "BIOSKETCH"


class StatementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    INCONSISTENT = "INCONSISTENT"
    SUPERSEDED = "SUPERSEDED"


class ReconcileVariant(str, Enum):
    STRICT_AGENCY = "STRICT_AGENCY"
    INSTITUTIONAL_ROLLUP = "INSTITUTIONAL_ROLLUP"


class ReconcileVerdict(str, Enum):
    CONSISTENT = "CONSISTENT"
    MINOR_VARIANCE = "MINOR_VARIANCE"
    MATERIAL_DISCREPANCY = "MATERIAL_DISCREPANCY"


class SupportStatement(TypedDict):
    id: str
    investigator_id: str
    project_id: str
    agency_code: str
    document_type: str
    declared_person_months: float
    declared_appointment_count: int
    declared_support_count: int
    status: str
    applied_variant: Optional[str]
    institutional_person_months: Optional[float]
    variance_person_months: Optional[float]
    omission_count: Optional[int]
    verdict: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# TravelRegistration
# --------------------------------------------------------------------------- #

class TravelPurpose(str, Enum):
    CONFERENCE = "CONFERENCE"
    COLLABORATION = "COLLABORATION"
    TEACHING = "TEACHING"
    RECRUITMENT = "RECRUITMENT"


class TravelStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class DeviceRequirementTier(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    LOANER_REQUIRED = "LOANER_REQUIRED"
    LOANER_PLUS_ESCORT = "LOANER_PLUS_ESCORT"


class TravelRegistration(TypedDict):
    id: str
    investigator_id: str
    project_id: Optional[str]
    host_organization_id: Optional[str]
    destination_country_code: str
    depart_on: str
    return_on: str
    purpose: str
    carries_institutional_device: bool
    risk_flag_count: int
    device_requirement_tier: str
    briefing_required: bool
    status: str
    device_decision_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# ControlledAccessGrant
# --------------------------------------------------------------------------- #

class GrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class GrantStatusReason(str, Enum):
    NONE = "NONE"
    OFFICER_ACTION = "OFFICER_ACTION"
    PROJECT_SUSPENDED = "PROJECT_SUSPENDED"
    INVESTIGATOR_RESTRICTED = "INVESTIGATOR_RESTRICTED"
    PERSONNEL_REMOVED = "PERSONNEL_REMOVED"
    PROJECT_TERMINATED = "PROJECT_TERMINATED"
    CAPACITY_UNAVAILABLE = "CAPACITY_UNAVAILABLE"


class ControlledAccessGrant(TypedDict):
    id: str
    project_id: str
    investigator_id: str
    valid_from: str
    valid_until: str
    peak_concurrency_at_request: int
    status: str
    status_reason: str
    activated_at: Optional[str]
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# SecurityIncident
# --------------------------------------------------------------------------- #

class IncidentType(str, Enum):
    UNDISCLOSED_APPOINTMENT = "UNDISCLOSED_APPOINTMENT"
    UNDISCLOSED_TALENT_PROGRAM = "UNDISCLOSED_TALENT_PROGRAM"
    UNREPORTED_TRAVEL = "UNREPORTED_TRAVEL"
    RESTRICTED_ENTITY_COLLABORATION = "RESTRICTED_ENTITY_COLLABORATION"
    DEVICE_COMPROMISE = "DEVICE_COMPROMISE"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    AGENCY_NOTIFIED = "AGENCY_NOTIFIED"
    CLOSED = "CLOSED"


class IncidentFinding(str, Enum):
    NONE = "NONE"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SecurityIncident(TypedDict):
    id: str
    investigator_id: str
    disclosure_id: Optional[str]
    project_id: Optional[str]
    incident_type: str
    discovered_on: str
    summary: str
    status: str
    finding: str
    severity_points: Optional[int]
    severity: Optional[str]
    lead_investigator_user_id: Optional[str]
    substantiated_at: Optional[str]
    notification_due_on: Optional[str]
    agency_notified_on: Optional[str]
    notification_reference: Optional[str]
    notified_late: bool
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# TrainingAssignment
# --------------------------------------------------------------------------- #

class CourseCode(str, Enum):
    RESEARCH_SECURITY_BASE = "RESEARCH_SECURITY_BASE"
    EXPORT_CONTROL = "EXPORT_CONTROL"
    INSIDER_THREAT = "INSIDER_THREAT"
    FOREIGN_TRAVEL_BRIEF = "FOREIGN_TRAVEL_BRIEF"
    CONTROLLED_AREA_SAFETY = "CONTROLLED_AREA_SAFETY"


class TrainingStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"
    EXPIRED = "EXPIRED"


class TrainingAssignment(TypedDict):
    id: str
    investigator_id: str
    required_for_project_id: Optional[str]
    course_code: str
    assigned_on: str
    due_on: str
    completed_on: Optional[str]
    waived_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Subaward
# --------------------------------------------------------------------------- #

class SubawardStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    BLOCKED = "BLOCKED"
    MITIGATED = "MITIGATED"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class ScreeningVariant(str, Enum):
    DIRECT_MATCH = "DIRECT_MATCH"
    OWNERSHIP_TRANSITIVE = "OWNERSHIP_TRANSITIVE"


class Subaward(TypedDict):
    id: str
    project_id: str
    organization_id: str
    scope: str
    amount_cents: int
    status: str
    applied_screening_variant: Optional[str]
    screening_designation: Optional[str]
    screening_matched_organization_id: Optional[str]
    screening_match_depth: Optional[int]
    screening_risk_points: Optional[int]
    mitigation_justification: Optional[str]
    executed_at: Optional[str]
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
