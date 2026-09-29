"""Typed shapes and enumerations for the camp accreditation and health compliance API.

Every resource in this domain carries ``id``, ``created_at``, ``updated_at`` and
``version``; no entity is exempt, so the common-property block is mixed into every
resource TypedDict below.
"""

from __future__ import annotations

from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class Role:
    CAMP_DIRECTOR = "CampDirector"
    HEALTH_CARE_STAFF = "HealthCareStaff"
    VISITOR = "Visitor"
    ACCREDITATION_OFFICER = "AccreditationOfficer"
    STATE_LICENSING_AGENT = "StateLicensingAgent"

    ALL = [
        CAMP_DIRECTOR,
        HEALTH_CARE_STAFF,
        VISITOR,
        ACCREDITATION_OFFICER,
        STATE_LICENSING_AGENT,
    ]


# --------------------------------------------------------------------------
# Camp enumerations
# --------------------------------------------------------------------------
class CampType:
    RESIDENT = "RESIDENT"
    DAY = "DAY"
    TRAVEL_TRIP = "TRAVEL_TRIP"
    FAMILY = "FAMILY"
    SPECIAL_NEEDS = "SPECIAL_NEEDS"


class PopulationServed:
    YOUTH_ONLY = "YOUTH_ONLY"
    ADULT_INCLUSIVE = "ADULT_INCLUSIVE"
    MEDICALLY_FRAGILE = "MEDICALLY_FRAGILE"


class ProgramElement:
    AQUATICS_POOL = "AQUATICS_POOL"
    AQUATICS_OPEN_WATER = "AQUATICS_OPEN_WATER"
    ADVENTURE_CHALLENGE_COURSE = "ADVENTURE_CHALLENGE_COURSE"
    ADVENTURE_CLIMBING = "ADVENTURE_CLIMBING"
    HORSEBACK = "HORSEBACK"
    TRANSPORTATION = "TRANSPORTATION"
    TRIP_CAMPING = "TRIP_CAMPING"


class HealthStaffingLevel:
    NONE = "NONE"
    FIRST_AIDER_ONLY = "FIRST_AIDER_ONLY"
    LPN_ONSITE = "LPN_ONSITE"
    RN_ONSITE = "RN_ONSITE"
    PHYSICIAN_ONSITE = "PHYSICIAN_ONSITE"


class AccreditationStatus:
    NOT_ACCREDITED = "NOT_ACCREDITED"
    ACCREDITED = "ACCREDITED"
    ACCREDITED_WITH_CORRECTION = "ACCREDITED_WITH_CORRECTION"
    PROVISIONAL = "PROVISIONAL"
    REVOKED = "REVOKED"


class StateLicenseStatus:
    NONE = "NONE"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class CompliancePosture:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class HealthIntakeStatus:
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class RiskIndexVariant:
    PRE_VISIT = "PRE_VISIT"
    POST_VISIT = "POST_VISIT"


# --------------------------------------------------------------------------
# Standards book enumerations
# --------------------------------------------------------------------------
class StandardsSetStatus:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class StandardDomain:
    SUPERVISION = "SUPERVISION"
    HEALTH_WELLNESS = "HEALTH_WELLNESS"
    EMERGENCY_RESPONSE = "EMERGENCY_RESPONSE"
    AQUATICS = "AQUATICS"
    ADVENTURE = "ADVENTURE"
    TRANSPORTATION = "TRANSPORTATION"
    OPERATIONS = "OPERATIONS"


class PlanType:
    SUPERVISION = "SUPERVISION"
    HEALTH_CARE = "HEALTH_CARE"
    EMERGENCY_RESPONSE = "EMERGENCY_RESPONSE"
    AQUATICS_SAFETY = "AQUATICS_SAFETY"
    TRANSPORTATION_SAFETY = "TRANSPORTATION_SAFETY"
    ADVENTURE_OPERATIONS = "ADVENTURE_OPERATIONS"


class WrittenPlanStatus:
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVALIDATION_REQUIRED = "REVALIDATION_REQUIRED"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------
# Cycle / evaluation enumerations
# --------------------------------------------------------------------------
class CycleStatus:
    SELF_ASSESSMENT = "SELF_ASSESSMENT"
    VISIT_SCHEDULED = "VISIT_SCHEDULED"
    VISIT_COMPLETED = "VISIT_COMPLETED"
    IN_CORRECTION = "IN_CORRECTION"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class DecisionLevel:
    ACCREDITED = "ACCREDITED"
    ACCREDITED_WITH_CORRECTION = "ACCREDITED_WITH_CORRECTION"
    PROVISIONAL = "PROVISIONAL"
    DENIED = "DENIED"


