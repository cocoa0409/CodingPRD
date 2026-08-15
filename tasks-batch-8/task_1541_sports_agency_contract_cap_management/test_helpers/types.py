"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity narratives (section 3) and the common resource
properties of section 2.4. Every resource carries id, created_at, updated_at,
and version.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    LEAGUE_OFFICER = "LeagueOfficer"
    AGENCY_MANAGER = "AgencyManager"
    AGENT = "Agent"
    TEAM = "Team"
    PLAYER = "Player"


class AgencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AgentCertStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRANSITIONING = "TRANSITIONING"
    RELEASED = "RELEASED"


class CapSeasonStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class ContractSigningStatus(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    SIGNED = "SIGNED"
    VOIDED = "VOIDED"


class CapPostingStatus(str, Enum):
    UNPOSTED = "UNPOSTED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class EndorsementStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class TenderKind(str, Enum):
    QUALIFYING_OFFER = "QUALIFYING_OFFER"
    TEAM_OPTION = "TEAM_OPTION"
    PLAYER_OPTION = "PLAYER_OPTION"


class TenderStatus(str, Enum):
    PENDING = "PENDING"
    EXERCISED = "EXERCISED"
    EXPIRED = "EXPIRED"


class GrievanceCategory(str, Enum):
    NON_PAYMENT = "NON_PAYMENT"
    ROSTER_MOVE = "ROSTER_MOVE"
    BONUS_DISPUTE = "BONUS_DISPUTE"
    MEDICAL = "MEDICAL"


class GrievanceStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ARBITRATION = "ARBITRATION"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class FeeLedgerKind(str, Enum):
    PLAYING_CONTRACT = "PLAYING_CONTRACT"
    ENDORSEMENT = "ENDORSEMENT"
    TRANSITION_ADJUSTMENT = "TRANSITION_ADJUSTMENT"


class FeeLedgerStatus(str, Enum):
    ACCRUED = "ACCRUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class Agency(TypedDict, total=False):
    id: str
    name: str
    fee_cap_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    agency_id: str
    full_name: str
    email: str
    cert_number: str
    cert_status: str
    certified_at: Optional[str]
    is_manager: bool
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    agency_id: str
    primary_agent_id: str
    full_name: str
    position: str
    status: str
    transition_to_agent_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict, total=False):
    id: str
    name: str
    league_code: str
    created_at: str
    updated_at: str
    version: int


class CapSeason(TypedDict, total=False):
    id: str
    team_id: str
    season_year: int
    cap_limit_cents: int
    luxury_threshold_cents: int
    committed_cents: int
    reserved_cents: int
    status: str
    available_hard_cents: int
    available_luxury_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    client_id: str
    team_id: str
    cap_season_id: str
    start_season_year: int
    years: int
    base_salary_cents: int
    guaranteed_cents: int
    signing_bonus_cents: int
    incentive_cents: int
    escalator_pct: float
    aav_cents: int
    total_value_cents: int
    signing_status: str
    cap_posting_status: str
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict, total=False):
    id: str
    contract_id: str
    proposed_by_agent_id: str
    round_index: int
    proposed_aav_cents: int
    proposed_guaranteed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EndorsementDeal(TypedDict, total=False):
    id: str
    client_id: str
    brand_name: str
    deal_value_cents: int
    start_date: str
    end_date: str
    agent_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TenderOption(TypedDict, total=False):
    id: str
    contract_id: str
    kind: str
    window_open_at: str
    window_close_at: str
    exercised_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Grievance(TypedDict, total=False):
    id: str
    contract_id: str
    filed_by_agent_id: str
    category: str
    description: str
    claimed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeLedgerEntry(TypedDict, total=False):
    id: str
    agency_id: str
    contract_id: Optional[str]
    endorsement_deal_id: Optional[str]
    agent_id: str
    split_pct: float
    amount_cents: int
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int
