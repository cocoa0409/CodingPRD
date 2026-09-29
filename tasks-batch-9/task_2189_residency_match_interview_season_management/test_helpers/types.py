"""TypedDict shapes and enum vocabularies for every resource in PRD §2/§3.

Every resource carries the same four system-managed fields (PRD §2.6):
``id``, ``created_at``, ``updated_at``, ``version``. No resource is exempt, so
all eighteen TypedDicts below extend :class:`SystemFields`.
"""

from typing import Any, TypedDict


# ----------------------------------------------------------------------
# Roles (PRD §2.1)
# ----------------------------------------------------------------------
class UserRole:
    NRMP_ADMIN = "NrmpAdmin"
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    PROGRAM_DIRECTOR = "ProgramDirector"
    REVIEWER = "Reviewer"
    INTERVIEWER = "Interviewer"
    COMMITTEE_MEMBER = "CommitteeMember"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    APPLICANT = "Applicant"


#: Roles whose caller id must be the id of a stored ``FacultyMember``.
FACULTY_BACKED_ROLES = (
    UserRole.PROGRAM_DIRECTOR,
    UserRole.REVIEWER,
    UserRole.INTERVIEWER,
    UserRole.COMMITTEE_MEMBER,
)

#: Roles whose caller id is not a stored resource.
OPAQUE_ROLES = (
    UserRole.NRMP_ADMIN,
    UserRole.PROGRAM_COORDINATOR,
    UserRole.COMPLIANCE_OFFICER,
)


# ----------------------------------------------------------------------
# Enum vocabularies
# ----------------------------------------------------------------------
class SeasonPhase:
    PRE_SEASON = "PRE_SEASON"
    REVIEW_OPEN = "REVIEW_OPEN"
    INTERVIEWS_OPEN = "INTERVIEWS_OPEN"
    RANKING = "RANKING"
    LIST_CERTIFIED = "LIST_CERTIFIED"
    MATCH_COMPLETE = "MATCH_COMPLETE"
    SOAP_ACTIVE = "SOAP_ACTIVE"
    SEASON_CLOSED = "SEASON_CLOSED"


class MedicalSchoolType:
    US_MD = "US_MD"
    US_DO = "US_DO"
    IMG = "IMG"


class VisaStatus:
    US_CITIZEN = "US_CITIZEN"
    PERMANENT_RESIDENT = "PERMANENT_RESIDENT"
    NEEDS_J1 = "NEEDS_J1"
    NEEDS_H1B = "NEEDS_H1B"


class ScreeningStatus:
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADVANCED = "ADVANCED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class InterviewStatus:
    NOT_INVITED = "NOT_INVITED"
    INVITED = "INVITED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ScreeningDecision:
    ADVANCE = "ADVANCE"
    REJECT = "REJECT"


class WaveStatus:
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"


class SlotStatus:
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InvitationStatus:
    ISSUED = "ISSUED"
    WAITLISTED = "WAITLISTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class PanelRole:
    LEAD = "LEAD"
    MEMBER = "MEMBER"


class AssignmentStatus:
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class ScoreCardStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    AMEND_REQUESTED = "AMEND_REQUESTED"
    LOCKED = "LOCKED"


class RankListStatus:
    DRAFT = "DRAFT"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    CERTIFIED = "CERTIFIED"
    WITHDRAWN = "WITHDRAWN"


class Ballot:
    APPROVE = "APPROVE"
    RETURN = "RETURN"


class MatchOutcome:
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    VACATED = "VACATED"


class SoapOfferStatus:
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class ContractStatus:
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    VOID = "VOID"
    RESCINDED = "RESCINDED"


class CredentialType:
    STATE_LICENSE = "STATE_LICENSE"
    DEA = "DEA"
    VISA = "VISA"
    BLS = "BLS"


class CredentialItemStatus:
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class CommunicationChannel:
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    IN_PERSON = "IN_PERSON"