class SelfScore:
    NOT_MET = "NOT_MET"
    PARTIAL = "PARTIAL"
    MET = "MET"


class SelfStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class VisitorScore:
    MET = "MET"
    NOT_MET = "NOT_MET"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ScoreSource:
    OBSERVED = "OBSERVED"
    DOCUMENT = "DOCUMENT"
    INTERVIEW = "INTERVIEW"


class VisitStatusAxis:
    """The evaluation row's visit-scoring dimension."""

    UNSCORED = "UNSCORED"
    SCORED = "SCORED"
    LOCKED = "LOCKED"


# --------------------------------------------------------------------------
# Visiting team enumerations
# --------------------------------------------------------------------------
class VisitorStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Certification:
    LEAD_VISITOR = "LEAD_VISITOR"
    AQUATICS_SPECIALIST = "AQUATICS_SPECIALIST"
    ADVENTURE_SPECIALIST = "ADVENTURE_SPECIALIST"
    HEALTH_SPECIALIST = "HEALTH_SPECIALIST"


class VisitStatus:
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    SCORED = "SCORED"
    RESCINDED = "RESCINDED"


class TeamRole:
    LEAD = "LEAD"
    MEMBER = "MEMBER"
    SPECIALIST_AQUATICS = "SPECIALIST_AQUATICS"
    SPECIALIST_ADVENTURE = "SPECIALIST_ADVENTURE"
    SPECIALIST_HEALTH = "SPECIALIST_HEALTH"


class AssignmentStatus:
    ASSIGNED = "ASSIGNED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class SpecialistDomain:
    AQUATICS = "AQUATICS"
    ADVENTURE = "ADVENTURE"
    HEALTH_WELLNESS = "HEALTH_WELLNESS"


# --------------------------------------------------------------------------
# Deficiency enumerations
# --------------------------------------------------------------------------
class DeficiencySeverity:
    MANDATORY_CRITICAL = "MANDATORY_CRITICAL"
    MANDATORY = "MANDATORY"
    SCORED = "SCORED"


class DeficiencyStatus:
    OPEN = "OPEN"
    PLAN_SUBMITTED = "PLAN_SUBMITTED"
    PLAN_ACCEPTED = "PLAN_ACCEPTED"
    CORRECTED = "CORRECTED"
    WAIVED = "WAIVED"
    ESCALATED = "ESCALATED"


class DeficiencyDecision:
    ACCEPT_PLAN = "ACCEPT_PLAN"
    REJECT_PLAN = "REJECT_PLAN"
    VERIFY_CORRECTION = "VERIFY_CORRECTION"
    WAIVE = "WAIVE"


class PlanReviewDecision:
    VERIFY = "VERIFY"
    REJECT = "REJECT"


# --------------------------------------------------------------------------
# Health centre enumerations
# --------------------------------------------------------------------------
class MedicationClass:
    OTC = "OTC"
    PRESCRIPTION = "PRESCRIPTION"
    CONTROLLED = "CONTROLLED"


class AdministeredByRole:
    RN = "RN"
    LPN = "LPN"
    FIRST_AIDER = "FIRST_AIDER"
    PHYSICIAN = "PHYSICIAN"
    UNLICENSED_DESIGNEE = "UNLICENSED_DESIGNEE"


class MedRecordStatus:
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class ComplianceFlag:
    COMPLIANT = "COMPLIANT"
    DOCUMENTATION_INCOMPLETE = "DOCUMENTATION_INCOMPLETE"


# --------------------------------------------------------------------------
# Annual reporting enumerations
# --------------------------------------------------------------------------
class AnnualReportStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LATE = "LATE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REOPENED = "REOPENED"
    ARCHIVED = "ARCHIVED"


class AnnualReportDecision:
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class IncidentType:
    SERIOUS_INJURY = "SERIOUS_INJURY"
    HOSPITALIZATION = "HOSPITALIZATION"
    DEATH = "DEATH"
    ABUSE_ALLEGATION = "ABUSE_ALLEGATION"
    MEDICATION_ERROR = "MEDICATION_ERROR"
    AQUATICS_RESCUE = "AQUATICS_RESCUE"
    TRANSPORTATION_COLLISION = "TRANSPORTATION_COLLISION"
    COMMUNICABLE_DISEASE_OUTBREAK = "COMMUNICABLE_DISEASE_OUTBREAK"


class DisclosureStatus:
    REPORTED = "REPORTED"
    LATE_DISCLOSED = "LATE_DISCLOSED"


