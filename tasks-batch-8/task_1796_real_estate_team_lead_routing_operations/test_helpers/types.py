"""Domain types: entity TypedDicts, status enums, role enum (PRD §2–§3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    TEAM_ADMIN = "TeamAdmin"
    TEAM_LEADER = "TeamLeader"
    AGENT = "Agent"
    REFERRAL_PARTNER = "ReferralPartner"


class AgentStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    OFFBOARDING = "OFFBOARDING"
    OFFBOARDED = "OFFBOARDED"


class RoleOnTeam(str, Enum):
    MEMBER = "MEMBER"
    LEADER = "LEADER"


class PerformanceTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class RoutingMode(str, Enum):
    ROUND_ROBIN = "ROUND_ROBIN"
    PERFORMANCE_WEIGHTED = "PERFORMANCE_WEIGHTED"


class RoutingPolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class LeadSourceType(str, Enum):
    PORTAL = "PORTAL"
    IDX_WEBSITE = "IDX_WEBSITE"
    PAID_AD = "PAID_AD"
    REFERRAL_PARTNER = "REFERRAL_PARTNER"
    SPHERE = "SPHERE"
    SIGN_CALL = "SIGN_CALL"


class LeadSourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class LeadStatus(str, Enum):
    NEW = "NEW"
    OFFERED = "OFFERED"
    CLAIMED = "CLAIMED"
    WORKING = "WORKING"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED_WON = "CLOSED_WON"
    CLOSED_LOST = "CLOSED_LOST"


class LeadTemperature(str, Enum):
    COLD = "COLD"
    WARM = "WARM"
    HOT = "HOT"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"
    REASSIGNED = "REASSIGNED"


class AssignmentOutcomeReason(str, Enum):
    DEADLINE = "DEADLINE"
    AUTO_PAUSE = "AUTO_PAUSE"
    OFFBOARD = "OFFBOARD"
    MANUAL = "MANUAL"
    RELEASED = "RELEASED"


class EngagementEventType(str, Enum):
    EMAIL_OPEN = "EMAIL_OPEN"
    LINK_CLICK = "LINK_CLICK"
    CALL_ANSWERED = "CALL_ANSWERED"
    FORM_SUBMIT = "FORM_SUBMIT"
    REPLIED = "REPLIED"
    SHOWING_ATTENDED = "SHOWING_ATTENDED"


class NurtureCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class NurtureEnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    EXITED = "EXITED"


class EnrollmentExitReason(str, Enum):
    MANUAL = "MANUAL"
    TEMPERATURE_SHIFT = "TEMPERATURE_SHIFT"
    CONVERTED = "CONVERTED"


class SplitAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class DealStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    PAID_OUT = "PAID_OUT"


class SplitBasisType(str, Enum):
    ESTIMATED = "ESTIMATED"
    ACTUAL = "ACTUAL"


# --- Entity TypedDicts -------------------------------------------------------
# Mutable resources carry id + created_at + updated_at + version (PRD §2.5).
# EngagementEvent is the append-only exception: only id + created_at (PRD §2.5).


class Team(TypedDict, total=False):
    id: str
    name: str
    market: str
    timezone: str
    speed_to_lead_window_seconds: int
    claim_window_seconds: int
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    team_id: str
    display_name: str
    license_number: str
    role_on_team: str
    max_active_leads: int
    status: str
    performance_tier: str
    active_lead_count: int
    trailing_90d_conversions: int
    trailing_90d_claimed: int
    trailing_90d_offered: int
    avg_first_response_seconds: Optional[int]
    consecutive_missed_claims: int
    last_assigned_at: Optional[str]
    onboarded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AgentTimeOff(TypedDict, total=False):
    id: str
    agent_id: str
    starts_at: str
    ends_at: str
    reason: str
    created_at: str
    updated_at: str
    version: int


class RoutingPolicy(TypedDict, total=False):
    id: str
    team_id: str
    version_no: int
    mode: str
    tier_weight_bps: Dict[str, int]
    source_mode_overrides: Dict[str, str]
    claim_window_seconds: Optional[int]
    speed_to_lead_window_seconds: Optional[int]
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeadSource(TypedDict, total=False):
    id: str
    team_id: str
    name: str
    type: str
    cost_per_lead_cents: int
    monthly_budget_cents: int
    priority_weight: int
    auto_route: bool
    status: str
    leads_this_month_count: int
    spent_this_month_cents: int
    created_at: str
    updated_at: str
    version: int


class Lead(TypedDict, total=False):
    id: str
    team_id: str
    source_id: str
    assigned_agent_id: Optional[str]
    referral_partner_id: Optional[str]
    contact_name: str
    contact_phone: str
    contact_email: str
    expected_close_price_cents: int
    status: str
    temperature: str
    engagement_score: int
    first_response_at: Optional[str]
    within_speed_sla: Optional[bool]
    speed_deadline_at: Optional[str]
    claim_deadline_at: Optional[str]
    current_assignment_id: Optional[str]
    close_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    lead_id: str
    agent_id: str
    policy_id: str
    supersedes_assignment_id: Optional[str]
    rotation_seq: int
    policy_mode_snapshot: str
    offered_at: str
    claim_deadline_at: str
    responded_at: Optional[str]
    status: str
    outcome_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EngagementEvent(TypedDict, total=False):
    # Append-only log: carries ONLY id + created_at (no updated_at, no version).
    id: str
    lead_id: str
    type: str
    occurred_at: str
    points: int
    effective_points: int
    created_at: str


class NurtureCampaign(TypedDict, total=False):
    id: str
    team_id: str
    name: str
    temperature_target: str
    steps: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class NurtureEnrollment(TypedDict, total=False):
    id: str
    campaign_id: str
    lead_id: str
    status: str
    entered_temperature: str
    current_step_index: int
    next_send_at: str
    exit_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReferralPartner(TypedDict, total=False):
    id: str
    team_id: str
    name: str
    fee_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SplitAgreement(TypedDict, total=False):
    id: str
    team_id: str
    agent_a_id: str
    agent_b_id: str
    a_share_bps: int
    b_share_bps: int
    effective_from: str
    effective_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AgentShare(TypedDict):
    agent_id: str
    amount_cents: int


class Deal(TypedDict, total=False):
    id: str
    team_id: str
    lead_id: str
    agent_id: str
    gross_commission_cents: int
    actual_gross_commission_cents: Optional[int]
    status: str
    split_basis_type: str
    split_basis_cents: int
    referral_partner_id: Optional[str]
    effective_fee_bps: int
    referral_fee_cents: int
    house_share_cents: int
    agent_pool_cents: int
    agent_shares: List[AgentShare]
    split_agreement_id: Optional[str]
    approved_at: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
