"""Entity shapes and enum vocabularies for the API under test.

The TypedDicts mirror the representations described in the PRD. Two entities
(WellnessCheck and RiskAssessment) are immutable append-only events and carry
only `id` and `created_at` from the audit triple: they have no `updated_at`
and no `version`, and neither field appears in their representation.
"""

from typing import List, Optional, TypedDict

# --- Enum vocabularies -------------------------------------------------------

CLIENT_STATUSES = ("INTAKE", "ACTIVE", "EXITED")
CONFIDENTIALITY_POSTURES = ("NORMAL", "HEIGHTENED", "SEALED")
RISK_BANDS = ("IMMINENT", "ELEVATED", "MODERATE", "LOW")
HMIS_CONSENT_VALUES = ("GRANTED", "DENIED", "REVOKED")
CALLER_TYPES = ("SURVIVOR", "FAMILY_MEMBER", "PROFESSIONAL_REFERRAL")
HOTLINE_CALL_STATUSES = (
    "RECEIVED",
    "RISK_ASSESSED",
    "SCREENING_REFERRED",
    "SAFETY_PLAN_ONLY",
    "RESOURCE_REFERRED",
)
DISPOSITIONS = ("SCREENING_REFERRED", "SAFETY_PLAN_ONLY", "RESOURCE_REFERRED")
RISK_VARIANTS = ("INTAKE_SNAPSHOT", "CORROBORATED_REVIEW")
SAFETY_PLAN_STATUSES = ("DRAFT", "ACTIVE", "UNDER_REVISION", "ARCHIVED")
COMPONENT_TYPES = ("RELOCATION", "COMMUNICATION", "TECHNOLOGY", "WORKPLACE_NOTIFICATION")
COMPONENT_STATUSES = ("DRAFT", "IMPLEMENTED", "REVIEW_REQUIRED", "BLOCKED")
STAFF_ROLE_TYPES = (
    "HOTLINE_ADVOCATE",
    "SHELTER_MANAGER",
    "LEGAL_ADVOCATE",
    "HOUSING_SPECIALIST",
    "PRIVACY_OFFICER",
)
WELLNESS_POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
UNIT_TYPES = ("STANDARD", "FAMILY_SUITE", "ADA_ACCESSIBLE")
UNIT_STATUSES = ("AVAILABLE", "HOLD", "OCCUPIED")
CAPACITY_POSTURES = ("OPEN", "NEAR_CAPACITY", "FULL")
SCREENING_STATUSES = ("PENDING", "APPROVED", "WAITLISTED", "DENIED", "ADMITTED", "EXPIRED")
SCREENING_DECISIONS = ("APPROVE", "DENY", "WAITLIST")
OCCUPANCY_STATUSES = ("RESERVED", "CHECKED_IN", "EXITED", "CANCELLED")
LOCATION_SECURITY_STATUSES = ("SECURE", "COMPROMISED", "RELOCATED")
COMPROMISE_SOURCES = ("ABUSER_CONTACT", "DATA_BREACH", "COURT_FILING", "SOCIAL_MEDIA")
EXIT_DESTINATIONS = ("PERMANENT_HOUSING", "TRANSITIONAL_HOUSING", "FAMILY_FRIENDS", "UNKNOWN")
SCHOOL_ENROLLMENT_STATUSES = ("PENDING", "ENROLLED", "NOT_APPLICABLE")
ORDER_TYPES = ("EMERGENCY_EX_PARTE", "FULL_ORDER", "MODIFICATION")
PROTECTIVE_ORDER_STATUSES = ("PETITION_DRAFTED", "FILED", "GRANTED", "DENIED_FINAL")
ORDER_OUTCOMES = ("GRANTED", "DENIED")
SUBSIDY_TYPES = ("HOUSING_CHOICE_VOUCHER", "RAPID_REHOUSING_SUBSIDY", "NONE")
PROGRAM_TYPES = ("TRANSITIONAL_HOUSING", "RAPID_REHOUSING")
INCENTIVE_TIERS = ("BASE", "SILVER", "GOLD", "PLATINUM")
REFERRAL_STATUSES = ("SUBMITTED", "MATCHED", "LEASED", "REJECTED")
REJECTION_REASONS = ("SAFETY_PLAN_SUSPENDED", "LANDLORD_WITHDREW", "CLIENT_DECLINED")
DISCLOSURE_KINDS = ("PARTNER_AGENCY", "COURT_SUBPOENA", "HMIS_EXPORT", "MANDATED_REPORT")
DISCLOSURE_STATUSES = ("REQUESTED", "RELEASED", "PARTIALLY_RELEASED", "DENIED")
DISCLOSURE_DECISIONS = ("RELEASE", "DENY")


# --- Entity shapes -----------------------------------------------------------


class AuditTriple(TypedDict):
    """The standard audit triple carried by every living record (PRD 2.5)."""

    created_at: str
    updated_at: str
    version: int


class StaffMember(AuditTriple):
    id: str
    full_name: str
    role_type: str
    max_caseload: int
    active_caseload_count: int
    secondary_trauma_index: float
    wellness_posture: str
    last_wellness_check_at: Optional[str]