class ComplianceStatus:
    CLEAN = "CLEAN"
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"


# ----------------------------------------------------------------------
# Resource shapes
# ----------------------------------------------------------------------
class SystemFields(TypedDict):
    """The four system-managed fields every resource carries (PRD §2.6)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Program(SystemFields):
    name: str
    nrmp_program_code: str
    specialty_code: str
    quota_positions: int
    season_phase: str
    visa_sponsorship_allowed: bool
    soap_participating: bool
    min_step2_score: int
    img_accepted: bool
    matched_count: int
    unfilled_positions: int
    invited_count: int
    soap_offer_budget: int
    rank_list_certified_at: str | None


class Applicant(SystemFields):
    eras_id: str
    full_name: str
    medical_school_type: str
    visa_status: str
    step2_score: int
    pipeline_program_alum: bool
    self_identified_group: str | None


class Application(SystemFields):
    program_id: str
    applicant_id: str
    screening_status: str
    interview_status: str
    review_count: int
    provisional_screen_score: float
    final_screen_score: float | None
    committee_score: float | None
    withdrawn_reason: str | None


class FacultyMember(SystemFields):
    program_id: str
    full_name: str
    is_program_director: bool
    is_committee_member: bool
    conflict_applicant_ids: list[str]
    scheduled_load: float
    realized_load: float


class ApplicationReview(SystemFields):
    application_id: str
    reviewer_id: str
    academic_points: int
    experience_points: int
    holistic_points: int


class InterviewWave(SystemFields):
    program_id: str
    wave_index: int
    invite_release_at: str
    response_deadline_at: str
    seat_capacity: int
    status: str
    issued_count: int


class InterviewSlot(SystemFields):
    wave_id: str
    start_at: str
    end_at: str
    room_label: str
    applicant_capacity: int
    booked_count: int
    status: str


class InterviewInvitation(SystemFields):
    application_id: str
    wave_id: str
    slot_id: str | None
    status: str
    issued_at: str | None
    expires_at: str | None
    responded_at: str | None


class InterviewAssignment(SystemFields):
    slot_id: str
    faculty_member_id: str
    panel_role: str
    status: str


class ScoreCard(SystemFields):
    assignment_id: str
    application_id: str
    communication_score: int
    clinical_reasoning_score: int
    professionalism_score: int
    teamwork_score: int
    domain_average: float | None
    status: str


class RankList(SystemFields):
    program_id: str
    status: str
    entry_count: int
    review_round: int
    approved_at: str | None
    certified_by_faculty_id: str | None


class RankListEntry(SystemFields):
    rank_list_id: str
    application_id: str
    rank_position: int
    tie_group_anchor_entry_id: str | None


class CommitteeVote(SystemFields):
    rank_list_id: str
    faculty_member_id: str
    review_round: int
    ballot: str
    comment: str | None


class MatchResult(SystemFields):
    program_id: str
    application_id: str
    outcome: str
    matched_rank_position: int | None
    published_at: str | None


class SoapOffer(SystemFields):
    program_id: str
    application_id: str
    soap_round: int
    status: str
    offered_at: str | None
    expires_at: str | None


class Contract(SystemFields):
    match_result_id: str
    salary_cents: int
    status: str
    issued_at: str | None
    signed_at: str | None
    mandatory_credential_count: int
    verified_credential_count: int


class CredentialItem(SystemFields):
    contract_id: str
    credential_type: str
    is_mandatory: bool
    status: str
    reference_number: str | None
    verified_at: str | None


class CommunicationLog(SystemFields):
    application_id: str
    author_faculty_id: str | None
    channel: str
    body: str
    contains_ranking_intent: bool
    compliance_status: str
    sent_at: str | None


class PipelineReport(TypedDict):
    """Body of the program pipeline aggregate (PRD §3.10)."""

    cohort_size: int
    advanced_rate: float
    img_share: float
    pipeline_alum_share: float
    group_buckets: list[dict[str, Any]]
