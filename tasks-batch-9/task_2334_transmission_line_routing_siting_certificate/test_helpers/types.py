"""Entity TypedDicts, state enums and role names for the Transmission Siting API.

Every persisted resource in this API carries the four common properties
described in PRD §2.4 — ``id``, ``created_at``, ``updated_at`` and ``version`` —
so every entity TypedDict below extends :class:`CommonFields`.
"""

from __future__ import annotations

from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole:
    """The seven role names accepted in the ``X-User-Role`` header."""

    DEVELOPER = "Developer"
    ROUTE_ANALYST = "RouteAnalyst"
    COMMISSION_STAFF = "CommissionStaff"
    HEARING_EXAMINER = "HearingExaminer"
    LANDOWNER = "Landowner"
    FEDERAL_PERMIT_OFFICER = "FederalPermitOfficer"
    COMPLIANCE_MONITOR = "ComplianceMonitor"

    ALL = (
        DEVELOPER,
        ROUTE_ANALYST,
        COMMISSION_STAFF,
        HEARING_EXAMINER,
        LANDOWNER,
        FEDERAL_PERMIT_OFFICER,
        COMPLIANCE_MONITOR,
    )


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class VoltageClass:
    KV_138 = "KV_138"
    KV_345 = "KV_345"
    KV_500 = "KV_500"


class ProjectStage:
    PLANNING = "PLANNING"
    ROUTING = "ROUTING"
    APPLICATION_FILED = "APPLICATION_FILED"
    CERTIFICATED = "CERTIFICATED"
    CONSTRUCTION = "CONSTRUCTION"
    ENERGIZED = "ENERGIZED"


class SchedulePosture:
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    CRITICAL = "CRITICAL"


class StudyStatus:
    DRAFT = "DRAFT"
    ALTERNATIVES_ANALYZED = "ALTERNATIVES_ANALYZED"
    CERTIFIED_SUFFICIENT = "CERTIFIED_SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


class AlternativeKind:
    TRANSMISSION = "TRANSMISSION"
    NON_TRANSMISSION = "NON_TRANSMISSION"
    HYBRID = "HYBRID"


class ScreeningStatus:
    SUBMITTED = "SUBMITTED"
    SCREENED_IN = "SCREENED_IN"
    SCREENED_OUT = "SCREENED_OUT"


class ScreeningDecision:
    SCREEN_IN = "SCREEN_IN"
    SCREEN_OUT = "SCREEN_OUT"


class RouteKind:
    PROPOSED = "PROPOSED"
    ALTERNATE = "ALTERNATE"


class RouteStatus:
    DRAFT = "DRAFT"
    CONSTRAINT_MAPPED = "CONSTRAINT_MAPPED"
    PUBLISHED_FOR_COMMENT = "PUBLISHED_FOR_COMMENT"
    REFINING = "REFINING"
    NOMINATED = "NOMINATED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class SurveyStatus:
    DESKTOP = "DESKTOP"
    FIELD_VERIFIED = "FIELD_VERIFIED"


class FederalCrossingKind:
    NONE = "NONE"
    PUBLIC_LAND = "PUBLIC_LAND"
    NAVIGABLE_WATERWAY = "NAVIGABLE_WATERWAY"
    WETLAND = "WETLAND"


class FederalPermitStatus:
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"


class FederalPermitAction:
    APPLY = "APPLY"
    ISSUE = "ISSUE"
    DENY = "DENY"


class FederalAgency:
    BLM = "BLM"
    USACE = "USACE"
    USFS = "USFS"


class ConstructionState:
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"
    COMPLETE = "COMPLETE"


class CommenterKind:
    LANDOWNER = "LANDOWNER"
    AGENCY = "AGENCY"
    PUBLIC = "PUBLIC"


class Materiality:
    MATERIAL = "MATERIAL"
    GENERAL = "GENERAL"


class CommentStatus:
    RECEIVED = "RECEIVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INCORPORATED = "INCORPORATED"
    DISMISSED = "DISMISSED"


class CommentDisposition:
    ACKNOWLEDGE = "ACKNOWLEDGE"
    DISMISS = "DISMISS"


