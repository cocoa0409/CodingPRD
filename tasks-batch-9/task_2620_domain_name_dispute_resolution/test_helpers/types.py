"""Domain types for the Domain Name Dispute Resolution API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them. Panel ballots and fee ledger lines are immutable event rows
and therefore carry only `id` and `created_at`.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROVIDER_ADMIN = "ProviderAdmin"
    CASE_MANAGER = "CaseManager"
    COMPLAINANT = "Complainant"
    RESPONDENT = "Respondent"
    PANELIST = "Panelist"
    REGISTRAR_AGENT = "RegistrarAgent"


class RegistrarStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DomainLockStatus(str, Enum):
    UNLOCKED = "UNLOCKED"
    LOCKED = "LOCKED"
    TRANSFER_EXECUTED = "TRANSFER_EXECUTED"
    CANCELLATION_EXECUTED = "CANCELLATION_EXECUTED"


class CaseStatus(str, Enum):
    FILED = "FILED"
    DEFICIENT = "DEFICIENT"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    NOTIFICATION_PENDING = "NOTIFICATION_PENDING"
    COMMENCED = "COMMENCED"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    DEFAULT = "DEFAULT"
    PANEL_APPOINTMENT = "PANEL_APPOINTMENT"
    PANEL_CONSTITUTED = "PANEL_CONSTITUTED"
    IMPLEMENTATION_WAITING = "IMPLEMENTATION_WAITING"
    STAYED = "STAYED"
    IMPLEMENTED = "IMPLEMENTED"
    ADMIN_CLOSED = "ADMIN_CLOSED"
    WITHDRAWN = "WITHDRAWN"
    TERMINATED_COURT = "TERMINATED_COURT"


NON_TERMINAL_CASE_STATUSES = [
    "FILED", "DEFICIENT", "VERIFICATION_PENDING", "NOTIFICATION_PENDING",
    "COMMENCED", "RESPONSE_RECEIVED", "DEFAULT", "PANEL_APPOINTMENT",
    "PANEL_CONSTITUTED", "IMPLEMENTATION_WAITING", "STAYED",
]
TERMINAL_CASE_STATUSES = [
    "IMPLEMENTED", "ADMIN_CLOSED", "WITHDRAWN", "TERMINATED_COURT",
]


class DeficiencyNoticeStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    EXPIRED = "EXPIRED"


class VerificationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RESPONDED = "RESPONDED"
    OVERDUE = "OVERDUE"


class NotificationStatus(str, Enum):
    SENT = "SENT"
    DELIVERED = "DELIVERED"
    UNDELIVERABLE = "UNDELIVERABLE"


class AppointmentStatus(str, Enum):
    NOMINATED = "NOMINATED"
    WAIVER_PENDING = "WAIVER_PENDING"
    ACCEPTED = "ACCEPTED"
    CONFLICTED = "CONFLICTED"
    DECLINED = "DECLINED"
    REPLACED = "REPLACED"
    DISCHARGED = "DISCHARGED"


class DecisionStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    STAYED = "STAYED"
    IMPLEMENTED = "IMPLEMENTED"
    VOIDED = "VOIDED"


class PublicationStatus(str, Enum):
    UNPUBLISHED = "UNPUBLISHED"
    PUBLISHED = "PUBLISHED"
    REDACTED = "REDACTED"


class CourtChallengeStatus(str, Enum):
    FILED = "FILED"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"
    SUSTAINED = "SUSTAINED"


class PanelistRosterStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    SUSPENDED = "SUSPENDED"


class Seat(str, Enum):
    SOLE = "SOLE"
    PRESIDING = "PRESIDING"
    CO_PANELIST_1 = "CO_PANELIST_1"
    CO_PANELIST_2 = "CO_PANELIST_2"


class GroundType(str, Enum):
    TRADEMARK_RIGHTS = "TRADEMARK_RIGHTS"
    NO_LEGITIMATE_INTEREST = "NO_LEGITIMATE_INTEREST"
    BAD_FAITH = "BAD_FAITH"


class SufficiencyStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    DEFICIENT = "DEFICIENT"


class Outcome(str, Enum):
    TRANSFER = "TRANSFER"
    CANCELLATION = "CANCELLATION"
    COMPLAINT_DENIED = "COMPLAINT_DENIED"


class OutcomeBasis(str, Enum):
    STRICT_MAJORITY = "STRICT_MAJORITY"
    PRESIDING_CASTING = "PRESIDING_CASTING"


class FeeKind(str, Enum):
    FILING_FEE = "FILING_FEE"
    PANEL_SUPPLEMENT = "PANEL_SUPPLEMENT"
    REFUND = "REFUND"
    WRITE_OFF = "WRITE_OFF"


class Payer(str, Enum):
    COMPLAINANT = "COMPLAINANT"
    RESPONDENT = "RESPONDENT"
    PROVIDER = "PROVIDER"


class RedactionLevel(str, Enum):
    NONE = "NONE"
    PARTY_NAMES = "PARTY_NAMES"
    FULL = "FULL"


# --- Entity shapes -------------------------------------------------------
# Most resources carry id, created_at, updated_at and version. The two
# immutable event rows (panel ballot, fee ledger line) carry only id and
# created_at.

class Registrar(TypedDict):
    id: str
    name: str
    iana_id: str
    contact_email: str
    verification_response_hours: int
    lock_sla_hours: int
    status: str
    overdue_verification_count: int
    created_at: str
    updated_at: str
    version: int


class DomainName(TypedDict):
    id: str
    domain_name: str
    registrar_id: str
    registrant_name_public: str
    registrant_email_public: str
    registration_date: str
    expiry_date: str
    lock_status: str
    locked_at: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complainant(TypedDict):
    id: str
    legal_name: str
    country_code: str
    email: str
    open_case_count: int
    adverse_rdnh_findings: int
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    case_number: str
    complainant_id: str
    domain_id: str
    mutual_jurisdiction: str
    remedy_requested: str
    panel_election: str
    expedited_requested: bool
    respondent_panel_election: str
    required_seat_count: int
    status: str
    fee_variant_applied: str
    assessed_fee_cents: int
    complainant_share_cents: int
    respondent_share_cents: int
    honoraria_pool_cents: int
    complainant_paid_cents: int
    respondent_paid_cents: int
    paid_cents: int
    deficiency_round_count: int
    last_deficiency_issuer_user_id: Optional[str]
    compliance_cleared_by_user_id: Optional[str]
    verified_registrant_name: Optional[str]
    verified_registrant_email: Optional[str]
    commenced_at: Optional[str]
    provisional_response_due_at: Optional[str]
    response_due_at: Optional[str]
    deadline_variant_applied: str
    default_recorded: bool
    closed_at: Optional[str]
    refiling_bar_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplaintGround(TypedDict):
    id: str
    case_id: str
    ground_type: str
    assertion_text: str
    evidence_count: int
    sufficiency_status: str
    mark_registration_number: Optional[str]
    mark_jurisdiction: Optional[str]
    similarity_claim: Optional[str]
    cited_decision_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class DeficiencyNotice(TypedDict):
    id: str
    case_id: str
    deficiency_codes: List[str]
    correction_days: int
    status: str
    issued_at: str
    issued_by_user_id: str
    round_number: int
    correction_deadline_at: str
    cured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegistrarVerification(TypedDict):
    id: str
    case_id: str
    status: str
    requested_at: str
    due_at: str
    responded_at: Optional[str]
    verified_registrant_name: Optional[str]
    verified_registrant_email: Optional[str]
    lock_applied: Optional[bool]
    registrar_remarks: Optional[str]
    escalation_count: int
    created_at: str
    updated_at: str
    version: int


class RespondentNotification(TypedDict):
    id: str
    case_id: str
    channel: str
    address: str
    status: str
    dispatched_at: str
    attempt_number: int
    transmission_allowance_days: int
    deemed_received_at: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Response(TypedDict):
    id: str
    case_id: str
    respondent_email: str
    content_summary: str
    requests_three_member_panel: bool
    nominated_panelist_ids: List[str]
    submitted_at: str
    timeliness: str
    created_at: str
    updated_at: str
    version: int


class Panelist(TypedDict):
    id: str
    full_name: str
    nationality_code: str
    roster_admitted_at: str
    firm_name: Optional[str]
    specializations: List[str]
    max_overlapping_engagements: int
    status: str
    active_case_load: int
    unavailable_from: Optional[str]
    unavailable_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PanelistAppointment(TypedDict):
    id: str
    case_id: str
    panelist_id: str
    seat: str
    nominated_by: str
    selected_by_provider: bool
    status: str
    disclosed_prior_representation: Optional[bool]
    disclosed_same_firm: Optional[bool]
    disclosed_financial_interest: Optional[bool]
    prior_appointments_with_complainant: Optional[int]
    months_since_last_contact: Optional[int]
    conflict_score: Optional[float]
    conflict_factors: List[str]
    screened_at: Optional[str]
    waiver_complainant: Optional[bool]
    waiver_respondent: Optional[bool]
    accepted_at: Optional[str]
    decision_due_at: Optional[str]
    honoraria_cents: int
    replaced_by_appointment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Decision(TypedDict):
    id: str
    case_id: str
    drafted_by_panelist_id: str
    draft_summary: str
    status: str
    publication_status: str
    outcome: Optional[str]
    outcome_basis: Optional[str]
    rdnh_finding: bool
    dissent_present: bool
    transfer_votes: int
    cancellation_votes: int
    deny_votes: int
    issued_at: Optional[str]
    implementation_deadline_at: Optional[str]
    implemented_at: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CourtChallenge(TypedDict):
    id: str
    decision_id: str
    jurisdiction: str
    docket_number: str
    filed_by: str
    status: str
    filed_at: str
    resolved_at: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrecedentEntry(TypedDict):
    id: str
    decision_id: str
    published_at: str
    redaction_level: str
    precedent_tags: List[str]
    digest_text: str
    superseded: bool
    citable: bool
    citation_count: int
    precedent_weight: float
    created_at: str
    updated_at: str
    version: int


# Immutable event row: a panel ballot carries only id and created_at.
class PanelVote(TypedDict):
    id: str
    decision_id: str
    voter_panelist_id: str
    seat: str
    vote: str
    rdnh_vote: bool
    rationale: Optional[str]
    cast_at: str
    created_at: str


# Immutable event row: a fee ledger line carries only id and created_at.
class FeeTransaction(TypedDict):
    id: str
    case_id: str
    kind: str
    payer: str
    amount_cents: int
    reference: Optional[str]
    recorded_at: str
    created_at: str
