"""Business constants for the Recreational Tennis League & Rating Administration API.

Every value here is transcribed from PRD.md; nothing is invented.
"""

# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------
API_PREFIX = "/tennis"

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_SECTION_ADMIN = "SectionAdmin"
ROLE_LEAGUE_COORDINATOR = "LeagueCoordinator"
ROLE_CAPTAIN = "Captain"
ROLE_PLAYER = "Player"
ROLE_COMMITTEE_MEMBER = "CommitteeMember"
ROLE_COMMITTEE_CHAIR = "CommitteeChair"

ALL_ROLES = [
    ROLE_SECTION_ADMIN,
    ROLE_LEAGUE_COORDINATOR,
    ROLE_CAPTAIN,
    ROLE_PLAYER,
    ROLE_COMMITTEE_MEMBER,
    ROLE_COMMITTEE_CHAIR,
]

ENTITY_BACKED_ROLES = [
    ROLE_CAPTAIN,
    ROLE_PLAYER,
    ROLE_COMMITTEE_MEMBER,
    ROLE_COMMITTEE_CHAIR,
]

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Rating ladder (PRD 2.6)
# ---------------------------------------------------------------------------
VALID_RATING_LEVELS = [2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
DYNAMIC_RATING_DECIMALS = 3
GAME_DIFFERENTIAL_COEFFICIENT = 0.50

# ---------------------------------------------------------------------------
# Section enums / defaults (PRD 2.8, 3.1)
# ---------------------------------------------------------------------------
RATING_PERIOD_OPEN_SEASON = "OPEN_SEASON"
RATING_PERIOD_RECALC_IN_PROGRESS = "RECALC_IN_PROGRESS"
RATING_PERIOD_RECALC_PUBLISHED = "RECALC_PUBLISHED"

SECTION_DEFAULTS = {
    "rating_period_status": RATING_PERIOD_OPEN_SEASON,
    "recalc_run_index": 0,
    "min_matches_for_playoff_eligibility": 3,
    "strike_limit": 3,
    "disqualification_strike_limit": 6,
    "scorecard_submission_window_hours": 48,
    "scorecard_dispute_window_hours": 24,
    "grievance_window_hours": 72,
    "recalculated_player_count": 0,
    "published_level_change_count": 0,
}

SECTION_CODE_MIN_LENGTH = 3
SECTION_CODE_MAX_LENGTH = 32
SEASON_YEAR_MIN = 2000
SEASON_YEAR_MAX = 2100

# ---------------------------------------------------------------------------
# Facility (PRD 3.1)
# ---------------------------------------------------------------------------
SURFACE_HARD = "HARD"
SURFACE_CLAY = "CLAY"
SURFACE_INDOOR_HARD = "INDOOR_HARD"
SURFACES = [SURFACE_HARD, SURFACE_CLAY, SURFACE_INDOOR_HARD]
FACILITY_DEFAULT_TURNAROUND_BUFFER_MINUTES = 30
FACILITY_DEFAULT_SURFACE = SURFACE_HARD

# ---------------------------------------------------------------------------
# League (PRD 3.1, 3.4)
# ---------------------------------------------------------------------------
TIER_LOCAL = "LOCAL"
TIER_DISTRICT = "DISTRICT"
TIER_SECTION = "SECTION"
TIERS = [TIER_LOCAL, TIER_DISTRICT, TIER_SECTION]

AGE_18_OVER = "AGE_18_OVER"
AGE_40_OVER = "AGE_40_OVER"
AGE_55_OVER = "AGE_55_OVER"
AGE_GROUPS = [AGE_18_OVER, AGE_40_OVER, AGE_55_OVER]
AGE_GROUP_MINIMUM = {AGE_18_OVER: 18, AGE_40_OVER: 40, AGE_55_OVER: 55}

FORMAT_MENS_DOUBLES = "MENS_DOUBLES"
FORMAT_WOMENS_DOUBLES = "WOMENS_DOUBLES"
FORMAT_MIXED_DOUBLES = "MIXED_DOUBLES"
FORMATS = [FORMAT_MENS_DOUBLES, FORMAT_WOMENS_DOUBLES, FORMAT_MIXED_DOUBLES]

LEAGUE_DRAFT = "DRAFT"
LEAGUE_REGISTRATION_OPEN = "REGISTRATION_OPEN"
LEAGUE_ROSTERS_LOCKED = "ROSTERS_LOCKED"
LEAGUE_IN_PLAY = "IN_PLAY"
LEAGUE_PLAYOFFS = "PLAYOFFS"
LEAGUE_COMPLETED = "COMPLETED"
LEAGUE_CANCELLED = "CANCELLED"

LEAGUE_DEFAULTS = {
    "lines_per_match": 3,
    "min_active_roster_size": 8,
    "max_roster_size": 14,
    "min_playoff_eligible_players": 6,
    "max_teams": 8,
    "advancement_slots": 1,
    "match_duration_minutes": 180,
    "allow_same_day_doubleheader": False,
    "status": LEAGUE_DRAFT,
    "registered_team_count": 0,
    "noncompliant_team_count": 0,
    "finalized_match_count": 0,
    "seeded_team_count": 0,
}

# ---------------------------------------------------------------------------
# Player (PRD 3.1, 3.2, 3.7)
# ---------------------------------------------------------------------------
GENDER_M = "M"
GENDER_F = "F"

RATING_UNRATED = "UNRATED"
RATING_SELF_RATED = "SELF_RATED"
RATING_COMPUTER_RATED = "COMPUTER_RATED"
RATING_APPEAL_GRANTED = "APPEAL_GRANTED"
RATING_COMMITTEE_ASSIGNED = "COMMITTEE_ASSIGNED"
RATING_TYPES = [
    RATING_UNRATED,
    RATING_SELF_RATED,
    RATING_COMPUTER_RATED,
    RATING_APPEAL_GRANTED,
    RATING_COMMITTEE_ASSIGNED,
]
SELF_RATING_LOCKED_TYPES = [
    RATING_COMPUTER_RATED,
    RATING_APPEAL_GRANTED,
    RATING_COMMITTEE_ASSIGNED,
]

RATING_SOURCE_SELF = "SELF"
RATING_SOURCE_COMPUTER = "COMPUTER"
RATING_SOURCE_APPEAL = "APPEAL"
RATING_SOURCE_COMMITTEE = "COMMITTEE"
RATING_SOURCE_YEAR_END_RECALC = "YEAR_END_RECALC"

PLAYER_ACTIVE = "ACTIVE"
PLAYER_STRIKE_SUSPENDED = "STRIKE_SUSPENDED"
PLAYER_DISQUALIFIED = "DISQUALIFIED"

PLAYER_BIRTH_YEAR_MIN = 1900
PLAYER_BIRTH_YEAR_MAX = 2020

PLAYER_DEFAULTS = {
    "rating_level": None,
    "rating_type": RATING_UNRATED,
    "self_rated_level": None,
    "dynamic_rating": None,
    "verified_match_count": 0,
    "verified_line_count": 0,
    "strike_count": 0,
    "status": PLAYER_ACTIVE,
    "proposed_recalc_level": None,
    "proposed_recalc_dynamic": None,
    "rating_history": [],
}

# ---------------------------------------------------------------------------
# Team / RosterSpot (PRD 3.3, 3.4)
# ---------------------------------------------------------------------------
TEAM_DRAFT = "DRAFT"
TEAM_REGISTERED = "REGISTERED"
TEAM_ROSTER_LOCKED = "ROSTER_LOCKED"
TEAM_IN_PLAY = "IN_PLAY"
TEAM_ELIMINATED = "ELIMINATED"
TEAM_ADVANCED = "ADVANCED"
TEAM_WITHDRAWN = "WITHDRAWN"
TEAM_DISQUALIFIED = "DISQUALIFIED"

SPOT_PENDING = "PENDING"
SPOT_ACTIVE = "ACTIVE"
SPOT_INELIGIBLE = "INELIGIBLE"
SPOT_REMOVED = "REMOVED"

INELIGIBLE_PLAYER_SUSPENDED = "PLAYER_SUSPENDED"
INELIGIBLE_APPEAL_GRANTED = "APPEAL_GRANTED"
INELIGIBLE_YEAR_END_RECALC = "YEAR_END_RECALC"
INELIGIBLE_GRIEVANCE_REMEDY = "GRIEVANCE_REMEDY"

# ---------------------------------------------------------------------------
# Match / Scorecard (PRD 3.5, 3.6)
# ---------------------------------------------------------------------------
STAGE_REGULAR = "REGULAR"
STAGE_PLAYOFF = "PLAYOFF"

SCHED_UNSCHEDULED = "UNSCHEDULED"
SCHED_SCHEDULED = "SCHEDULED"
SCHED_CONFIRMED = "CONFIRMED"
SCHED_PLAYED = "PLAYED"
SCHED_DEFAULTED = "DEFAULTED"
SCHED_CANCELLED = "CANCELLED"

RESULT_PENDING = "PENDING"
RESULT_REPORTED = "REPORTED"
RESULT_DISPUTED = "DISPUTED"
RESULT_VERIFIED = "VERIFIED"
RESULT_FINALIZED = "FINALIZED"
RESULT_VOIDED = "VOIDED"

SIDE_HOME = "HOME"
SIDE_AWAY = "AWAY"
SIDE_BOTH = "BOTH"

DEFAULT_KIND_NO_SHOW = "NO_SHOW"
DEFAULT_KIND_SHORT_ROSTER = "SHORT_ROSTER"
DEFAULT_KIND_LINE_MAJORITY = "LINE_MAJORITY"

SCORECARD_SUBMITTED = "SUBMITTED"
SCORECARD_DISPUTED = "DISPUTED"
SCORECARD_AMENDED = "AMENDED"
SCORECARD_VERIFIED = "VERIFIED"
SCORECARD_VOIDED = "VOIDED"

REVIEW_VERIFY = "VERIFY"
REVIEW_DISPUTE = "DISPUTE"

CREDIT_SOURCE_PLAYED = "PLAYED"
CREDIT_SOURCE_LINE_DEFAULT = "LINE_DEFAULT"
CREDIT_SOURCE_TEAM_DEFAULT = "TEAM_DEFAULT"
CREDIT_SOURCE_FORFEIT = "FORFEIT"

# Standard credited default line score (PRD 3.6)
DEFAULT_LINE_SETS = 2
DEFAULT_LINE_GAMES = 12
FORFEIT_SET_GAMES = 6

MATCH_WIN_POINTS = 3
SCORECARD_AMENDMENT_LIMIT = 2

# Year-end rating variant weights (PRD 3.2)
WEIGHT_PLAYOFF_LINE = 1.5
WEIGHT_REGULAR_LINE = 1.0
IN_SEASON_PROVISIONAL_WINDOW = 6

# ---------------------------------------------------------------------------
# Strike ledger (PRD 3.7)
# ---------------------------------------------------------------------------
STRIKE_SELF_RATE_VIOLATION = "SELF_RATE_VIOLATION"
STRIKE_INELIGIBLE_LINEUP = "INELIGIBLE_LINEUP"
STRIKE_NO_SHOW_DEFAULT = "NO_SHOW_DEFAULT"
STRIKE_SCORECARD_FALSIFICATION = "SCORECARD_FALSIFICATION"

STRIKE_WEIGHTS = {
    STRIKE_SELF_RATE_VIOLATION: 2,
    STRIKE_INELIGIBLE_LINEUP: 2,
    STRIKE_NO_SHOW_DEFAULT: 1,
    STRIKE_SCORECARD_FALSIFICATION: 3,
}

STRIKE_ACTIVE = "ACTIVE"
STRIKE_RESCINDED = "RESCINDED"

# ---------------------------------------------------------------------------
# Appeals / Grievances / Votes (PRD 3.8)
# ---------------------------------------------------------------------------
APPEAL_UP = "UP"
APPEAL_DOWN = "DOWN"

APPEAL_SUBMITTED = "SUBMITTED"
APPEAL_UNDER_REVIEW = "UNDER_REVIEW"
APPEAL_GRANTED = "GRANTED"
APPEAL_DENIED = "DENIED"

AUTO_GRANT_REQUIRED_MATCHES_COMPUTER = 3
AUTO_GRANT_REQUIRED_MATCHES_OTHER = 5
AUTO_GRANT_THRESHOLD_FLOOR = 0.20
AUTO_GRANT_THRESHOLD_CEILING = 0.50
AUTO_GRANT_DOWN_EXTRA_MARGIN = 0.10

GRIEVANCE_INELIGIBLE_LINEUP = "INELIGIBLE_LINEUP"
GRIEVANCE_SCORE_FALSIFICATION = "SCORE_FALSIFICATION"
GRIEVANCE_DEFAULT_ABUSE = "DEFAULT_ABUSE"
GRIEVANCE_RATING_VIOLATION = "RATING_VIOLATION"

GRIEVANCE_FILED = "FILED"
GRIEVANCE_UNDER_REVIEW = "UNDER_REVIEW"
GRIEVANCE_UPHELD = "UPHELD"
GRIEVANCE_DISMISSED = "DISMISSED"
GRIEVANCE_WITHDRAWN = "WITHDRAWN"

REMEDY_MATCH_FORFEIT = "MATCH_FORFEIT"
REMEDY_PLAYER_STRIKE = "PLAYER_STRIKE"
REMEDY_TEAM_DISQUALIFICATION = "TEAM_DISQUALIFICATION"

OUTCOME_UPHOLD = "UPHOLD"
OUTCOME_DISMISS = "DISMISS"
OUTCOME_GRANT = "GRANT"
OUTCOME_DENY = "DENY"

SUBJECT_RATING_APPEAL = "RATING_APPEAL"
SUBJECT_GRIEVANCE = "GRIEVANCE"

VOTE_SUPPORT = "SUPPORT"
VOTE_OPPOSE = "OPPOSE"
VOTE_ABSTAIN = "ABSTAIN"

QUORUM_MIN_SUPPORT = 2

# ---------------------------------------------------------------------------
# Year-end recalculation deltas (PRD 3.9)
# ---------------------------------------------------------------------------
RECALC_PROMOTION_DELTA = 0.25
RECALC_DEMOTION_DELTA = -0.35

# ---------------------------------------------------------------------------
# Common-field carriers (PRD 2.4)
# ---------------------------------------------------------------------------
ENTITIES_WITH_VERSION = [
    "Section",
    "League",
    "Facility",
    "Player",
    "Team",
    "RosterSpot",
    "Match",
    "Scorecard",
    "Strike",
    "RatingAppeal",
    "Grievance",
]
APPEND_ONLY_ENTITIES = ["CommitteeVote"]
