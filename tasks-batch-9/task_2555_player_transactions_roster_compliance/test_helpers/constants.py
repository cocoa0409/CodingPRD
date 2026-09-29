"""Domain constants drawn from the Player Transactions & Roster Compliance PRD.

Every literal here is quoted from the PRD so that test modules never re-derive a
business rule. Time helpers exist only to *build* setup timestamps; expected
values in assertions are always written as explicit literals.
"""

from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Logical clock and the daily processing window (PRD 2.5)
# ---------------------------------------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
PROCESSING_WINDOW_OPEN_HOUR = 13
PROCESSING_WINDOW_CLOSE_HOUR = 21
PROCESSING_WINDOW_OPEN_TIME = "13:00:00"
PROCESSING_WINDOW_CLOSE_TIME = "21:00:00"

# A safe in-window instant used whenever a test only needs "the window is open".
IN_WINDOW_TIME = "14:00:00"

CURRENT_SEASON_YEAR = 2026

# ---------------------------------------------------------------------------
# Filing cycle (PRD 3.3)
# ---------------------------------------------------------------------------
FILING_DEADLINE_HOURS = 48
MAX_TRANSACTION_REVISIONS = 2
TRANSACTION_TYPES_REQUIRING_PHYSICAL = ("SIGNING", "IR_ACTIVATION")

# ---------------------------------------------------------------------------
# Contract economics (PRD 3.4)
# ---------------------------------------------------------------------------
MAX_PRORATION_YEARS = 5
ACCELERATION_CUTOFF = "2026-09-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Medical dimension (PRD 3.5)
# ---------------------------------------------------------------------------
PHYSICAL_VALIDITY_DAYS = 14
MEDICAL_REVIEW_WINDOW_HOURS = 72
MAX_CONCURRENT_MEDICAL_REVIEWS = 1
RETURN_WINDOW_LENGTH_DAYS = 21
MINIMUM_STAY_DAYS = {
    "INJURED_RESERVE": 21,
    "INJURED_RESERVE_RETURN_ELIGIBLE": 14,
    "NON_ROSTER_INJURY": 28,
}

# ---------------------------------------------------------------------------
# Waiver wire (PRD 3.6)
# ---------------------------------------------------------------------------
WAIVER_IRREVOCABLE_CUTOFF = "2026-08-25T16:00:00Z"
WAIVER_CLEARANCE_HOURS = {"REVOCABLE": 24, "IRREVOCABLE": 48}

# ---------------------------------------------------------------------------
# Trades (PRD 3.7)
# ---------------------------------------------------------------------------
MAX_TRADE_ROUNDS = 3
DRAFT_PICK_YEAR_MIN = 2027
DRAFT_PICK_YEAR_MAX = 2031
DRAFT_PICK_ROUND_MIN = 1
DRAFT_PICK_ROUND_MAX = 7

# ---------------------------------------------------------------------------
# Tenders and qualifying offers (PRD 3.8)
# ---------------------------------------------------------------------------
TENDER_DEADLINE_HOURS = 72
TENDER_CEILING_CENTS = 150_000_000
TENDER_LEVEL_MINIMUM_CENTS = {
    "FIRST_ROUND": 60_000_000,
    "SECOND_ROUND": 45_000_000,
    "ORIGINAL_ROUND": 30_000_000,
    "RIGHT_OF_FIRST_REFUSAL": 25_000_000,
}
TENDER_SERVICE_YEAR_MINIMUM_CENTS = {
    0: 12_000_000,
    1: 15_000_000,
    2: 18_000_000,
    3: 21_000_000,
    4: 24_000_000,  # four or more accrued seasons
}
TENDER_MULTIPLIERS = {
    "QUALIFYING_OFFER": 1.00,
    "RESTRICTED_TENDER": 1.10,
    "ARBITRATION_TENDER": 1.20,
}

# ---------------------------------------------------------------------------
# Service accrual and future contract rights (PRD 3.2)
# ---------------------------------------------------------------------------
SERVICE_DAYS_PER_SEASON = 170
IR_ROSTER_CREDIT_FACTOR = 0.5
PRACTICE_SQUAD_MAX_SERVICE_DAYS = 340
PRACTICE_SQUAD_MAX_SEASONS = 2