class WellnessCheck(TypedDict):
    """Immutable append-only event: only `id` and `created_at` (PRD 2.5)."""

    id: str
    created_at: str
    staff_member_id: str
    checked_on_utc: str
    exposure_hours: float
    distress_scale: int
    debrief_completed: bool
    contribution_points: float


class Client(AuditTriple):
    id: str
    client_code: str
    legal_name: str
    household_size: int
    minor_children_count: int
    accessibility_required: bool
    location_confidential: bool
    hmis_disclosure_consent: str
    status: str
    confidentiality_posture: str
    current_danger_score: Optional[float]
    current_risk_band: Optional[str]
    protective_order_active: bool
    resource_referral_count: int


class HotlineCall(AuditTriple):
    id: str
    client_id: str
    caller_type: str
    presenting_concerns: str
    taken_by_staff_id: str
    received_at_utc: str
    status: str
    disposed_at: Optional[str]


class RiskAssessment(TypedDict):
    """Immutable append-only event: only `id` and `created_at` (PRD 2.5)."""

    id: str
    created_at: str
    hotline_call_id: str
    weapon_access: bool
    strangulation_history: bool
    separation_recent: bool
    threats_to_kill: bool
    stalking_frequency_per_week: int
    corroborate_with_history: bool
    variant_applied: str
    corroborating_fact_count: int
    base_subtotal: float
    escalation_multiplier: float
    danger_score: float
    risk_band: str


class SafetyPlan(AuditTriple):
    id: str
    client_id: str
    based_on_risk_assessment_id: str
    authored_by_staff_id: str
    status: str
    coverage_score: float
    revision_count: int
    superseded_by_plan_id: Optional[str]
    archived_at: Optional[str]


class PlanComponent(AuditTriple):
    id: str
    safety_plan_id: str
    component_type: str
    detail: str
    target_completion_date: str
    status: str
    weight_effective: float
    subscore: float


class Shelter(AuditTriple):
    id: str
    name: str
    confidential_location: bool
    nightly_rate_cents: int
    weekend_surcharge_cents: int
    child_supplement_cents: int
    total_bed_capacity: int
    available_beds: int
    capacity_posture: str
    settled_revenue_cents: int


class ShelterUnit(AuditTriple):
    id: str
    shelter_id: str
    unit_label: str
    unit_type: str
    bed_capacity: int
    reserved_beds: int
    occupied_beds: int
    available_beds: int
    status: str


class ScreeningRequest(AuditTriple):
    id: str
    client_id: str
    hotline_call_id: str
    requested_shelter_id: str
    requested_entry_date: str
    household_size: int
    minor_children_count: int
    accessibility_required: bool
    created_by_staff_id: str
    assigned_advocate_id: Optional[str]
    offered_shelter_unit_id: Optional[str]
    waitlist_position: Optional[int]
    promoted_from_waitlist: bool
    denial_reason: Optional[str]
    status: str
    decided_at: Optional[str]


class ShelterAdmission(AuditTriple):
    id: str
    screening_request_id: str
    client_id: str
    shelter_unit_id: str
    shelter_id: str
    prior_unit_id: Optional[str]
    household_size: int
    minor_children_count: int
    entry_date: str
    planned_exit_date: str
    actual_exit_date: Optional[str]
    occupancy_status: str
    location_security_status: str
    compromise_source: Optional[str]
    projected_stay_cost_cents: int
    settled_stay_cost_cents: Optional[int]
    exit_destination: Optional[str]
    cancel_reason: Optional[str]
    school_enrollment_status: str


class ProtectiveOrderCase(AuditTriple):
    id: str
    client_id: str
    order_type: str
    status: str
    refile_count: int
    filed_court: Optional[str]
    hearing_start_utc: Optional[str]
    hearing_end_utc: Optional[str]
    accompanying_advocate_id: Optional[str]
    outcome_recorded_at: Optional[str]


class LandlordPartner(AuditTriple):
    id: str
    name: str
    units_pledged: int
    accepts_subsidy_type: str
    base_incentive_cents: int
    units_committed: int
    units_available: int
    engagement_score: float
    incentive_tier: str
    incentive_accrued_cents: int


class HousingReferral(AuditTriple):
    id: str
    client_id: str
    landlord_partner_id: str
    program_type: str
    subsidy_type: str
    created_by_staff_id: str
    status: str
    monthly_rent_cents: Optional[int]
    incentive_fee_cents: Optional[int]
    incentive_tier_applied: Optional[str]
    rejection_reason: Optional[str]
    lease_start_date: Optional[str]
    withdraw_count: int


class DisclosureEvent(AuditTriple):
    id: str
    client_id: str
    requested_by_staff_id: str
    kind: str
    requester_org: str
    requested_field_keys: List[str]
    released_field_keys: List[str]
    suppressed_field_keys: List[str]
    roi_signed_on: Optional[str]
    roi_expires_on: Optional[str]
    decision_deadline_utc: Optional[str]
    decided_by_staff_id: Optional[str]
    decided_at: Optional[str]
    late_filed: bool
    status: str
