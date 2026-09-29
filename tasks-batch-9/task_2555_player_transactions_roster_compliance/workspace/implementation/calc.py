"""Deterministic calculations: window snapping, proration, dead money, tenders."""
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import UTC

CURRENT_SEASON_YEAR = 2026
MAX_PRORATION_YEARS = 5
SERVICE_DAYS_PER_SEASON = 170
PRACTICE_SQUAD_MAX_ROSTER_SERVICE_DAYS = 340
PRACTICE_SQUAD_MAX_SEASONS = 2

WINDOW_OPEN = time(13, 0, 0)
WINDOW_CLOSE = time(21, 0, 0)

ACCELERATION_CUTOFF = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
WAIVER_IRREVOCABLE_CUTOFF = datetime(2026, 8, 25, 16, 0, 0, tzinfo=UTC)

FILING_DEADLINE_HOURS = 48
WAIVER_CLEARANCE_HOURS = {"REVOCABLE": 24, "IRREVOCABLE": 48}
TENDER_RESPONSE_HOURS = 72
MEDICAL_REVIEW_HOURS = 72
MAX_CONCURRENT_MEDICAL_REVIEWS = 1
GRACE_PERIOD_HOURS = 24
PAPERWORK_GRACE_HOURS = 24
FREEZE_AFTER_CONSECUTIVE_CHECKS = 3
PHYSICAL_VALIDITY_DAYS = 14
RETURN_WINDOW_LENGTH_DAYS = 21
MAX_TRADE_ROUNDS = 3
MAX_TRANSACTION_REVISIONS = 2

MINIMUM_STAY_DAYS = {
    "INJURED_RESERVE": 21,
    "INJURED_RESERVE_RETURN_ELIGIBLE": 14,
    "NON_ROSTER_INJURY": 28,
}

MIN_TENDER_CENTS = {
    "FIRST_ROUND": 60000000,
    "SECOND_ROUND": 45000000,
    "ORIGINAL_ROUND": 30000000,
    "RIGHT_OF_FIRST_REFUSAL": 25000000,
}

LEAGUE_MINIMUM_BY_SERVICE_YEAR = {
    0: 12000000,
    1: 15000000,
    2: 18000000,
    3: 21000000,
    4: 24000000,
}

TENDER_MULTIPLIER = {
    "QUALIFYING_OFFER": None,
    "RESTRICTED_TENDER": Decimal("1.10"),
    "ARBITRATION_TENDER": Decimal("1.20"),
}

TENDER_CEILING_CENTS = 150000000

DEFAULT_ACTIVE_ROSTER_LIMIT = 26
DEFAULT_RESERVE_ROSTER_LIMIT = 4
DEFAULT_INJURED_RESERVE_LIMIT = 3
DEFAULT_PRACTICE_SQUAD_LIMIT = 6
CONVENTIONAL_SALARY_CAP_CENTS = 500000000


def in_window(instant):
    tod = instant.astimezone(UTC).time()
    return WINDOW_OPEN <= tod < WINDOW_CLOSE


def snap(instant):
    """PRD 2.5: pull a raw deadline into the daily processing window."""
    instant = instant.astimezone(UTC).replace(microsecond=0)
    tod = instant.time()
    if tod < WINDOW_OPEN:
        return instant.replace(hour=13, minute=0, second=0, microsecond=0)
    if tod < WINDOW_CLOSE:
        return instant
    nxt = instant + timedelta(days=1)
    return nxt.replace(hour=13, minute=0, second=0, microsecond=0)


def elapsed_days(start, end):
    """Whole elapsed days: floor of elapsed seconds over 86400."""
    if start is None or end is None:
        return 0
    seconds = int((end - start).total_seconds())
    if seconds <= 0:
        return 0
    return seconds // 86400


def proration(signing_bonus_cents, years):
    span = min(years, MAX_PRORATION_YEARS)
    if span < 1:
        span = 1
    annual = signing_bonus_cents // span
    final = signing_bonus_cents - annual * (span - 1)
    return span, annual, final


def current_season_share(years, start_season_year, annual_cents, final_cents):
    span = min(years, MAX_PRORATION_YEARS)
    if span < 1:
        span = 1
    seasons_elapsed = CURRENT_SEASON_YEAR - start_season_year
    if seasons_elapsed == span - 1:
        return final_cents
    if seasons_elapsed < span - 1:
        return annual_cents
    return 0


def unamortised_bonus(signing_bonus_cents, annual_cents, start_season_year):
    seasons_elapsed = CURRENT_SEASON_YEAR - start_season_year
    return signing_bonus_cents - annual_cents * seasons_elapsed


def dead_money_split(signing_bonus_cents, annual_cents, start_season_year, release_instant):
    balance = unamortised_bonus(signing_bonus_cents, annual_cents, start_season_year)
    if release_instant < ACCELERATION_CUTOFF:
        return annual_cents, balance - annual_cents
    return balance, 0


def service_years_from_days(pension_credit_days):
    return pension_credit_days // SERVICE_DAYS_PER_SEASON


def rights_class(service_years):
    if service_years >= 4:
        return "UNRESTRICTED"
    if service_years == 3:
        return "ARBITRATION_ELIGIBLE"
    if service_years >= 1:
        return "RESTRICTED"
    return "NONE"


def tender_amount(prior_base_salary_cents, tender_level, offer_type, service_years):
    lookup_years = min(service_years, 4)
    floor_cents = max(
        prior_base_salary_cents,
        MIN_TENDER_CENTS[tender_level],
        LEAGUE_MINIMUM_BY_SERVICE_YEAR[lookup_years],
    )
    multiplier = TENDER_MULTIPLIER[offer_type]
    if multiplier is None:
        amount = floor_cents
    else:
        raw = Decimal(floor_cents) * multiplier
        amount = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return min(amount, TENDER_CEILING_CENTS)