# ---------------------------------------------------------------------------
# Compliance sweep and the posture ladder (PRD 3.9)
# ---------------------------------------------------------------------------
GRACE_PERIOD_HOURS = 24
FREEZE_AFTER_CONSECUTIVE_CHECKS = 3
UNFILED_PAPERWORK_GRACE_HOURS = 24
VIOLATION_CODE_ORDER = (
    "ACTIVE_ROSTER_OVER_LIMIT",
    "RESERVE_OVER_LIMIT",
    "IR_OVER_LIMIT",
    "PRACTICE_SQUAD_OVER_LIMIT",
    "CAP_OVER_LIMIT",
    "INELIGIBLE_PRACTICE_SQUAD_PLAYER",
    "UNFILED_INJURY_PAPERWORK",
)
BLOCKING_COMPLIANCE_POSTURES = ("NON_COMPLIANT", "TRANSACTION_FROZEN")

# ---------------------------------------------------------------------------
# Clubs (PRD 3.1)
# ---------------------------------------------------------------------------
STANDARD_SALARY_CAP_LIMIT_CENTS = 500_000_000
DEFAULT_ACTIVE_ROSTER_LIMIT = 26
DEFAULT_RESERVE_ROSTER_LIMIT = 4
DEFAULT_INJURED_RESERVE_LIMIT = 3
DEFAULT_PRACTICE_SQUAD_LIMIT = 6
ROSTERED_DESIGNATIONS = ("ACTIVE", "RESERVE", "INJURED_RESERVE", "PRACTICE_SQUAD")

