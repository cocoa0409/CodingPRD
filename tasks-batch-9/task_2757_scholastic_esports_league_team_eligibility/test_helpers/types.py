"""Domain types for the Scholastic Esports League API.

Entity TypedDicts, status enumerations and the role enumeration, all taken
from the PRD's entity descriptions in §3 and its role list in §2.1.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    LEAGUE_ADMIN = "LeagueAdmin"
    DISTRICT_ADMIN = "DistrictAdmin"
    ATHLETIC_DIRECTOR = "AthleticDirector"
    COACH = "Coach"
    ELIGIBILITY_OFFICER = "EligibilityOfficer"
    INTEGRITY_OFFICER = "IntegrityOfficer"
    RECRUITER = "Recruiter"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class AgeRating(str, Enum):
    E = "E"
    E10 = "E10"
    T = "T"
    M = "M"


AGE_RATING_ORDINAL = {"E": 0, "E10": 1, "T": 2, "M": 3}


class AcademicStandingBasis(str, Enum):
    TERM_SNAPSHOT = "TERM_SNAPSHOT"
    ROLLING_CUMULATIVE = "ROLLING_CUMULATIVE"


class SchoolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    INACTIVE = "INACTIVE"


class CoachCertificationStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class StudentEnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class AcademicStanding(str, Enum):
    UNEVALUATED = "UNEVALUATED"
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    INELIGIBLE = "INELIGIBLE"


class FairPlayStatus(str, Enum):
    CLEAR = "CLEAR"
    SANCTIONED = "SANCTIONED"


class ShowcaseStatus(str, Enum):
    NONE = "NONE"
    NOMINATED = "NOMINATED"


class AwardTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ScholarshipAwardState(str, Enum):
    NONE = "NONE"
    CURRENT = "CURRENT"
    RECALC_REQUIRED = "RECALC_REQUIRED"


class TitleApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    ROSTER_LOCKED = "ROSTER_LOCKED"
    REGULAR_SEASON = "REGULAR_SEASON"
    PLAYOFFS = "PLAYOFFS"
    COMPLETE = "COMPLETE"


class SeedingState(str, Enum):
    UNSEEDED = "UNSEEDED"
    SEEDED = "SEEDED"
    STALE = "STALE"


class SeedingBasis(str, Enum):
    MATCH_POINT_BASIS = "MATCH_POINT_BASIS"
    WIN_PERCENTAGE_BASIS = "WIN_PERCENTAGE_BASIS"


class Division(str, Enum):
    VARSITY = "VARSITY"
    JV = "JV"


class TeamStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTERED = "REGISTERED"
    ROSTER_LOCKED = "ROSTER_LOCKED"
    COMPETING = "COMPETING"
    SUSPENDED = "SUSPENDED"
    PLAYOFF_SEEDED = "PLAYOFF_SEEDED"
    ELIMINATED = "ELIMINATED"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class SuspensionReason(str, Enum):
    FAIR_PLAY_SANCTION = "FAIR_PLAY_SANCTION"
    ROSTER_MINIMUM_BREACH = "ROSTER_MINIMUM_BREACH"
    INTEGRITY_FLOOR_BREACH = "INTEGRITY_FLOOR_BREACH"


class SlotRole(str, Enum):
    STARTER = "STARTER"
    SUB = "SUB"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    ENROLLMENT_VERIFIED = "ENROLLMENT_VERIFIED"


class SlotAcademicStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class ParticipationStatus(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    ACTIVE = "ACTIVE"
    INELIGIBLE = "INELIGIBLE"
    RELEASED = "RELEASED"


class IneligibilityReason(str, Enum):
    ACADEMIC = "ACADEMIC"
    FAIR_PLAY = "FAIR_PLAY"
    ENROLLMENT = "ENROLLMENT"


class PlayStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SERVER_READY = "SERVER_READY"
    PLAYED = "PLAYED"
    FINALIZED = "FINALIZED"
    FORFEITED = "FORFEITED"


class ResultStatus(str, Enum):
    AWAITING_REPORTS = "AWAITING_REPORTS"
    PARTIALLY_REPORTED = "PARTIALLY_REPORTED"
    CONFIRMED = "CONFIRMED"
    CONTESTED = "CONTESTED"
    ADJUDICATED = "ADJUDICATED"


class DisputeStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class DisputeReasonCode(str, Enum):
    SCORE_MISMATCH = "SCORE_MISMATCH"
    SERVER_FAULT = "SERVER_FAULT"
    INELIGIBLE_PLAYER = "INELIGIBLE_PLAYER"
    CONDUCT = "CONDUCT"


class BroadcastStatus(str, Enum):
    NONE = "NONE"
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"


class CaseSubjectType(str, Enum):
    STUDENT = "STUDENT"
    MATCH_BROADCAST = "MATCH_BROADCAST"


class CaseType(str, Enum):
    ACCOUNT_SHARING = "ACCOUNT_SHARING"
    SMURFING = "SMURFING"
    CHEAT_DETECTION = "CHEAT_DETECTION"
    SPECTATOR_CONDUCT = "SPECTATOR_CONDUCT"


class CaseSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class CaseStatus(str, Enum):
    REPORTED = "REPORTED"
    INVESTIGATING = "INVESTIGATING"
    SUSTAINED = "SUSTAINED"
    APPEALED = "APPEALED"
    DISMISSED = "DISMISSED"
    SUSTAINED_FINAL = "SUSTAINED_FINAL"
    OVERTURNED = "OVERTURNED"


class SanctionType(str, Enum):
    NONE = "NONE"
    WARNING = "WARNING"
    STUDENT_SUSPENSION = "STUDENT_SUSPENSION"
    TEAM_SUSPENSION = "TEAM_SUSPENSION"
    DISQUALIFICATION = "DISQUALIFICATION"


# --------------------------------------------------------------------------
# Entity TypedDicts (every entity carries id/created_at/updated_at/version
# per PRD §2.5)
# --------------------------------------------------------------------------
class District(TypedDict):
    id: str
    name: str
    state_code: str
    max_age_rating: str
    academic_standing_basis: str
    min_gpa: float
    probation_gpa_floor: float
    dispute_window_hours: int
    subsidy_pct: float
    subsidy_pool_cents: int
    subsidy_pool_initial_cents: int
    recruiting_dead_period_start: Optional[str]
    recruiting_dead_period_end: Optional[str]
    recruiting_contact_cap_per_window: int
    recruiting_window_days: int
    broadcast_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    district_id: str
    name: str
    nces_code: str
    enrollment_verified_through: str
    concurrent_broadcast_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict):
    id: str
    school_id: str
    full_name: str
    email: str
    certification_status: str
    background_check_expires_on: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    school_id: str
    full_name: str
    birthdate: str
    grade_level: int
    enrollment_status: str
    credits_completed: float
    latest_term_label: Optional[str]
    latest_term_gpa: Optional[float]
    latest_term_credits: Optional[float]
    prior_term_gpa: Optional[float]
    prior_term_credits: Optional[float]
    effective_gpa: Optional[float]
    academic_standing: str
    standing_basis_applied: Optional[str]
    fair_play_status: str
    showcase_status: str
    nominating_team_id: Optional[str]
    award_tier: str
    provisional_award_cents: int
    scholarship_award_cents: int
    scholarship_award_state: str
    recruiting_contact_log: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict):
    id: str
    name: str
    publisher: str
    age_rating: str
    min_player_age: int
    server_pool_id: str
    server_pool_capacity: int
    match_duration_minutes: int
    created_at: str
    updated_at: str
    version: int


class TitleApproval(TypedDict):
    id: str
    district_id: str
    title_id: str
    requested_by_school_id: str
    status: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Season(TypedDict):
    id: str
    title_id: str
    name: str
    division: str
    registration_opens_at: str
    registration_closes_at: str
    roster_lock_at: str
    regular_season_end_at: str
    age_cutoff_date: str
    max_age: int
    min_starters: int
    max_starters: int
    base_entry_fee_cents: int
    per_starter_fee_cents: int
    seeding_basis: str
    seeding_basis_applied: Optional[str]
    playoff_slots: int
    status: str
    seeding_state: str
    seed_order: List[str]
    registered_team_count: int
    match_point_pool: int
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict):
    id: str
    season_id: str
    school_id: str
    title_id: str
    coach_id: str
    name: str
    status: str
    registered_at: Optional[str]
    roster_locked_at: Optional[str]
    starter_slots_used: int
    starter_slots_available: int
    active_starter_count: int
    entry_fee_cents: int
    subsidy_granted_cents: int
    net_fee_due_cents: int
    match_points: int
    wins: int
    losses: int
    draws: int
    forfeits_charged: int
    forfeit_wins: int
    games_won: int
    games_lost: int
    game_differential: int
    seed_points: float
    seed_position: Optional[int]
    seed_stale: bool
    integrity_score: float
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RosterSlot(TypedDict):
    id: str
    team_id: str
    student_id: str
    slot_role: str
    verification_status: str
    academic_status: str
    participation_status: str
    enrollment_verified_by_user_id: Optional[str]
    academics_verified_by_user_id: Optional[str]
    enrollment_document_ref: Optional[str]
    verified_birthdate: Optional[str]
    age_at_cutoff: Optional[int]
    standing_at_verification: Optional[str]
    effective_gpa_at_verification: Optional[float]
    released_at: Optional[str]
    ineligibility_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict):
    id: str
    season_id: str
    home_team_id: str
    away_team_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    server_pool_id: str
    region_code: Optional[str]
    patch_version: Optional[str]
    play_status: str
    result_status: str
    dispute_status: str
    broadcast_status: str
    broadcast_school_id: Optional[str]
    broadcast_start_at: Optional[str]
    broadcast_end_at: Optional[str]
    spectator_strikes: int
    home_reported_home_games_won: Optional[int]
    home_reported_away_games_won: Optional[int]
    away_reported_home_games_won: Optional[int]
    away_reported_away_games_won: Optional[int]
    home_games_won: Optional[int]
    away_games_won: Optional[int]
    result_confirmed_at: Optional[str]
    dispute_deadline_at: Optional[str]
    dispute_filed_by_team_id: Optional[str]
    dispute_reason_code: Optional[str]
    winner_team_id: Optional[str]
    forfeiting_team_id: Optional[str]
    home_points_awarded: int
    away_points_awarded: int
    created_at: str
    updated_at: str
    version: int


class FairPlayCase(TypedDict):
    id: str
    team_id: str
    subject_type: str
    subject_student_id: Optional[str]
    subject_match_id: Optional[str]
    case_type: str
    evidence_ref: str
    severity: Optional[str]
    status: str
    reported_by_user_id: Optional[str]
    investigator_user_id: Optional[str]
    decider_user_id: Optional[str]
    appeal_decider_user_id: Optional[str]
    severity_weight: float
    repeat_index: Optional[int]
    applied_penalty: float
    sanction_type: str
    appeal_grounds: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
