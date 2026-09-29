"""Domain types for the Correspondent Banking Due Diligence API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    RESPONDENT_CONTACT = "RespondentContact"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    SANCTIONS_OFFICER = "SanctionsOfficer"
    FIG_RELATIONSHIP_MANAGER = "FIGRelationshipManager"
    COMMITTEE_APPROVER = "CommitteeApprover"
    PLATFORM_ADMIN = "PlatformAdmin"


ALL_ROLES = [r.value for r in UserRole]
OPERATOR_ROLES = [
    "ComplianceAnalyst",
    "SanctionsOfficer",
    "FIGRelationshipManager",
    "CommitteeApprover",
    "PlatformAdmin",
]


class SanctionsStatus(str, Enum):
    PERMITTED = "PERMITTED"
    RESTRICTED = "RESTRICTED"
    COMPREHENSIVELY_SANCTIONED = "COMPREHENSIVELY_SANCTIONED"


class FatfListing(str, Enum):
    NONE = "NONE"
    INCREASED_MONITORING = "INCREASED_MONITORING"
    CALL_FOR_ACTION = "CALL_FOR_ACTION"


class RiskRating(str, Enum):
    UNRATED = "UNRATED"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    PROHIBITED = "PROHIBITED"


class DdState(str, Enum):
    PROSPECT = "PROSPECT"
    DD_IN_PROGRESS = "DD_IN_PROGRESS"
    PENDING_COMMITTEE = "PENDING_COMMITTEE"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    RESTRICTED = "RESTRICTED"
    REFRESH_DUE = "REFRESH_DUE"
    UNDER_REFRESH = "UNDER_REFRESH"
    REFRESH_OVERDUE = "REFRESH_OVERDUE"
    EXITING = "EXITING"
    TERMINATED = "TERMINATED"


class PaymentPosture(str, Enum):
    BLOCKED = "BLOCKED"
    SCREEN_ONLY = "SCREEN_ONLY"
    OPEN = "OPEN"
    WIND_DOWN_ONLY = "WIND_DOWN_ONLY"


class LicenseStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    ACTIVE = "ACTIVE"
    CONDITIONAL = "CONDITIONAL"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class RegulatorStanding(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    GOOD_STANDING = "GOOD_STANDING"
    UNDER_ENFORCEMENT = "UNDER_ENFORCEMENT"
    DEREGISTERED = "DEREGISTERED"


class RestrictionReason(str, Enum):
    UNRESPONSIVE_STRIKES = "UNRESPONSIVE_STRIKES"
    ADVERSE_MEDIA = "ADVERSE_MEDIA"
    SANCTIONS_EXPOSURE = "SANCTIONS_EXPOSURE"
    PROHIBITED_NESTING = "PROHIBITED_NESTING"
    REFRESH_LAPSED = "REFRESH_LAPSED"
    LICENSE_LAPSE = "LICENSE_LAPSE"
    OFFICER_ACTION = "OFFICER_ACTION"


class OwnerVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class OwnerType(str, Enum):
    NATURAL_PERSON = "NATURAL_PERSON"
    LEGAL_ENTITY = "LEGAL_ENTITY"
    STATE = "STATE"


class QuestionnaireState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_ASSESSMENT = "UNDER_ASSESSMENT"
    RETURNED_FOR_CLARIFICATION = "RETURNED_FOR_CLARIFICATION"
    ASSESSED = "ASSESSED"
    SUPERSEDED = "SUPERSEDED"


class ControlDomain(str, Enum):
    GOVERNANCE = "GOVERNANCE"
    KYC_ONBOARDING = "KYC_ONBOARDING"
    TRANSACTION_MONITORING = "TRANSACTION_MONITORING"
    SANCTIONS_SCREENING = "SANCTIONS_SCREENING"
    PEP_HANDLING = "PEP_HANDLING"
    TRAINING = "TRAINING"
    AUDIT = "AUDIT"
    NESTED_CONTROLS = "NESTED_CONTROLS"


class GapSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class NestedState(str, Enum):
    DISCLOSED = "DISCLOSED"
    UNDISCLOSED_DETECTED = "UNDISCLOSED_DETECTED"
    CONFIRMED = "CONFIRMED"
    SUSPENDED = "SUSPENDED"
    PROHIBITED = "PROHIBITED"
    TERMINATED = "TERMINATED"


class RelationshipType(str, Enum):
    DOWNSTREAM_CORRESPONDENT = "DOWNSTREAM_CORRESPONDENT"
    PAYABLE_THROUGH = "PAYABLE_THROUGH"
    NESTED_PSP = "NESTED_PSP"


class DiscoverySource(str, Enum):
    QUESTIONNAIRE = "QUESTIONNAIRE"
    TRANSACTION_MONITORING = "TRANSACTION_MONITORING"
    RFI = "RFI"
    ADVERSE_MEDIA = "ADVERSE_MEDIA"


class ProhibitionReason(str, Enum):
    CYCLE = "CYCLE"
    SANCTIONED_JURISDICTION = "SANCTIONED_JURISDICTION"
    JURISDICTION_PROHIBITS_NESTING = "JURISDICTION_PROHIBITS_NESTING"
    DEPTH_EXCEEDED = "DEPTH_EXCEEDED"
    PAYABLE_THROUGH_NOT_PERMITTED = "PAYABLE_THROUGH_NOT_PERMITTED"


class CalibrationState(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CALIBRATED = "CALIBRATED"
    RECALIBRATION_REQUIRED = "RECALIBRATION_REQUIRED"
    SUPERSEDED = "SUPERSEDED"


class RecalibrationReason(str, Enum):
    OFFICER_ACTION = "OFFICER_ACTION"
    NESTED_DISCOVERY = "NESTED_DISCOVERY"
    ALERT_ESCALATION = "ALERT_ESCALATION"
    REFRESH_COMPLETION = "REFRESH_COMPLETION"


class AlertType(str, Enum):
    VOLUME_BREACH = "VOLUME_BREACH"
    COUNT_BREACH = "COUNT_BREACH"
    CORRIDOR_UNEXPECTED = "CORRIDOR_UNEXPECTED"
    NESTED_ACTIVITY_UNDISCLOSED = "NESTED_ACTIVITY_UNDISCLOSED"


class AlertSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertState(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    ESCALATED = "ESCALATED"
    CLOSED_FALSE_POSITIVE = "CLOSED_FALSE_POSITIVE"
    CLOSED_CONFIRMED = "CLOSED_CONFIRMED"


class RfiState(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    RESPONDED = "RESPONDED"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    ACCEPTED = "ACCEPTED"
    ABANDONED = "ABANDONED"


class RequestTopic(str, Enum):
    OWNERSHIP_EVIDENCE = "OWNERSHIP_EVIDENCE"
    LICENSING_EVIDENCE = "LICENSING_EVIDENCE"
    NESTED_DISCLOSURE = "NESTED_DISCLOSURE"
    ACTIVITY_EXPLANATION = "ACTIVITY_EXPLANATION"
    CONTROL_REMEDIATION = "CONTROL_REMEDIATION"


class MediaState(str, Enum):
    NEW = "NEW"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class MediaCategory(str, Enum):
    SANCTIONS_EVASION = "SANCTIONS_EVASION"
    MONEY_LAUNDERING = "MONEY_LAUNDERING"
    FRAUD = "FRAUD"
    REGULATORY_ACTION = "REGULATORY_ACTION"
    LITIGATION = "LITIGATION"
    OTHER = "OTHER"


class RefreshState(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class TriggerReason(str, Enum):
    CADENCE = "CADENCE"
    ADVERSE_MEDIA = "ADVERSE_MEDIA"
    ALERT_ESCALATION = "ALERT_ESCALATION"
    NESTED_DISCOVERY = "NESTED_DISCOVERY"
    REGULATOR_ACTION = "REGULATOR_ACTION"


class ScreeningState(str, Enum):
    RECEIVED = "RECEIVED"
    SCREENED_CLEAR = "SCREENED_CLEAR"
    HELD_FOR_REVIEW = "HELD_FOR_REVIEW"
    BLOCKED_SANCTIONS = "BLOCKED_SANCTIONS"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class HoldReason(str, Enum):
    SANCTIONS_RESTRICTED_JURISDICTION = "SANCTIONS_RESTRICTED_JURISDICTION"
    POSTURE_SCREEN_ONLY = "POSTURE_SCREEN_ONLY"
    UNDISCLOSED_NESTED_PARTY = "UNDISCLOSED_NESTED_PARTY"
    AMOUNT_THRESHOLD = "AMOUNT_THRESHOLD"


class PurposeCode(str, Enum):
    TRADE_SETTLEMENT = "TRADE_SETTLEMENT"
    REMITTANCE = "REMITTANCE"
    INTERBANK_PLACEMENT = "INTERBANK_PLACEMENT"
    RETURN_OF_FUNDS = "RETURN_OF_FUNDS"
    SETTLEMENT = "SETTLEMENT"


class ClosureState(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    NOTICE_SERVED = "NOTICE_SERVED"
    WIND_DOWN = "WIND_DOWN"
    CLOSED = "CLOSED"
    ABORTED = "ABORTED"


class TerminationReason(str, Enum):
    UNRESPONSIVE = "UNRESPONSIVE"
    SANCTIONS_EXPOSURE = "SANCTIONS_EXPOSURE"
    PROHIBITED_NESTING = "PROHIBITED_NESTING"
    RISK_APPETITE = "RISK_APPETITE"
    COMMERCIAL = "COMMERCIAL"
    REGULATORY_ACTION = "REGULATORY_ACTION"


class CapBasis(str, Enum):
    NONE = "NONE"
    FORWARD_PROJECTED = "FORWARD_PROJECTED"
    CHRONOLOGICAL_ACTUAL = "CHRONOLOGICAL_ACTUAL"


# --- Entity shapes.  Every persisted resource carries id/created_at/
# --- updated_at/version, per the common resource properties of the PRD.


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class JurisdictionProfile(CommonFields):
    jurisdiction_code: str
    name: str
    sanctions_status: str
    fatf_listing: str
    basel_aml_index: float
    secrecy_flag: bool
    corridor_risk_weight: float
    nested_correspondent_prohibited: bool
    max_permitted_risk_rating: str
    jurisdiction_risk_points: float


class RespondentBank(CommonFields):
    legal_name: str
    swift_bic: str
    home_jurisdiction_code: str
    relationship_manager_user_id: str
    dd_state: str
    payment_posture: str
    license_status: str
    regulator_name: Optional[str]
    regulator_standing: str
    license_verified_at: Optional[str]
    expected_monthly_volume_usd: float
    expected_monthly_count: int
    nested_activity_permitted: bool
    verified_ownership_pct: float
    control_chain_complete: bool
    ownership_verified: bool
    disclosed_nested_count: int
    undisclosed_nested_count: int
    max_nested_depth: int
    nested_exposure_units: int
    inherent_risk_score: float
    control_score: float
    control_credit: float
    adverse_media_uplift: float
    residual_risk_score: float
    risk_rating: str
    risk_assessment_variant: str
    assessed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    approved_risk_rating: str
    last_approved_at: Optional[str]
    refresh_due_date: Optional[str]
    unresponsive_strikes: int
    escalation_units: int
    restriction_reason: Optional[str]
    last_risk_assessed_at: Optional[str]


class BeneficialOwner(CommonFields):
    respondent_bank_id: str
    parent_owner_id: Optional[str]
    owner_name: str
    owner_type: str
    ownership_pct: float
    country_of_residence: str
    is_pep: bool
    chain_depth: int
    effective_ownership_pct: float
    verification_status: str
    verified_by_user_id: Optional[str]
    rejection_reason: Optional[str]


class DueDiligenceQuestionnaire(CommonFields):
    respondent_bank_id: str
    questionnaire_version: str
    state: str
    submitted_at: Optional[str]
    assessed_at: Optional[str]
    assessed_by_user_id: Optional[str]
    clarification_rounds: int
    declared_nested_activity: bool
    declared_downstream_count: int
    computed_control_score: Optional[float]
    control_score_variant: str


class ControlAssessment(CommonFields):
    questionnaire_id: str
    control_domain: str
    self_rating: int
    assessed_rating: Optional[int]
    domain_weight: float
    gap_severity: str
    remediation_required: bool
    evidence_note: str


class NestedRelationship(CommonFields):
    respondent_bank_id: str
    downstream_respondent_bank_id: Optional[str]
    downstream_institution_name: str
    downstream_jurisdiction_code: str
    relationship_type: str
    discovery_source: str
    state: str
    depth: int
    prohibition_reason: Optional[str]
    adjudicated_by_user_id: Optional[str]
    adjudicated_at: Optional[str]


class TransactionMonitoringProfile(CommonFields):
    respondent_bank_id: str
    effective_from: str
    effective_to: str
    tolerance_pct: float
    expected_corridors: List[dict]
    calibration_state: str
    corridor_thresholds: List[dict]
    aggregate_usd_threshold: Optional[float]
    hold_threshold_usd: Optional[float]
    calibrated_at: Optional[str]
    calibrated_by_user_id: Optional[str]
    recalibration_reason: Optional[str]


class ActivityObservation(CommonFields):
    monitoring_profile_id: str
    period_month: str
    corridor_jurisdiction_code: str
    aggregate_usd: float
    txn_count: int
    distinct_downstream_count: int
    usd_threshold_applied: float
    count_threshold_applied: int
    breach_ratio: Optional[float]
    alerts_created_count: int


class MonitoringAlert(CommonFields):
    respondent_bank_id: str
    activity_observation_id: Optional[str]
    alert_type: str
    severity: str
    state: str
    breach_ratio: Optional[float]
    investigated_by_user_id: Optional[str]
    disposition_reason: Optional[str]
    escalated_at: Optional[str]


class InformationRequest(CommonFields):
    respondent_bank_id: str
    monitoring_alert_id: Optional[str]
    request_topic: str
    severity: str
    state: str
    dispatched_at: Optional[str]
    sla_hours: Optional[int]
    due_at: Optional[str]
    escalation_level: int
    reminder_count: int
    insufficiency_rounds: int
    responded_at: Optional[str]
    response_note: str
    adjudicated_by_user_id: Optional[str]
    retro_credited: bool


class AdverseMediaEvent(CommonFields):
    respondent_bank_id: str
    headline: str
    category: str
    severity_tier: str
    source_reliability: str
    event_date: str
    adjudication_state: str
    uplift_points: float
    triaged_by_user_id: Optional[str]
    triaged_at: Optional[str]


class PeriodicRefresh(CommonFields):
    respondent_bank_id: str
    trigger_reason: str
    window_start: str
    scheduled_due_date: str
    state: str
    cadence_months_applied: int
    rating_at_schedule: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    lapsed_at: Optional[str]
    completed_control_score: Optional[float]
    completion_risk_rating: Optional[str]
    cancelled_reason: Optional[str]


class PaymentInstruction(CommonFields):
    respondent_bank_id: str
    nested_relationship_id: Optional[str]
    ordering_jurisdiction_code: str
    beneficiary_jurisdiction_code: str
    amount_usd: float
    purpose_code: str
    involves_nested_party: bool
    screening_state: str
    hold_reason: Optional[str]
    hold_threshold_applied: Optional[float]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    decision_reason: Optional[str]


class ClosurePlan(CommonFields):
    respondent_bank_id: str
    termination_reason: str
    state: str
    cap_basis: str
    notice_period_days: int
    notice_served_at: Optional[str]
    wind_down_end_at: Optional[str]
    wind_down_cap_usd: Optional[float]
    wind_down_released_usd: float
    original_obligation_cents: int
    outstanding_obligation_cents: int
    settled_cents: int
    last_allocated_cents: int
    allocation_round: int
    allocation_lines: List[dict]
    return_rounds: int
    drafted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    closed_at: Optional[str]
    abort_reason: Optional[str]