class ReviewStatus:
    FILED = "FILED"
    DEFICIENT = "DEFICIENT"
    ACCEPTED = "ACCEPTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class RecordStatus:
    NOT_OPENED = "NOT_OPENED"
    SCHEDULING = "SCHEDULING"
    EVIDENTIARY_REQUIRED = "EVIDENTIARY_REQUIRED"
    RECORD_OPEN = "RECORD_OPEN"
    RECORD_CLOSED = "RECORD_CLOSED"


class ReviewOutcome:
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class SessionKind:
    PREHEARING = "PREHEARING"
    EVIDENTIARY = "EVIDENTIARY"
    PUBLIC_TESTIMONY = "PUBLIC_TESTIMONY"


class SessionStatus:
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"


class PetitionerKind:
    LANDOWNER = "LANDOWNER"
    INTEREST_GROUP = "INTEREST_GROUP"


class InterventionStatus:
    PETITIONED = "PETITIONED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class Ruling:
    GRANT = "GRANT"
    DENY = "DENY"


class DecisionOutcome:
    GRANT = "GRANT"
    DENY = "DENY"


class CertificateStatus:
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"


class CertificatePosture:
    ACTIVE = "ACTIVE"
    STOP_WORK = "STOP_WORK"
    REVOKED = "REVOKED"


class EscrowTier:
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ConditionCategory:
    ENVIRONMENTAL = "ENVIRONMENTAL"
    CULTURAL = "CULTURAL"
    LAND_USE = "LAND_USE"
    ENGINEERING = "ENGINEERING"
    PUBLIC_SAFETY = "PUBLIC_SAFETY"


class ConstraintKind:
    SEASONAL_BLACKOUT = "SEASONAL_BLACKOUT"
    CREW_LIMIT = "CREW_LIMIT"
    NOTICE = "NOTICE"
    MONITORING = "MONITORING"


class ConditionStatus:
    ACTIVE = "ACTIVE"
    VIOLATED = "VIOLATED"
    WAIVED = "WAIVED"


class AcquisitionStatus:
    NOT_STARTED = "NOT_STARTED"
    OFFERED = "OFFERED"
    AGREED = "AGREED"
    REJECTED = "REJECTED"
    CONDEMNATION_FILED = "CONDEMNATION_FILED"
    AWARDED = "AWARDED"


class PaymentStatus:
    UNPAID = "UNPAID"
    PAID = "PAID"
    RESCINDED = "RESCINDED"


class OfferResponse:
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class ActivityKind:
    CLEARING = "CLEARING"
    FOUNDATION = "FOUNDATION"
    STRINGING = "STRINGING"


class ActivityStatus:
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class SuspensionReason:
    FEDERAL_PERMIT_DENIED = "FEDERAL_PERMIT_DENIED"
    CERTIFICATE_STOP_WORK = "CERTIFICATE_STOP_WORK"


class Severity:
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class NonconformanceStatus:
    OPEN = "OPEN"
    CORRECTED = "CORRECTED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Entity shapes (PRD §2.4: all fifteen entities carry all four common fields)
# ---------------------------------------------------------------------------


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Project(CommonFields, total=False):
    name: str
    voltage_class: str
    jurisdiction_state: str
    target_energization_at: str
    stage: str
    schedule_posture: str
    right_of_way_hold: bool
    escrow_funded_cents: int
    escrow_balance_cents: int
    escrow_disbursed_cents: int
    easement_committed_cents: int


class PlanningStudy(CommonFields, total=False):
    project_id: str
    horizon_year: int
    reliability_deficit_mw: float
    transmission_capex_cents: int
    benefit_pv_cents: int
    status: str
    authored_by_user_id: str
    certified_by_user_id: Optional[str]
    transmission_levelized_cents_per_mw: Optional[float]
    benefit_ratio: Optional[float]
    need_margin_ratio: Optional[float]
    selected_nta_alternative_id: Optional[str]
    alternatives_screened_in_count: int


class Alternative(CommonFields, total=False):
    study_id: str
    kind: str
    description: str
    capex_cents: int
    deliverable_mw: float
    levelized_cost_cents_per_mw: float
    screening_status: str
    screen_reason: Optional[str]


