"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    RESIDENT = "Resident"
    TRAFFIC_ENGINEER = "TrafficEngineer"
    CITY_ENGINEER = "CityEngineer"
    EMERGENCY_REVIEWER = "EmergencyReviewer"
    CITY_ADMIN = "CityAdmin"


class FunctionalClass(str, Enum):
    LOCAL = "LOCAL"
    COLLECTOR = "COLLECTOR"
    ARTERIAL = "ARTERIAL"


class RequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PETITION_OPEN = "PETITION_OPEN"
    PETITION_MET = "PETITION_MET"
    PETITION_FAILED = "PETITION_FAILED"
    STUDY_IN_PROGRESS = "STUDY_IN_PROGRESS"
    RANKING_ELIGIBLE = "RANKING_ELIGIBLE"
    SCORE_INELIGIBLE = "SCORE_INELIGIBLE"
    FUNDED = "FUNDED"
    WAITLISTED = "WAITLISTED"
    DESIGN_IN_PROGRESS = "DESIGN_IN_PROGRESS"
    BALLOT_READY = "BALLOT_READY"
    BALLOT_OPEN = "BALLOT_OPEN"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    CONSENT_DENIED = "CONSENT_DENIED"
    INSTALLATION_PLANNED = "INSTALLATION_PLANNED"
    INSTALLED = "INSTALLED"
    POST_STUDY_IN_PROGRESS = "POST_STUDY_IN_PROGRESS"
    EFFECTIVENESS_CERTIFIED = "EFFECTIVENESS_CERTIFIED"
    REMOVAL_REVIEW = "REMOVAL_REVIEW"
    REMOVED = "REMOVED"


class StudyType(str, Enum):
    INITIAL = "INITIAL"
    POST_INSTALLATION = "POST_INSTALLATION"


class StudyStatus(str, Enum):
    COLLECTING = "COLLECTING"
    ANALYZED = "ANALYZED"
    CERTIFIED = "CERTIFIED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    RANKING_PUBLISHED = "RANKING_PUBLISHED"
    CLOSED = "CLOSED"


class TreatmentType(str, Enum):
    SPEED_HUMP = "SPEED_HUMP"
    CHICANE = "CHICANE"
    SIGNAGE = "SIGNAGE"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED_FOR_REVIEW = "SUBMITTED_FOR_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"
    WITHDRAWN = "WITHDRAWN"


class BallotStatus(str, Enum):
    OPEN = "OPEN"
    TALLIED = "TALLIED"


class BallotOutcome(str, Enum):
    CONSENT_GRANTED = "CONSENT_GRANTED"
    CONSENT_DENIED = "CONSENT_DENIED"


class VoteChoice(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"


class ScheduleStatus(str, Enum):
    UNSCHEDULED = "UNSCHEDULED"
    SCHEDULED = "SCHEDULED"
    INSTALLED = "INSTALLED"


class EmergencyReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class RemovalStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    REMOVAL_GRANTED = "REMOVAL_GRANTED"
    REMOVAL_DENIED = "REMOVAL_DENIED"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).
# Event records (petition signature, study observation, ballot vote) carry
# only id + created_at; updated_at and version are absent (PRD §2.5).

class StreetSegment(TypedDict, total=False):
    id: str
    name: str
    speed_limit_mph: int
    household_count: int
    functional_class: str
    emergency_route: bool
    crash_count_3yr: int
    pedestrian_generator_count: int
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    street_segment_id: str
    household_ref: str
    created_at: str
    updated_at: str
    version: int


class TrafficCalmingRequest(TypedDict, total=False):
    id: str
    street_segment_id: str
    created_by_resident_id: str
    title: str
    requested_budget_cents: int
    status: str
    petition_opened_at: Optional[str]
    petition_deadline_at: Optional[str]
    required_signatures: Optional[int]
    signature_count: int
    certified_score: Optional[int]
    funding_cycle_id: Optional[str]
    citywide_rank: Optional[int]
    allocated_cents: int
    installed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PetitionSignature(TypedDict, total=False):
    # Event record: only id + created_at are system-managed (no updated_at/version).
    id: str
    request_id: str
    resident_id: str
    household_ref: str
    signed_at: str
    created_at: str


class SpeedStudy(TypedDict, total=False):
    id: str
    request_id: str
    study_type: str
    window_start_date: str
    window_end_date: str
    status: str
    observation_count: int
    valid_observation_count: int
    provisional_p85_mph: Optional[float]
    provisional_mean_speed_mph: Optional[float]
    provisional_avg_daily_volume: Optional[int]
    provisional_score: Optional[int]
    certified_p85_mph: Optional[float]
    certified_mean_speed_mph: Optional[float]
    certified_avg_daily_volume: Optional[int]
    certified_score: Optional[int]
    baseline_p85_mph: Optional[float]
    baseline_mean_speed_mph: Optional[float]
    p85_reduction_mph: Optional[float]
    mean_reduction_mph: Optional[float]
    meets_effectiveness_target: Optional[bool]
    meets_target_mean_variant: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class StudyObservation(TypedDict, total=False):
    # Event record: only id + created_at are system-managed.
    id: str
    study_id: str
    observation_date: str
    vehicle_count: int
    p85_speed_mph: float
    mean_speed_mph: float
    is_valid: bool
    created_at: str


class FundingCycle(TypedDict, total=False):
    id: str
    cycle_year: int
    budget_total_cents: int
    budget_committed_cents: int
    budget_available_cents: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict, total=False):
    id: str
    request_id: str
    treatment_type: str
    estimated_cost_cents: int
    created_by_user_id: str
    status: str
    approved_by_user_id: Optional[str]
    submitted_at: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ballot(TypedDict, total=False):
    id: str
    request_id: str
    treatment_plan_id: str
    close_date: str
    eligible_households: int
    quorum_required: int
    votes_received: int
    votes_for: int
    votes_against: int
    status: str
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BallotVote(TypedDict, total=False):
    # Event record: only id + created_at are system-managed.
    id: str
    ballot_id: str
    resident_id: str
    household_ref: str
    choice: str
    cast_at: str
    created_at: str


class InstallationWorkOrder(TypedDict, total=False):
    id: str
    request_id: str
    crew_ref: str
    scheduled_date: Optional[str]
    duration_days: Optional[int]
    schedule_status: str
    emergency_review_status: str
    reviewed_by_user_id: Optional[str]
    installed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemovalRequest(TypedDict, total=False):
    id: str
    request_id: str
    created_by_resident_id: str
    reason: str
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
