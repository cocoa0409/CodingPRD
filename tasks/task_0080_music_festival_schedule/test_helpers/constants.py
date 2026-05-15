"""Domain constants drawn verbatim from the PRD §2.7, §2.8, and §3.5 prose.

These are the numeric and string literals the implementation must honour by
name and value.  Tests import them from this module rather than hard-coding
the numbers inline so a typo in any test cannot drift away from the
canonical pin.

The PRD prose names each of these constants by the same identifier the
test fixture asserts against:

  - The travel-buffer minimum default                      TRAVEL_HOURS_MIN
  - The stage changeover buffer default                     STAGE_CHANGEOVER_BUFFER_SECONDS
  - The team warmup-gap default                             TEAM_WARMUP_MINUTES
  - The engineer-to-front-of-house handoff before the act   TEAM_HANDOFF_SECONDS
  - The grace window before the rehearsal auto-archives     REHEARSAL_GRACE_SECONDS
  - The grace window before the festival auto-closes        FESTIVAL_CLOSE_GRACE_SECONDS
  - The idempotency-key lifetime                            IDEMPOTENCY_WINDOW_SECONDS
  - The absolute refund-magnitude tolerance                 ABS_TOLERANCE_CENTS
  - The external admin-fee deduction rate                   ADMIN_FEE_RATE_FINAL
  - The two-decimal-place percent rounding                  PERCENT_PRECISION
  - The cents-precision floor                               CENT_PRECISION
  - The five tier-bonus constants and the three weights
  - The default sponsor-payout rate in mills per unit       SPONSOR_PAYOUT_RATE_MILS_DEFAULT
  - The fixed waterfall tier ordering                        WATERFALL_TIER_ORDER
  - The travel-buffer upper clamp in minutes                TRAVEL_BUFFER_MAX_MINUTES
  - The rider-count upper clamp                             RIDER_CAP
  - The non-negative floor on the slot-priority raw score   NON_NEGATIVE_FLOOR
  - The cardinality minimum on HEADLINER blocking riders    HEADLINER_MIN_BLOCKING_RIDERS
  - The per-festival upper bound on program-item count      MAX_PROGRAM_ITEMS_PER_FESTIVAL

The literal four-target list and the fixed waterfall tier ordering are the
two string-valued constants the PRD also pins, and the four catalog-kind
literals are the keys of the exposure-catalog dictionary the PRD §2.8
declares.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Dict, List


# ---------------------------------------------------------------------------
# Numeric thresholds, all integer-valued unless noted.
# ---------------------------------------------------------------------------

THRESHOLDS: Dict[str, int] = {
    "STAGE_CHANGEOVER_BUFFER_SECONDS": 1800,        # 30 minutes, per-stage default
    "TRAVEL_HOURS_MIN": 4,                           # 4 hours, the per-artist default
    "TEAM_WARMUP_MINUTES": 10,                       # 10 minutes, per-team default
    "TEAM_WARMUP_SECONDS": 10 * 60,                  # 600 seconds, the same value
    "TEAM_HANDOFF_SECONDS": 600,                     # 10 minutes, the sound-check-end to act-start gap
    "REHEARSAL_GRACE_SECONDS": 600,                  # 10 minutes, the rehearsal-end to auto-archive gap
    "FESTIVAL_CLOSE_GRACE_SECONDS": 3600,            # 60 minutes, the festival-end to auto-close gap
    "IDEMPOTENCY_WINDOW_SECONDS": 86400,             # 24 hours, the idempotency-key lifetime
    "ABS_TOLERANCE_CENTS": 0,                        # strict cents-tolerance on the refund-magnitude check
    "PERCENT_PRECISION": 2,                          # the two-decimal-place pct rounding
    "CENT_PRECISION": 0,                             # the integer-cents convention
    "HEADLINER_BONUS": 100,                          # the slot-priority HEADLINER bonus
    "MAIN_BONUS": 50,                                # the slot-priority MAIN bonus
    "OPENER_BONUS": 30,                              # the slot-priority OPENER bonus
    "SURPRISE_BONUS": 10,                            # the slot-priority SURPRISE bonus
    "MULTI_FESTIVAL_CONFLICT_PENALTY": 20,           # per-conflict subtraction on the priority score
    "RIDER_WEIGHT": 2,                               # each (clamped) rider contributes two points
    "RIDER_CAP": 5,                                  # the upper clamp on the rider count
    "TRAVEL_BUFFER_MAX_MINUTES": 1440,               # 24-hour upper clamp on the travel-buffer term
    "NON_NEGATIVE_FLOOR": 0,                         # the floor on the raw score
    "SPONSOR_PAYOUT_RATE_MILS_DEFAULT": 25,          # default rate in mills (thousandths of a cent) per unit
    "HEADLINER_MIN_BLOCKING_RIDERS": 1,              # cardinality minimum on HEADLINER announcement
    "MAX_PROGRAM_ITEMS_PER_FESTIVAL": 500,           # hard cap on items per festival
    "TRAVEL_HOURS_TO_SECONDS": 3600,                 # the hours-to-seconds multiplier in the buffer check
}

# Fractional-valued constant: the admin-fee rate the external ticketing
# system charges per refunded ticket, the gap that distinguishes the
# provisional from the final refund cents totals.
ADMIN_FEE_RATE_FINAL: Decimal = Decimal("0.05")

# The TRAVEL_WEIGHT is the per-minute multiplier on the travel-buffer term
# of the slot-priority formula, fractional and applied in exact decimal.
TRAVEL_WEIGHT: Decimal = Decimal("0.1")

# The fixed evaluation order of the sponsor-allocation waterfall (the apex
# tier first, the mid tier second, the bottom tier third).
WATERFALL_TIER_ORDER: List[str] = ["TITLE", "GOLD", "SILVER"]

# The four-element ordered list of the canonical sync-envelope targets.
CANONICAL_SYNC_TARGETS: List[str] = ["ticketing", "im", "broadcasting", "sponsor"]

# The four-element exposure-catalog kind set the PRD §2.8 declares as the
# fixed key set of the catalog dictionary the festival's producer seeds.
CATALOG_KINDS: List[str] = ["stage_name", "screen_time", "artist_mention", "branded_zone"]

# The six-element audit-event-category enum the PRD §2.8 declares.
AUDIT_CATEGORIES: List[str] = [
    "SCHEDULE_CHANGE", "EXPOSURE", "SYNC_ACK",
    "CLOCK_TICK", "STATE_TRANSITION", "OCC_CONFLICT",
]

# The three-role audit-log-read allowlist the PRD §2.1 declares.
AUDIT_VIEWER_ROLES: List[str] = ["AuditViewer", "FestivalProducer", "PlatformAdmin"]

# Pagination defaults and bounds the PRD §2.3 declares.
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_DEFAULT_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Test-side default field values used by factories.py when the caller does
# not override.  These are convenience defaults internal to the test suite
# — the PRD itself does not pin these specific strings.  They exist only
# to spare every test the boilerplate of naming a stage and a venue and
# so on.  Any test that cares about a specific value passes it as an
# override.
# ---------------------------------------------------------------------------

TEST_DEFAULTS: Dict[str, object] = {
    "FESTIVAL_NAME_PREFIX": "TestFest",
    "VENUE_NAME": "Test Venue",
    "STAGE_NAME_PREFIX": "Main",
    "TEAM_NAME_PREFIX": "Crew",
    "HEAD_ENGINEER_NAME": "Pat Engineer",
    "EQUIPMENT_KIT_CODE_PREFIX": "KIT",
    "EQUIPMENT_KIT_TOTAL_UNITS": 2,
    "ZONE_NAME": "Zone-Main",
    "ZONE_CAPACITY": 100,
    "UNIT_PRICE_CENTS": 12000,         # canonical refund-example $120.00 — see PRD §3.4 worked example
    "TICKET_COUNT_DEFAULT": 3,         # canonical refund-example outstanding count of 3
    "FESTIVAL_DAY_COUNT_DEFAULT": 3,   # canonical 3-day window so the per-day divisor is 3
    "ARTIST_HOME_CITY": "Local",
    "VERSION_LABEL_PREFIX": "v",
    "SPONSOR_CONTRACTED_UNITS": 10,
    "REHEARSAL_ROOM_NAME": "RoomA",
    "PROGRAM_VERSION_LABEL": "v1-initial",
    "REASON_TEXT_DEFAULT": "default-test-reason",
}


# The day-in-seconds constant the festival_day_count ceiling division uses.
DAY_SECONDS: int = 86400


# ---------------------------------------------------------------------------
# The §3.6-canonical-worked-example refund literals.  These come from the
# §3.4 narrative where unit_price_cents=12000 and festival_day_count=3 and
# outstanding=3.  The forward-looking pro-rata is per-ticket cents
# round_half_up(12000 * 1 / 3) = 4000 cents, the across-three-tickets
# product is 12000 cents, and the externally-confirmed final after the
# 5% admin fee is round_half_up(12000 * (1 - 0.05)) = 11400 cents (the
# 600-cents admin fee being half-up of 12000 * 0.05).
# ---------------------------------------------------------------------------

CANONICAL_PROVISIONAL_REFUND_CENTS: int = 12000
CANONICAL_FINAL_REFUND_CENTS: int = 11400
CANONICAL_ADMIN_FEE_CENTS: int = CANONICAL_PROVISIONAL_REFUND_CENTS - CANONICAL_FINAL_REFUND_CENTS  # 600


# The PRD §3.5 worked priority-score literal: a HEADLINER with a 600-minute
# travel buffer, one ±24-hour external commitment conflict, and seven
# riders (clamped to RIDER_CAP=5) yields the score 100 + 60.0 - 20 + 10
# = 150, max with zero = 150, rounded half-up to two decimals = 150.00.
CANONICAL_HEADLINER_SCORE: float = 150.00

# The PRD §3.6 sponsor-payout worked example: three lines each delivering
# one unit at the default twenty-five-mils-per-unit rate gives a
# pinned-order answer of 8 cents (the unrounded 0.075-cents total rounds
# half-up to 0.08, surfacing as integer 8 cents), versus the rejected
# per-line-rounded alternative that would yield 9 cents.
CANONICAL_PINNED_PAYOUT_CENTS: int = 8
ALTERNATIVE_UNPINNED_PAYOUT_CENTS: int = 9


# The PRD §3.6 waterfall worked example: a branded-zone pool of 10 with
# Title=5, Gold-aaa=2, Gold-bbb=2, Silver-aaa=1, Silver-bbb=0, Silver-ccc=0
# in the pinned tier-then-rank-then-external-id-lexicographic order.
CANONICAL_WATERFALL_ACTUAL_UNITS: Dict[str, int] = {
    "title-aaa":  5,
    "gold-aaa":   2,
    "gold-bbb":   2,
    "silver-aaa": 1,
    "silver-bbb": 0,
    "silver-ccc": 0,
}

# The PRD §3.6 projected-vs-actual divergence on the canonical 10-unit
# Gold tier with two tied-item cancellations: projected is 8/10 = 80.00
# and the post-event actual after seven of the eight surviving allocations
# deliver is 7/10 = 70.00.  The ten-percentage-point gap on the same row
# is the dual-variant evidence.
CANONICAL_PROJECTED_PCT: float = 80.00
CANONICAL_ACTUAL_PCT: float = 70.00


__all__ = [
    "THRESHOLDS", "ADMIN_FEE_RATE_FINAL", "TRAVEL_WEIGHT",
    "WATERFALL_TIER_ORDER", "CANONICAL_SYNC_TARGETS", "CATALOG_KINDS",
    "AUDIT_CATEGORIES", "AUDIT_VIEWER_ROLES",
    "PAGINATION_DEFAULT_LIMIT", "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT", "PAGINATION_DEFAULT_OFFSET",
    "TEST_DEFAULTS", "DAY_SECONDS",
    "CANONICAL_PROVISIONAL_REFUND_CENTS", "CANONICAL_FINAL_REFUND_CENTS",
    "CANONICAL_ADMIN_FEE_CENTS", "CANONICAL_HEADLINER_SCORE",
    "CANONICAL_PINNED_PAYOUT_CENTS", "ALTERNATIVE_UNPINNED_PAYOUT_CENTS",
    "CANONICAL_WATERFALL_ACTUAL_UNITS",
    "CANONICAL_PROJECTED_PCT", "CANONICAL_ACTUAL_PCT",
]
