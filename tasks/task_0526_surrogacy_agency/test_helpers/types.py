"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the full common fields (id, created_at,
updated_at, version) per the PRD's common-resource-properties section — none is
a create-only, immutable record.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CASE_MANAGER = "CaseManager"
    SCREENER = "Screener"
    FINANCE_OFFICER = "FinanceOfficer"
    INTENDED_PARENT_ACTOR = "IntendedParentActor"
    CARRIER_ACTOR = "CarrierActor"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class IntakeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class PsychClearance(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class MatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    PSYCH_CLEARED = "PSYCH_CLEARED"
    VOID = "VOID"


class ContractStatus(str, Enum):
    DRAFTED = "DRAFTED"
    IP_SIGNED = "IP_SIGNED"
    EXECUTED = "EXECUTED"
    VOID = "VOID"


class EscrowStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class JourneyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class JourneyPhase(str, Enum):
    PRE_TRANSFER = "PRE_TRANSFER"
    TRANSFERRED = "TRANSFERRED"
    HEARTBEAT_CONFIRMED = "HEARTBEAT_CONFIRMED"
    BORN = "BORN"


class ParentageOrderStatus(str, Enum):
    NOT_FILED = "NOT_FILED"
    FILED = "FILED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class MilestoneType(str, Enum):
    EMBRYO_TRANSFER = "EMBRYO_TRANSFER"
    HEARTBEAT = "HEARTBEAT"
    BIRTH = "BIRTH"


class MilestoneStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACHIEVED = "ACHIEVED"
    FAILED = "FAILED"


class Recipient(str, Enum):
    CARRIER = "CARRIER"
    DONOR = "DONOR"


class DisbursementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class PolicyKind(str, Enum):
    SURROGACY_FRIENDLY = "SURROGACY_FRIENDLY"
    EXCLUSION = "EXCLUSION"
    NONE = "NONE"


class InsuranceReviewStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    GAP_IDENTIFIED = "GAP_IDENTIFIED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------
# Entity TypedDicts (all carry full common fields)
# --------------------------------------------------------------------------
class IntendedParent(TypedDict):
    id: str
    legal_name: str
    state_code: str
    intake_status: str
    psych_clearance: str
    budget_cents: int
    created_at: str
    updated_at: str
    version: int


class GestationalCarrier(TypedDict):
    id: str
    legal_name: str
    state_code: str
    intake_status: str
    psych_clearance: str
    prior_deliveries: int
    base_compensation_cents: int
    created_at: str
    updated_at: str
    version: int


class EggDonor(TypedDict):
    id: str
    donor_code: str
    state_code: str
    intake_status: str
    donor_compensation_cents: int
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict):
    id: str
    intended_parent_id: str
    carrier_id: str
    donor_id: Optional[str]
    status: str
    offer_round: int
    proposed_carrier_comp_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    match_id: str
    status: str
    ip_signed_at: Optional[str]
    cooling_off_days: int
    created_at: str
    updated_at: str
    version: int


class EscrowAccount(TypedDict):
    id: str
    journey_id: str
    deposited_cents: int
    disbursed_cents: int
    reserved_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Journey(TypedDict):
    id: str
    match_id: str
    status: str
    current_phase: str
    parentage_order_status: str
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    journey_id: str
    milestone_type: str
    status: str
    scheduled_utc: str
    achieved_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompensationSchedule(TypedDict):
    id: str
    journey_id: str
    trigger_milestone_type: str
    recipient: str
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    journey_id: str
    schedule_id: str
    escrow_account_id: str
    amount_cents: int
    status: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceReview(TypedDict):
    id: str
    carrier_id: str
    policy_kind: str
    status: str
    gap_premium_cents: int
    created_at: str
    updated_at: str
    version: int
