"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


class UserRole(str, Enum):
    PROXY_ADMINISTRATOR = "ProxyAdministrator"
    TRANSFER_AGENT = "TransferAgent"
    SHAREHOLDER = "Shareholder"
    BROKER = "Broker"
    INSPECTOR_OF_ELECTION = "InspectorOfElection"


class MeetingType(str, Enum):
    ANNUAL = "ANNUAL"
    SPECIAL = "SPECIAL"
    CONTESTED = "CONTESTED"


class MeetingMode(str, Enum):
    IN_PERSON = "IN_PERSON"
    VIRTUAL = "VIRTUAL"
    HYBRID = "HYBRID"


class MeetingStatus(str, Enum):
    DRAFT = "DRAFT"
    RECORD_DATE_LOCKED = "RECORD_DATE_LOCKED"
    MATERIALS_DISTRIBUTED = "MATERIALS_DISTRIBUTED"
    VOTING_OPEN = "VOTING_OPEN"
    MEETING_IN_PROGRESS = "MEETING_IN_PROGRESS"
    ADJOURNED = "ADJOURNED"
    MEETING_HELD = "MEETING_HELD"
    RESULTS_CERTIFIED = "RESULTS_CERTIFIED"
    FILED_8K = "FILED_8K"
    CANCELLED = "CANCELLED"


class ShareClass(str, Enum):
    COMMON = "COMMON"
    PREFERRED = "PREFERRED"


class DeliveryPreference(str, Enum):
    NOTICE_AND_ACCESS = "NOTICE_AND_ACCESS"
    FULL_MAIL = "FULL_MAIL"
    E_DELIVERY = "E_DELIVERY"


class AccountStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"


class BrokerSearchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RESPONDED = "RESPONDED"


class DistributionChannel(str, Enum):
    NOTICE_AND_ACCESS = "NOTICE_AND_ACCESS"
    FULL_MAIL = "FULL_MAIL"
    E_DELIVERY = "E_DELIVERY"


class DistributionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELIVERED = "DELIVERED"
    BOUNCED = "BOUNCED"
    SUPERSEDED = "SUPERSEDED"


class DeliveryOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    BOUNCED = "BOUNCED"


class ProposalType(str, Enum):
    DIRECTOR_ELECTION = "DIRECTOR_ELECTION"
    SAY_ON_PAY = "SAY_ON_PAY"
    RATIFICATION = "RATIFICATION"
    SHAREHOLDER_PROPOSAL = "SHAREHOLDER_PROPOSAL"


class VoteStandard(str, Enum):
    MAJORITY_OF_VOTES_CAST = "MAJORITY_OF_VOTES_CAST"
    MAJORITY_OF_OUTSTANDING = "MAJORITY_OF_OUTSTANDING"
    PLURALITY = "PLURALITY"


class BoardRecommendation(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    NO_RECOMMENDATION = "NO_RECOMMENDATION"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WITHDRAWN = "WITHDRAWN"


class VoteChannel(str, Enum):
    INTERNET = "INTERNET"
    PHONE = "PHONE"
    MAIL = "MAIL"
    BROKER = "BROKER"
    IN_PERSON = "IN_PERSON"


class VoteChoice(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"
    WITHHOLD = "WITHHOLD"


class VoteStatus(str, Enum):
    VALIDATED = "VALIDATED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    INVALIDATED = "INVALIDATED"


class SessionType(str, Enum):
    REHEARSAL = "REHEARSAL"
    LIVE = "LIVE"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"


class QuestionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"


class ModerationAction(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RETURN = "RETURN"


class ChallengeRuling(str, Enum):
    UPHELD = "UPHELD"
    OVERRULED = "OVERRULED"


class ChallengeStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    OVERRULED = "OVERRULED"


class CertificationStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    SUPERSEDED = "SUPERSEDED"


class QuorumVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class TabulationVariant(str, Enum):
    UNOFFICIAL = "UNOFFICIAL"
    CERTIFIED = "CERTIFIED"


class ProjectedOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class Meeting(TypedDict, total=False):
    id: str
    company_name: str
    ticker: str
    meeting_type: str
    record_date: str
    meeting_datetime: str
    meeting_mode: str
    quorum_threshold_pct: float
    outstanding_shares: int
    status: str
    walk_in_shares: int
    filed_at: Optional[str]
    filing_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShareholderAccount(TypedDict, total=False):
    id: str
    meeting_id: str
    holder_name: str
    account_number: str
    share_class: str
    shares_held: int
    address_key: Optional[str]
    email: Optional[str]
    delivery_preference: str
    householding_opt_out: bool
    control_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BrokerSearchRecord(TypedDict, total=False):
    id: str
    meeting_id: str
    broker_code: str
    broker_name: str
    status: str
    shares_reported: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MaterialDistribution(TypedDict, total=False):
    id: str
    meeting_id: str
    channel: str
    representative_account_id: str
    covered_account_ids: List[str]
    covered_shares: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict, total=False):
    id: str
    meeting_id: str
    proposal_number: int
    title: str
    proposal_type: str
    vote_standard: str
    board_recommendation: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VoteInstruction(TypedDict, total=False):
    id: str
    meeting_id: str
    proposal_id: str
    account_id: str
    channel: str
    choice: str
    shares_voted: int
    control_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MeetingPlatformSession(TypedDict, total=False):
    id: str
    meeting_id: str
    session_type: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QuestionSubmission(TypedDict, total=False):
    id: str
    meeting_id: str
    account_id: str
    question_text: str
    moderation_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class VoteChallenge(TypedDict, total=False):
    id: str
    meeting_id: str
    vote_instruction_id: str
    reason: str
    ruling: Optional[str]
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SolicitationCampaign(TypedDict, total=False):
    id: str
    meeting_id: str
    soliciting_party: str
    start_at: str
    end_at: str
    created_at: str
    updated_at: str
    version: int


class InspectorCertification(TypedDict, total=False):
    id: str
    meeting_id: str
    created_by_user_id: str
    final_quorum_met: bool
    final_quorum_pct_bp: int
    outcomes: Dict[str, str]
    status: str
    created_at: str
    updated_at: str
    version: int