class Route(CommonFields, total=False):
    project_id: str
    label: str
    kind: str
    status: str
    segment_count: int
    total_miles: float
    unsurveyed_segment_count: int
    constraint_score_preliminary: Optional[float]
    constraint_score_certified: Optional[float]
    constraint_density_certified: Optional[float]
    comment_window_closes_at: Optional[str]
    open_house_held_count: int
    open_house_counties: List[str]
    refinement_round: int
    refinement_target_segment_id: Optional[str]


class RouteSegment(CommonFields, total=False):
    route_id: str
    sequence_index: int
    miles: float
    county: str
    crew_capacity: int
    land_use_rating: int
    environmental_rating: int
    cultural_rating: int
    engineering_rating: int
    survey_status: str
    habitat_blackout: bool
    federal_crossing_kind: str
    federal_permit_status: str
    federal_permit_agency: Optional[str]
    construction_state: str
    committed_crew_count: int
    material_comment_count: int
    refinement_count: int


class PublicComment(CommonFields, total=False):
    route_id: str
    segment_id: Optional[str]
    commenter_kind: str
    commenter_name: str
    commenter_landowner_id: Optional[str]
    body: str
    materiality: str
    status: str
    disposition_note: Optional[str]
    received_at: str


class SitingApplication(CommonFields, total=False):
    project_id: str
    study_id: str
    proposed_route_id: str
    docket_number: str
    filing_fee_cents: int
    review_status: str
    record_status: str
    alternate_route_ids: List[str]
    party_count: int
    suspension_days: int
    amendment_round: int
    deficiency_note: Optional[str]
    filed_at: str
    filed_by_user_id: str
    decision_deadline_at: str


class HearingSession(CommonFields, total=False):
    application_id: str
    kind: str
    window_start_at: str
    window_end_at: str
    status: str
    exhibits_admitted_count: int
    presiding_user_id: str


class Intervention(CommonFields, total=False):
    application_id: str
    petitioner_kind: str
    grounds: str
    landowner_id: Optional[str]
    organization_name: Optional[str]
    status: str
    ruling_reason: Optional[str]
    ruled_by_user_id: Optional[str]
    filed_at: str


class Certificate(CommonFields, total=False):
    application_id: str
    certified_route_id: str
    status: str
    posture: str
    eminent_domain_authorized: bool
    mitigation_base_cents: int
    escrow_tier: str
    contingency_cents: int
    condition_surcharge_cents: int
    escrow_required_cents: int
    compliance_index_rolling: float
    compliance_index_cumulative: float
    issued_by_user_id: str
    issued_at: str


class CertificateCondition(CommonFields, total=False):
    certificate_id: str
    code: str
    category: str
    constraint_kind: str
    severity_weight: int
    blackout_start_mmdd: Optional[str]
    blackout_end_mmdd: Optional[str]
    crew_limit: Optional[int]
    status: str
    waiver_reason: Optional[str]


class Landowner(CommonFields, total=False):
    name: str
    email: str
    mailing_address: str


class EasementTract(CommonFields, total=False):
    project_id: str
    segment_id: str
    landowner_id: str
    parcel_number: str
    acres: float
    per_acre_value_cents: int
    easement_factor: float
    structure_damages_cents: int
    before_value_cents: int
    after_value_cents: int
    severance_damages_cents: int
    acquisition_status: str
    payment_status: str
    offer_round: int
    offered_compensation_cents: Optional[int]
    agreed_compensation_cents: Optional[int]
    award_cents: Optional[int]
    committed_cents: int
    paid_amount_cents: int
    paid_at: Optional[str]
    court_docket_number: Optional[str]
    deposit_cents: Optional[int]


class ConstructionActivity(CommonFields, total=False):
    certificate_id: str
    segment_id: str
    activity_kind: str
    crew_count: int
    window_start_at: str
    window_end_at: str
    status: str
    suspension_reason: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]


class Nonconformance(CommonFields, total=False):
    certificate_id: str
    condition_id: str
    activity_id: Optional[str]
    severity: str
    observation: str
    status: str
    deduction_points: float
    corrective_action: Optional[str]
    observed_at: str
