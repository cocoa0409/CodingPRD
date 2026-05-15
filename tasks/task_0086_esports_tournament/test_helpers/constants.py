"""Domain constants sourced from PRD §3 calculations.

These centralise numeric thresholds, currency conversion rates, and tax
brackets so test code can reference them by symbolic name. Generic
NON_EXISTENT_UUID is re-exported from the framework via __init__.
"""
from __future__ import annotations
from typing import Dict, List


# ---------------------------------------------------------------------------
# Prize allocation (PRD §3.1 / §3.6)
# ---------------------------------------------------------------------------
MVP_BPS: int = 500   # 5% in basis points — required by PRD §3.1 sum invariant.
TOTAL_BPS: int = 10000


# ---------------------------------------------------------------------------
# Appeal cycle (PRD §3.5)
# ---------------------------------------------------------------------------
MAX_APPEALS: int = 1
APPEAL_WINDOW_HOURS: int = 72


# ---------------------------------------------------------------------------
# Contagion risk (PRD §3.5)
# ---------------------------------------------------------------------------
RISK_HALFLIFE_DAYS: int = 30
AUTO_DISQUALIFY_THRESHOLD: int = 50

BASE_WEIGHT: Dict[str, int] = {
    "WARNING": 1,
    "FINE": 3,
    "FORFEIT": 5,
    "DISQUALIFICATION": 10,
}

CLASSIFICATION_MULTIPLIER: Dict[str, float] = {
    "LATENCY": 1.0,
    "UNSPORTSMANLIKE_CONDUCT": 1.5,
    "RULE_VIOLATION": 2.0,
    "CHEATING_SUSPICION": 3.0,
}


# ---------------------------------------------------------------------------
# Draft + match (PRD §3.4)
# ---------------------------------------------------------------------------
DISCONNECT_GRACE_SECONDS: int = 60
REFEREE_BUFFER_MINUTES: int = 15
ROSTER_MIN_MAIN_PLAYERS: int = 5


# ---------------------------------------------------------------------------
# Payout floor (PRD §3.6)
# ---------------------------------------------------------------------------
MIN_PAYOUT_FLOOR_CENTS: int = 100


# ---------------------------------------------------------------------------
# Tax brackets per jurisdiction (PRD §3.6)
# ---------------------------------------------------------------------------
TAX_BRACKETS: Dict[str, List[Dict[str, int]]] = {
    "US": [
        {"up_to_cents": 100_000_000, "rate_bps": 2400},
        {"up_to_cents": 999_999_999_999, "rate_bps": 3700},
    ],
    "DE": [
        {"up_to_cents": 5_000_000_000, "rate_bps": 4500},
    ],
    "KR": [
        {"up_to_cents": 100_000_000, "rate_bps": 2200},
        {"up_to_cents": 500_000_000, "rate_bps": 3500},
        {"up_to_cents": 999_999_999_999, "rate_bps": 4500},
    ],
    "CN": [
        {"up_to_cents": 999_999_999_999, "rate_bps": 2000},
    ],
}


# ---------------------------------------------------------------------------
# Foreign-exchange rates (PRD §3.6)
# ---------------------------------------------------------------------------
FX_RATE: Dict[str, Dict[str, float]] = {
    "USD": {"USD": 1.0, "EUR": 0.92, "KRW": 1350.0, "CNY": 7.20},
    "EUR": {"USD": 1.09, "EUR": 1.0, "KRW": 1465.0, "CNY": 7.83},
    "KRW": {"USD": 0.00074, "EUR": 0.00068, "KRW": 1.0, "CNY": 0.0053},
    "CNY": {"USD": 0.139, "EUR": 0.128, "KRW": 187.5, "CNY": 1.0},
}


# ---------------------------------------------------------------------------
# Test scaffolding scalars
# ---------------------------------------------------------------------------
TEST_DEFAULTS: Dict[str, object] = {
    # Tournament basics
    "TOURNAMENT_NAME": "Test Tournament",
    "TOURNAMENT_FORMAT": "DOUBLE_ELIMINATION",
    "TOURNAMENT_REGION": "GLOBAL",
    "ENTRY_FEE_CENTS": 10_000,           # $100.00 USD
    "ENTRY_FEE_CURRENCY": "USD",
    "BASE_PRIZE_POOL_CENTS": 1_000_000,  # $10,000.00 USD
    "MAX_TEAMS": 16,
    "MIN_AGE": 16,
    "MIN_TEAM_RANKING_POINTS": 0,
    "REQUIRED_REFEREE_LEVEL": "L1",
    "SEEDING_RULE": "RANKING",
    # Deadlines (relative — fixtures will set absolute ISO times).
    "ROSTER_LOCK_OFFSET_DAYS": 30,
    "REGISTRATION_OFFSET_DAYS": 14,
    # Players
    "PLAYER_AGE": 22,
    "PLAYER_RANKING": 100,
    # Match slot duration (PRD §3.4: 'scheduled_end is scheduled_start
    # plus the format-rule slot duration').
    "MATCH_SLOT_MINUTES": 60,
    # Tax + verification defaults
    "DEFAULT_JURISDICTION": "US",
    "PAYOUT_CURRENCY": "USD",
}


__all__ = [
    "MVP_BPS",
    "TOTAL_BPS",
    "MAX_APPEALS",
    "APPEAL_WINDOW_HOURS",
    "RISK_HALFLIFE_DAYS",
    "AUTO_DISQUALIFY_THRESHOLD",
    "BASE_WEIGHT",
    "CLASSIFICATION_MULTIPLIER",
    "DISCONNECT_GRACE_SECONDS",
    "REFEREE_BUFFER_MINUTES",
    "ROSTER_MIN_MAIN_PLAYERS",
    "MIN_PAYOUT_FLOOR_CENTS",
    "TAX_BRACKETS",
    "FX_RATE",
    "TEST_DEFAULTS",
]
