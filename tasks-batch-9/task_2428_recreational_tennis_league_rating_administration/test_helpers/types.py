"""TypedDict shapes for every entity declared in PRD 3.

Eleven entity kinds carry the full common-field set ``id``, ``created_at``,
``updated_at`` and ``version`` (PRD 2.4).  ``CommitteeVote`` is append-only and
carries only ``id`` and ``created_at`` — its TypedDict deliberately omits
``updated_at`` and ``version``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class VersionedEntity(TypedDict):
    """Common fields shared by the eleven mutable entity kinds (PRD 2.4)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyEntity(TypedDict):
    """Common fields for append-only rows: no ``updated_at``, no ``version``."""

    id: str
    created_at: str


class Section(VersionedEntity):
    code: str
    name: str
    season_year: int
    rating_period_status: str
    recalc_run_index: int
    min_matches_for_playoff_eligibility: int
    strike_limit: int
    disqualification_strike_limit: int
    scorecard_submission_window_hours: int
    scorecard_dispute_window_hours: int
    grievance_window_hours: int
    recalculated_player_count: int
    published_level_change_count: int


class League(VersionedEntity):
    section_id: str
    parent_league_id: Optional[str]
    tier: str
    ntrp_level: float
    age_group: str
    format: str
    lines_per_match: int
    min_active_roster_size: int
    max_roster_size: int
    min_playoff_eligible_players: int
    max_teams: int
    advancement_slots: int
    match_duration_minutes: int
    allow_same_day_doubleheader: bool
    registration_opens_at: str
    registration_closes_at: str
    roster_lock_at: str
    season_end_at: str
    status: str
    registered_team_count: int
    noncompliant_team_count: int
    finalized_match_count: int
    seeded_team_count: int


class Facility(VersionedEntity):
    section_id: str
    name: str
    court_count: int
    turnaround_buffer_minutes: int
    surface: str


class Player(VersionedEntity):
    section_id: str
    full_name: str
    birth_year: int
    gender: str
    rating_level: Optional[float]
    rating_type: str
    self_rated_level: Optional[float]
    dynamic_rating: Optional[float]
    verified_match_count: int
    verified_line_count: int
    strike_count: int
    status: str
    proposed_recalc_level: Optional[float]
    proposed_recalc_dynamic: Optional[float]
    rating_history: List[Dict[str, Any]]


class Team(VersionedEntity):
    league_id: str
    captain_player_id: str
    name: str
    home_facility_id: str
    advanced_from_team_id: Optional[str]
    status: str
    active_roster_size: int
    playoff_eligible_roster_size: int
    roster_compliant: bool
    matches_won: int
    matches_lost: int
    lines_won: int
    lines_lost: int
    sets_won: int
    sets_lost: int
    games_won: int
    games_lost: int
    standings_points: int
    playoff_seed: Optional[int]


class RosterSpot(VersionedEntity):
    team_id: str
    player_id: str
    status: str
    level_at_add: Optional[float]
    verified_match_count: int
    playoff_eligible: bool
    ineligible_reason: Optional[str]
    source_strike_id: Optional[str]


class Match(VersionedEntity):
    league_id: str
    home_team_id: str
    away_team_id: str
    stage: str
    round_number: int
    facility_id: Optional[str]
    scheduled_start_at: Optional[str]
    scheduled_end_at: Optional[str]
    courts_required: Optional[int]
    schedule_status: str
    result_status: str
    winner_team_id: Optional[str]
    home_lines_won: int
    away_lines_won: int
    home_sets_won: int
    away_sets_won: int
    home_games_won: int
    away_games_won: int
    line_results: List[Dict[str, Any]]
    default_side: Optional[str]
    default_kind: Optional[str]
    verified_at: Optional[str]


class Scorecard(VersionedEntity):
    match_id: str
    submitted_by_captain_player_id: str
    submitted_by_team_id: str
    verified_by_captain_player_id: Optional[str]
    status: str
    lines: List[Dict[str, Any]]
    amendment_count: int
    dispute_reason: Optional[str]
    disputed_line_numbers: List[int]
    verified_at: Optional[str]


class Strike(VersionedEntity):
    player_id: str
    match_id: Optional[str]
    source_grievance_id: Optional[str]
    kind: str
    weight: int
    status: str
    reason: str
    rescinded_reason: Optional[str]


class RatingAppeal(VersionedEntity):
    player_id: str
    direction: str
    requested_level: float
    reason: str
    status: str
    rating_level_at_filing: Optional[float]
    dynamic_rating_at_filing: Optional[float]
    verified_match_count_at_filing: int
    strike_count_at_filing: int
    auto_grant_eligible: bool
    support_vote_count: int
    oppose_vote_count: int
    decided_by_chair_player_id: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]
    granted_level: Optional[float]


class Grievance(VersionedEntity):
    league_id: str
    filed_by_captain_player_id: str
    against_team_id: str
    subject_match_id: Optional[str]
    kind: str
    status: str
    remedy: Optional[str]
    remedy_target_player_id: Optional[str]
    statement: str
    support_vote_count: int
    oppose_vote_count: int
    decided_by_chair_player_id: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]


class CommitteeVote(AppendOnlyEntity):
    """Append-only: no ``updated_at`` and no ``version`` (PRD 2.4)."""

    subject_type: str
    subject_id: str
    voter_player_id: str
    vote: str
    note: Optional[str]
