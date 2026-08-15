"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CLAIMS_ANALYST = "ClaimsAnalyst"
    TPA_AGENT = "TpaAgent"
    AGENCY_LIAISON = "AgencyLiaison"
    CHARGE_AUDITOR = "ChargeAuditor"
    RATING_ANALYST = "RatingAnalyst"
    TPA_MANAGER = "TpaManager"


class MeritRatingMethod(str, Enum):
    RESERVE_RATIO = "RESERVE_RATIO"
    BENEFIT_RATIO = "BENEFIT_RATIO"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    SANCTIONED = "SANCTIONED"


class OversightStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REINSTATED = "REINSTATED"
    TERMINATED = "TERMINATED"


class AuthorityScope(str, Enum):
    RESPONSE_ONLY = "RESPONSE_ONLY"
    RESPONSE_AND_HEARING = "RESPONSE_AND_HEARING"
    FULL = "FULL"


class WindowBasis(str, Enum):
    CALENDAR = "CALENDAR"
    BUSINESS = "BUSINESS"


class WeekendShift(str, Enum):
    NEXT_BUSINESS_DAY = "NEXT_BUSINESS_DAY"
    NONE = "NONE"


class SeparationReason(str, Enum):
    VOLUNTARY_QUIT = "VOLUNTARY_QUIT"
    DISCHARGE_MISCONDUCT = "DISCHARGE_MISCONDUCT"
    DISCHARGE_NON_MISCONDUCT = "DISCHARGE_NON_MISCONDUCT"
    LAYOFF = "LAYOFF"
    LEAVE_OF_ABSENCE = "LEAVE_OF_ABSENCE"