PROVISIONAL_CONTRACT_STATUSES = ("PENDING_APPROVAL", "ACTIVE")
PROVISIONAL_ALLOCATION_KINDS = ("ROSTER_BONUS", "PERFORMANCE_LTBE")
FINAL_ALLOCATION_KINDS = (
    "ROSTER_BONUS",
    "PERFORMANCE_LTBE",
    "PERFORMANCE_NLTBE",
)

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
ROLES = ("LeagueOfficer", "TeamCapAnalyst", "TeamMedicalOfficer", "PlayerAgent")
PLAYER_POSITIONS = ("QB", "RB", "WR", "OL", "DL", "LB", "DB", "K")
ROSTER_DESIGNATIONS = (
    "UNROSTERED",
    "ACTIVE",
    "RESERVE",
    "INJURED_RESERVE",
    "PRACTICE_SQUAD",
    "WAIVED_PENDING",
)
MEDICAL_STATUSES = ("CLEARED", "PHYSICAL_PENDING", "FAILED_PHYSICAL", "REHAB")
CONTRACT_RIGHTS_CLASSES = (
    "NONE",
    "RESTRICTED",
    "ARBITRATION_ELIGIBLE",
    "UNRESTRICTED",
)
COMPLIANCE_STATUSES = (
    "COMPLIANT",
    "GRACE",
    "NON_COMPLIANT",
    "TRANSACTION_FROZEN",
)
TRANSACTION_TYPES = (
    "SIGNING",
    "RELEASE",
    "DESIGNATION_CHANGE",
    "IR_PLACEMENT",
    "IR_ACTIVATION",
    "PRACTICE_SQUAD_ELEVATION",
)
TRANSACTION_STATUSES = ("DRAFT", "FILED", "APPROVED", "REJECTED", "VOIDED")
CONTRACT_STATUSES = ("PENDING_APPROVAL", "ACTIVE", "TERMINATED", "VOIDED")
CONTRACT_OPTION_TYPES = ("NONE", "TEAM_OPTION", "PLAYER_OPTION")
CONTRACT_OPTION_STATUSES = (
    "NOT_APPLICABLE",
    "PENDING",
    "EXERCISED",
    "DECLINED",
    "LAPSED",
)
TERMINATION_REASONS = ("RELEASE_CLEARED", "OPTION_DECLINED", "OPTION_LAPSED")
BONUS_ALLOCATION_KINDS = (
    "SIGNING_PRORATION",
    "ROSTER_BONUS",
    "PERFORMANCE_LTBE",
    "PERFORMANCE_NLTBE",
)
BONUS_ALLOCATION_STATUSES = ("SCHEDULED", "EARNED", "FORFEITED", "ACCELERATED")
WAIVER_STATUSES = ("PENDING", "WITHDRAWN", "CLAIMED", "CLEARED")
WAIVER_REVOCABILITY = ("REVOCABLE", "IRREVOCABLE")
WAIVER_CLAIM_STATUSES = ("SUBMITTED", "AWARDED", "LOST", "INVALIDATED")
TRADE_STATUSES = (
    "PROPOSED",
    "COUNTERED",
    "ACCEPTED",
    "MEDICAL_REVIEW",
    "EXECUTED",
    "VOIDED",
)
TRADE_CLAUSE_TYPES = ("NONE", "PICK_CONDITIONAL", "PHYSICAL_CONTINGENT")
TRADE_VOID_REASONS = (
    "ROUND_LIMIT_EXCEEDED",
    "FAILED_PHYSICAL",
    "MEDICAL_WINDOW_EXPIRED",
)
TRADE_ASSET_KINDS = ("CONTRACT", "DRAFT_PICK", "CASH_CONSIDERATION")
TRADE_ASSET_DIRECTIONS = ("TO_COUNTERPARTY", "TO_INITIATOR")
TRADE_ASSET_STATUSES = ("PROPOSED", "TRANSFERRED", "RETURNED")
TENDER_OFFER_TYPES = (
    "QUALIFYING_OFFER",
    "RESTRICTED_TENDER",
    "ARBITRATION_TENDER",
)
TENDER_LEVELS = (
    "FIRST_ROUND",
    "SECOND_ROUND",
    "ORIGINAL_ROUND",
    "RIGHT_OF_FIRST_REFUSAL",
)
TENDER_STATUSES = ("ISSUED", "ACCEPTED", "DECLINED", "LAPSED")
INJURY_DESIGNATION_TYPES = (
    "INJURED_RESERVE",
    "INJURED_RESERVE_RETURN_ELIGIBLE",
    "NON_ROSTER_INJURY",
)
INJURY_DESIGNATION_STATUSES = (
    "PENDING_PAPERWORK",
    "PAPERWORK_FILED",
    "ACTIVE",
    "RETURN_WINDOW_OPEN",
    "CLOSED",
    "VOIDED",
)
OPEN_INJURY_DESIGNATION_STATUSES = (
    "PENDING_PAPERWORK",
    "PAPERWORK_FILED",
    "ACTIVE",
    "RETURN_WINDOW_OPEN",
)
EXAM_TYPES = ("ENTRY_PHYSICAL", "TRADE_PHYSICAL", "RETURN_PHYSICAL")
EXAM_STATUSES = ("SCHEDULED", "PASSED", "FAILED", "EXPIRED")
EXAM_RESULTS = ("PASSED", "FAILED")
CHECK_MODES = ("EVENT", "SWEEP")


# ---------------------------------------------------------------------------
# Timestamp helpers — used to *construct* setup instants, never to derive an
# expected value that a test then asserts.
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant (with or without fractional seconds)."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC instant with whole seconds."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def instant(year: int, month: int, day: int, hour: int = 0,
            minute: int = 0, second: int = 0) -> str:
    """Build an ISO 8601 UTC instant string from calendar parts."""
    return format_instant(
        datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    )


def shift(value: str, *, days: int = 0, hours: int = 0,
          minutes: int = 0, seconds: int = 0) -> str:
    """Offset an ISO 8601 UTC instant by a whole-second delta."""
    moment = parse_instant(value) + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds
    )
    return format_instant(moment)


def in_window_on(year: int, month: int, day: int, hour: int = 14,
                 minute: int = 0, second: int = 0) -> str:
    """An instant on the given date that sits inside the processing window."""
    assert PROCESSING_WINDOW_OPEN_HOUR <= hour < PROCESSING_WINDOW_CLOSE_HOUR, (
        "helper is only for instants inside the processing window"
    )
    return instant(year, month, day, hour, minute, second)