# --------------------------------------------------------------------------
# Resource shapes
# --------------------------------------------------------------------------
class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Camp(CommonFields):
    name: str
    camp_type: str
    state_code: str
    population_served: str
    program_elements: List[str]
    resident_census: int
    max_daily_census: int
    distance_to_hospital_km: int
    health_staffing_level: str
    required_health_staffing_level: str
    prior_accredited_cycle_count: int
    state_license_number: Optional[str]
    state_license_status: str
    accreditation_status: str
    penalty_point_balance: int
    compliance_posture: str
    health_intake_status: str
    controlled_intake_units: int
    controlled_on_hand_units: int
    last_accredited_year: Optional[int]
    risk_index: float
    risk_index_variant: str


class StandardsSet(CommonFields):
    edition_code: str
    effective_year: int
    status: str
    published_at: Optional[str]
    standard_count: int
    mandatory_count: int


class Standard(CommonFields):
    standards_set_id: str
    code: str
    title: str
    domain: str
    mandatory: bool
    scoring_weight: int
    written_plan_type_required: Optional[str]
    applies_to_camp_types: List[str]
    applies_to_populations: List[str]
    requires_program_elements_any: List[str]
    requires_state_licensed: bool


class AccreditationCycle(CommonFields):
    camp_id: str
    standards_set_id: str
    cycle_year: int
    status: str
    applicable_standard_count: int
    applicable_mandatory_count: int
    self_assessment_submitted_at: Optional[str]
    provisional_mandatory_pct: Optional[float]
    final_mandatory_pct: Optional[float]
    final_weighted_pct: Optional[float]
    decision_level: Optional[str]
    open_deficiency_count: int
    assessed_fee_cents: Optional[int]
    correction_deadline_at: Optional[str]
    decision_issued_at: Optional[str]
    decision_issued_by_user_id: Optional[str]


class StandardEvaluation(CommonFields):
    cycle_id: str
    standard_id: str
    visit_id: Optional[str]
    applicable: bool
    mandatory: bool
    scoring_weight: int
    self_score: Optional[str]
    self_status: str
    written_plan_id: Optional[str]
    note: Optional[str]
    visitor_score: Optional[str]
    score_source: Optional[str]
    visit_status: str
    scored_by_visitor_id: Optional[str]


class WrittenPlan(CommonFields):
    camp_id: str
    plan_type: str
    body_ref: str
    effective_date: str
    expires_at: str
    physician_reviewed: bool
    status: str
    supersedes_plan_id: Optional[str]
    verified_at: Optional[str]
    reviewer_user_id: Optional[str]
    verification_note: Optional[str]


class Visitor(CommonFields):
    full_name: str
    home_state_code: str
    trained_through_year: int
    certifications: List[str]
    employer_camp_id: Optional[str]
    status: str
    committed_travel_days: int
    deactivated_reason: Optional[str]


class AccreditationVisit(CommonFields):
    cycle_id: str
    window_start_date: str
    window_end_date: str
    scheduled_note: Optional[str]
    status: str
    lead_visitor_id: Optional[str]
    team_size: int
    required_specialist_domains: List[str]
    mandatory_scored_count: int
    mandatory_met_count: int
    provisional_mandatory_pct: Optional[float]
    scheduled_by_user_id: Optional[str]
    scored_at: Optional[str]


class VisitAssignment(CommonFields):
    visit_id: str
    visitor_id: str
    team_role: str
    travel_block_start_date: str
    travel_block_end_date: str
    travel_days: int
    status: str
    withdrawal_reason: Optional[str]


class Deficiency(CommonFields):
    visit_id: str
    standard_id: str
    severity: str
    base_points: int
    penalty_points: int
    correction_due_date: str
    status: str
    plan_revision_count: int
    correction_plan_text: Optional[str]
    last_plan_submitted_at: Optional[str]
    reviewer_user_id: Optional[str]
    reviewer_note: Optional[str]


class MedicationAdministrationRecord(CommonFields):
    camp_id: str
    camper_reference: str
    medication_class: str
    dose_units: int
    administered_at: str
    administered_by_role: str
    second_signature_present: bool
    record_status: str
    compliance_flag: str
    void_reason: Optional[str]


class AnnualReport(CommonFields):
    camp_id: str
    report_year: int
    due_date: str
    status: str
    declared_incident_count: int
    disclosed_incident_count: int
    reopen_count: int
    submitted_at: Optional[str]
    attested_by_user_id: Optional[str]
    reviewer_note: Optional[str]


class IncidentDisclosure(CommonFields):
    annual_report_id: str
    incident_type: str
    occurred_at: str
    disclosed_at: str
    severity_weight: int
    state_notification_required: bool
    status: str
