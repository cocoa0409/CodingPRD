"""Domain types for the Unscripted Casting & Participant Agreements API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.  Two record types — negotiation rounds and incidental releases — are
append-only evidence and therefore carry only ``id`` and ``created_at`` (PRD
§2.4); their TypedDicts deliberately omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------- role enum


class UserRole(str, Enum):
    PRODUCTION_ADMIN = "ProductionAdmin"
    CASTING_DIRECTOR = "CastingDirector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BUSINESS_AFFAIRS = "BusinessAffairs"
    WELFARE_OFFICER = "WelfareOfficer"
    APPLICANT = "Applicant"


# ------------------------------------------------------------- enumerations


class FormatType(str, Enum):
    COMPETITION_HIGH_STRESS = "COMPETITION_HIGH_STRESS"
    DOCUSOAP = "DOCUSOAP"
    DATING_FORMAT = "DATING_FORMAT"
    TALENT_SEARCH = "TALENT_SEARCH"


class JurisdictionCode(str, Enum):
    CA = "CA"
    NY = "NY"
    GA = "GA"
    IL = "IL"


class DutyOfCareTier(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"
    CRITICAL = "CRITICAL"


class CastingPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class CastingCallStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class CastingCallChannel(str, Enum):
    OPEN_CALL = "OPEN_CALL"
    DIGITAL_SUBMISSION = "DIGITAL_SUBMISSION"
    REFERRAL = "REFERRAL"


class ClosedReason(str, Enum):
    DIRECTOR_CLOSED = "DIRECTOR_CLOSED"
    POSTURE_RESTRICTED = "POSTURE_RESTRICTED"
    POSTURE_FROZEN = "POSTURE_FROZEN"


class ScreeningStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    CAST = "CAST"


class MedicalStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    DEFERRED = "DEFERRED"
    EXPIRED = "EXPIRED"


class ScreeningItemKind(str, Enum):
    INTERVIEW = "INTERVIEW"
    BACKGROUND_CHECK = "BACKGROUND_CHECK"
    PSYCH_EVAL = "PSYCH_EVAL"
    MEDICAL_EXAM = "MEDICAL_EXAM"


class ScreeningOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class MinorProtectionStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    COMPLETE = "COMPLETE"
    LAPSED = "LAPSED"
    RELEASED = "RELEASED"


class AgreementStatus(str, Enum):
    DRAFTED = "DRAFTED"
    SENT = "SENT"
    COUNTERED = "COUNTERED"
    REVISED = "REVISED"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class ConfidentialityTier(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"
    PERPETUAL = "PERPETUAL"


class DepictionRightsScope(str, Enum):
    FULL = "FULL"
    LIMITED = "LIMITED"
    PSEUDONYMIZED = "PSEUDONYMIZED"


class StipendStructure(str, Enum):
    FLAT = "FLAT"
    PER_EPISODE = "PER_EPISODE"
    TIERED = "TIERED"


class VoidReason(str, Enum):
    WELFARE_BREACH = "WELFARE_BREACH"
    APPLICANT_WITHDRAWN = "APPLICANT_WITHDRAWN"
    BUSINESS_AFFAIRS_VOID = "BUSINESS_AFFAIRS_VOID"
    SUPERSEDED = "SUPERSEDED"


class ProposedBy(str, Enum):
    PRODUCTION = "PRODUCTION"
    PARTICIPANT = "PARTICIPANT"


class RoundDisposition(str, Enum):
    COUNTERED = "COUNTERED"
    REVISED = "REVISED"


class WelfareProtocolKind(str, Enum):
    DUTY_OF_CARE_OFFICER = "DUTY_OF_CARE_OFFICER"
    ONSET_PSYCH_SUPPORT = "ONSET_PSYCH_SUPPORT"
    INSURANCE_RIDER = "INSURANCE_RIDER"
    AFTERCARE_PROGRAM = "AFTERCARE_PROGRAM"


class WelfareProtocolStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class BlockKind(str, Enum):
    STUDIO = "STUDIO"
    LOCATION_EXTERIOR = "LOCATION_EXTERIOR"
    PUBLIC_SPACE = "PUBLIC_SPACE"


class ShootBlockStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ROLLING = "ROLLING"
    WRAPPED = "WRAPPED"
    CANCELLED = "CANCELLED"


class ReleaseSubjectKind(str, Enum):
    INCIDENTAL_CROWD = "INCIDENTAL_CROWD"
    BYSTANDER_IDENTIFIABLE = "BYSTANDER_IDENTIFIABLE"
    PROPERTY_OWNER = "PROPERTY_OWNER"
    MINOR_INCIDENTAL = "MINOR_INCIDENTAL"


class ReleaseDisposition(str, Enum):
    COLLECTED = "COLLECTED"
    REFUSED = "REFUSED"
    BLURRED_WAIVER = "BLURRED_WAIVER"


class PostObligationKind(str, Enum):
    PRESS_JUNKET = "PRESS_JUNKET"
    REUNION_TAPING = "REUNION_TAPING"


class PostObligationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FULFILLED = "FULFILLED"
    EXCUSED = "EXCUSED"
    BREACHED = "BREACHED"


class ComplaintCategory(str, Enum):
    WELFARE = "WELFARE"
    MISREPRESENTATION = "MISREPRESENTATION"
    HARASSMENT = "HARASSMENT"
    PAYMENT = "PAYMENT"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    AFTERCARE_ACTIVE = "AFTERCARE_ACTIVE"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class ComplaintRoute(str, Enum):
    AFTERCARE = "AFTERCARE"
    ESCALATION = "ESCALATION"


# ------------------------------------------------------------ entity shapes
# Records that carry id + created_at + updated_at + version (PRD §2.4).


class Production(TypedDict):
    id: str
    title: str
    format_type: str
    jurisdiction_code: str
    season_number: int
    episode_order: int
    photography_start_utc: str
    photography_end_utc: str
    stipend_pool_cents: int
    stipend_committed_cents: int
    welfare_budget_cents: int
    welfare_committed_cents: int
    trust_escrow_balance_cents: int
    duty_of_care_tier: str
    welfare_incident_count: int
    breached_obligation_count: int
    casting_posture: str
    minor_participant_cap: int
    minor_participant_count: int
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict):
    id: str
    name: str
    state_code: str
    capacity: int
    turnaround_buffer_minutes: int
    filming_permit_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CastingCall(TypedDict):
    id: str
    production_id: str
    venue_location_id: Optional[str]
    channel: str
    min_age: int
    max_age: int
    residency_state_code: Optional[str]
    open_call_window_start_utc: Optional[str]
    open_call_window_end_utc: Optional[str]
    expected_attendance: int
    exclusivity_window_days: int
    status: str
    published_at: Optional[str]
    closed_reason: Optional[str]
    screened_pass_count: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    casting_call_id: str
    legal_name: str
    date_of_birth: str
    residency_state_code: str
    guardian_name: Optional[str]
    is_minor: bool
    screening_status: str
    medical_status: str
    psych_eval_required: bool
    provisional_risk_score: float
    final_risk_score: float
    enhanced_support_required: bool
    created_at: str
    updated_at: str
    version: int


class ScreeningItem(TypedDict):
    id: str
    applicant_id: str
    kind: str
    outcome: str
    severity_flags: int
    conditional_conditions: Optional[str]
    recorded_by_user_id: Optional[str]
    recorded_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MinorProtection(TypedDict):
    id: str
    applicant_id: str
    work_permit_number: str
    permit_expires_on: str
    education_hours_scheduled_weekly: int
    trust_deposit_pct: float
    trust_deposited_cents: int
    installment_count: Optional[int]
    per_installment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ParticipantAgreement(TypedDict):
    id: str
    applicant_id: str
    production_id: str
    supersedes_agreement_id: Optional[str]
    status: str
    round_number: int
    exclusivity_window_days: int
    confidentiality_tier: str
    depiction_rights_scope: str
    stipend_structure: str
    base_stipend_cents: int
    episodes_committed: int
    press_appearance_obligation_count: int
    reunion_obligation: bool
    provisional_stipend_cents: int
    total_stipend_commitment_cents: int
    last_production_proposer_user_id: Optional[str]
    executed_by_user_id: Optional[str]
    executed_at: Optional[str]
    welfare_hold: bool
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WelfareProtocol(TypedDict):
    id: str
    production_id: str
    kind: str
    coverage_start_utc: str
    coverage_end_utc: str
    cost_cents: int
    carrier_certificate_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShootBlock(TypedDict):
    id: str
    production_id: str
    location_id: str
    block_kind: str
    start_utc: str
    end_utc: str
    expected_crowd_headcount: int
    participant_agreement_ids: List[str]
    onset_minor_hours: float
    status: str
    minor_participant_count: int
    covered_head_count: int
    release_coverage_complete: bool
    created_at: str
    updated_at: str
    version: int


class PostObligation(TypedDict):
    id: str
    agreement_id: str
    kind: str
    sequence_ordinal: int
    due_utc: str
    fee_cents: int
    status: str
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    agreement_id: str
    category: str
    severity: int
    narrative: str
    status: str
    duty_of_care_breach: bool
    aftercare_sessions_authorized: int
    triaged_by_user_id: Optional[str]
    routed_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------- append-only record shapes
# PRD §2.4: "Negotiation rounds and incidental releases are append-only
# evidence, not editable state: each carries only `id` and `created_at`, and
# both `updated_at` and `version` are absent from those records entirely."


class NegotiationRound(TypedDict):
    id: str
    agreement_id: str
    round_number: int
    proposed_by: str
    proposer_user_id: str
    requested_base_stipend_cents: int
    requested_exclusivity_window_days: int
    requested_depiction_rights_scope: str
    disposition: str
    recorded_at: str
    created_at: str


class Release(TypedDict):
    id: str
    shoot_block_id: str
    subject_kind: str
    subject_name: Optional[str]
    head_count: int
    guardian_signature: bool
    disposition: str
    collected_at: str
    created_at: str