class CodingConfidence(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"


class ClaimStatus(str, Enum):
    NOTICE_RECEIVED = "NOTICE_RECEIVED"
    RESPONSE_IN_PROGRESS = "RESPONSE_IN_PROGRESS"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    LATE_RESPONSE = "LATE_RESPONSE"
    UNDER_ADJUDICATION = "UNDER_ADJUDICATION"
    DETERMINED = "DETERMINED"
    HEARING_PENDING = "HEARING_PENDING"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class AdjudicationPosture(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class ResponseType(str, Enum):
    PROTEST = "PROTEST"
    NO_PROTEST = "NO_PROTEST"
    INFORMATION_ONLY = "INFORMATION_ONLY"


class ResponseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED_INSUFFICIENT = "REJECTED_INSUFFICIENT"
    SUPERSEDED = "SUPERSEDED"


class Timeliness(str, Enum):
    ON_TIME = "ON_TIME"
    LATE = "LATE"


class DocCategory(str, Enum):
    WRITTEN_WARNING = "WRITTEN_WARNING"
    SIGNED_POLICY = "SIGNED_POLICY"
    FINAL_INCIDENT_REPORT = "FINAL_INCIDENT_REPORT"
    ATTENDANCE_RECORD = "ATTENDANCE_RECORD"
    PERFORMANCE_REVIEW = "PERFORMANCE_REVIEW"
    RESIGNATION_LETTER = "RESIGNATION_LETTER"
    OTHER = "OTHER"


class DeterminationOutcome(str, Enum):
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"
    ALLOWED_NO_CHARGE = "ALLOWED_NO_CHARGE"


class DeterminationStatus(str, Enum):
    ISSUED = "ISSUED"
    APPEALED_BY_EMPLOYER = "APPEALED_BY_EMPLOYER"
    APPEALED_BY_CLAIMANT = "APPEALED_BY_CLAIMANT"
    FINAL = "FINAL"
    REVERSED = "REVERSED"


class Appellant(str, Enum):
    EMPLOYER = "EMPLOYER"
    CLAIMANT = "CLAIMANT"


class AppealStatus(str, Enum):
    FILED = "FILED"
    DOCKETED = "DOCKETED"
    HEARD = "HEARD"
    DECIDED_AFFIRMED = "DECIDED_AFFIRMED"
    DECIDED_REVERSED = "DECIDED_REVERSED"
    REMANDED = "REMANDED"
    WITHDRAWN = "WITHDRAWN"
    DISMISSED_UNTIMELY = "DISMISSED_UNTIMELY"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PREP_IN_PROGRESS = "PREP_IN_PROGRESS"
    READY = "READY"
    HELD = "HELD"
    CONTINUED = "CONTINUED"
    CLOSED = "CLOSED"


class WitnessRole(str, Enum):
    DIRECT_SUPERVISOR = "DIRECT_SUPERVISOR"
    HR_CUSTODIAN = "HR_CUSTODIAN"
    POLICY_AUTHOR = "POLICY_AUTHOR"
    CLAIMANT = "CLAIMANT"
    OTHER = "OTHER"


class PrepStatus(str, Enum):
    UNPREPARED = "UNPREPARED"
    BRIEFED = "BRIEFED"
    EXHIBITS_REVIEWED = "EXHIBITS_REVIEWED"
    READY = "READY"


class StatementStatus(str, Enum):
    ISSUED = "ISSUED"
    UNDER_AUDIT = "UNDER_AUDIT"
    AUDIT_COMPLETE = "AUDIT_COMPLETE"
    RECONCILED = "RECONCILED"


class ErroneousReason(str, Enum):
    NONE = "NONE"
    CLAIMANT_NOT_SEPARATED = "CLAIMANT_NOT_SEPARATED"
    WRONG_EMPLOYER = "WRONG_EMPLOYER"
    ALREADY_PROTESTED = "ALREADY_PROTESTED"
    EXCEEDS_MAX_BENEFIT = "EXCEEDS_MAX_BENEFIT"
    DUPLICATE_LINE = "DUPLICATE_LINE"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    PROTESTED = "PROTESTED"
    SUSTAINED = "SUSTAINED"
    REVERSED = "REVERSED"
    WAIVED = "WAIVED"


class ProtestStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    DISMISSED_UNTIMELY = "DISMISSED_UNTIMELY"


class ModelVariant(str, Enum):
    RESERVE_RATIO = "RESERVE_RATIO"
    BENEFIT_RATIO = "BENEFIT_RATIO"


class ModelKind(str, Enum):
    OFFICIAL = "OFFICIAL"
    WHAT_IF = "WHAT_IF"


class ModelStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Every resource carries the standard system-managed
# fields id / created_at / updated_at / version (PRD §2.4).
# ---------------------------------------------------------------------------


class EmployerAccount(TypedDict, total=False):
    id: str
    legal_name: str
    fein: str
    merit_rating_method: str
    reserve_balance_cents: int
    taxable_payroll_cents: int
    current_tax_rate_bps: int
    protest_credits_cents: int
    compliance_posture: str
    late_response_strikes: int
    created_at: str
    updated_at: str
    version: int


class TpaEngagement(TypedDict, total=False):
    id: str
    employer_id: str
    tpa_name: str
    authority_scope: str
    effective_from: str
    effective_to: str
    oversight_status: str
    breach_count: int
    created_at: str
    updated_at: str
    version: int


class StateRule(TypedDict, total=False):
    id: str
    state_code: str
    response_window_days: int
    window_basis: str
    appeal_window_days: int
    protest_window_days: int
    weekend_shift: str
    created_at: str
    updated_at: str
    version: int


class ClaimantSeparation(TypedDict, total=False):
    id: str
    employer_id: str
    claimant_name: str
    ssn_last4: str
    last_day_worked: str
    separation_reason: str
    reason_coding_confidence: str
    created_at: str
    updated_at: str
    version: int


class UiClaim(TypedDict, total=False):
    id: str
    employer_id: str
    separation_id: str
    state_code: str
    state_claim_number: str
    notice_received_at: str
    response_due_at: str
    benefit_year_begin: str
    weekly_benefit_amount_cents: int
    max_benefit_cents: int
    charged_amount_cents: int
    status: str
    response_channel: Optional[str]
    adjudication_posture: str
    created_at: str
    updated_at: str
    version: int


class ClaimResponse(TypedDict, total=False):
    id: str
    claim_id: str
    filed_by_tpa_id: Optional[str]
    response_type: str
    separation_reason_code: str
    narrative: str
    filed_at: Optional[str]
    timeliness: Optional[str]
    completeness_score: int
    status: str
    amendment_of: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceDocument(TypedDict, total=False):
    id: str
    claim_id: str
    response_id: Optional[str]
    doc_category: str
    doc_date: str
    authenticated: bool
    weight_points: int
    created_at: str
    updated_at: str
    version: int


class Determination(TypedDict, total=False):
    id: str
    claim_id: str
    outcome: str
    mailed_at: str
    appeal_due_at: str
    disqualification_weeks: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    determination_id: str
    appellant: str
    filed_at: str
    timeliness: str
    grounds: str
    round_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict, total=False):
    id: str
    appeal_id: str
    claim_id: str
    scheduled_start: str
    scheduled_end: str
    referee_id: str
    location: str
    continuance_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Witness(TypedDict, total=False):
    id: str
    hearing_id: str
    full_name: str
    witness_role: str
    availability_start: str
    availability_end: str
    prep_status: str
    created_at: str
    updated_at: str
    version: int


class ChargeStatement(TypedDict, total=False):
    id: str
    employer_id: str
    state_code: str
    quarter: str
    issued_at: str
    protest_due_at: str
    total_charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargeLineItem(TypedDict, total=False):
    id: str
    statement_id: str
    claim_id: str
    amount_cents: int
    benefit_weeks: int
    erroneous_reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargeProtest(TypedDict, total=False):
    id: str
    line_item_id: str
    statement_id: str
    filed_at: str
    timeliness: str
    protest_basis: str
    evidence_strength: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExperienceRatingModel(TypedDict, total=False):
    id: str
    employer_id: str
    model_year: int
    variant: str
    kind: str
    projected_rate_bps: int
    projected_liability_cents: int
    input_snapshot_hash: str
    status: str
    created_at: str
    updated_at: str
    version: int
