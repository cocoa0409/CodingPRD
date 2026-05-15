"""Global constants from SCAFFOLD §1.3 `global_constants` and PRD §2.7.

Every magic-number literal the rest of the codebase needs comes from here
so the PRD-pinned values are the single source of truth.
"""
from __future__ import annotations

from decimal import Decimal

# §1.3 global_constants block.
STAGE_CHANGEOVER_BUFFER_SECONDS: int = 1800
TRAVEL_HOURS_MIN: int = 4
TEAM_WARMUP_MINUTES: int = 10
TEAM_HANDOFF_SECONDS: int = 600
FESTIVAL_CLOSE_GRACE_SECONDS: int = 3600
REHEARSAL_GRACE_SECONDS: int = 600
IDEMPOTENCY_WINDOW_SECONDS: int = 86400
ABS_TOLERANCE_CENTS: int = 0
ADMIN_FEE_RATE_FINAL: Decimal = Decimal("0.05")
PERCENT_PRECISION: int = 2
CENT_PRECISION: int = 0
HEADLINER_BONUS: int = 100
MAIN_BONUS: int = 50
OPENER_BONUS: int = 30
SURPRISE_BONUS: int = 10
TRAVEL_WEIGHT: Decimal = Decimal("0.1")
MULTI_FESTIVAL_CONFLICT_PENALTY: int = 20
RIDER_WEIGHT: int = 2
RIDER_CAP: int = 5
TRAVEL_BUFFER_MAX_MINUTES: int = 1440
NON_NEGATIVE_FLOOR: int = 0
SPONSOR_PAYOUT_RATE_MILS_DEFAULT: int = 25
WATERFALL_TIER_ORDER: tuple[str, ...] = ("TITLE", "GOLD", "SILVER")
HEADLINER_MIN_BLOCKING_RIDERS: int = 1
MAX_PROGRAM_ITEMS_PER_FESTIVAL: int = 500

# Fixed enumerations.
ROLE_NAMES: frozenset[str] = frozenset(
    {
        "FestivalProducer",
        "ArtistLiaison",
        "StageManager",
        "TicketingAdmin",
        "SponsorshipAdmin",
        "AuditViewer",
        "PlatformAdmin",
    }
)

AUDIT_LOG_ALLOWLIST: frozenset[str] = frozenset(
    {"AuditViewer", "FestivalProducer", "PlatformAdmin"}
)

SYNC_TARGETS: tuple[str, ...] = ("ticketing", "im", "broadcasting", "sponsor")

EXPOSURE_KINDS: frozenset[str] = frozenset(
    {"stage_name", "screen_time", "artist_mention", "branded_zone"}
)

AUDIT_CATEGORIES: frozenset[str] = frozenset(
    {
        "SCHEDULE_CHANGE",
        "EXPOSURE",
        "SYNC_ACK",
        "CLOCK_TICK",
        "STATE_TRANSITION",
        "OCC_CONFLICT",
    }
)
