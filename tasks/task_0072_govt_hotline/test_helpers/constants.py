"""Domain thresholds — numeric constants from the PRD.

Field names mirror PRD prose exactly. Generic NON_EXISTENT_UUID comes from
the framework.
"""
from __future__ import annotations
import math


# ---------------------------------------------------------------------------
# Difficulty score (PRD §3.12).
# urgency_weight = {LOW:0, NORMAL:1, HIGH:3, CRITICAL:5}.
# joint_factor = 2 when joint_handling=true else 0.
# Score is clamped to [1, 10].
# ---------------------------------------------------------------------------
URGENCY_WEIGHT_LOW = 0
URGENCY_WEIGHT_NORMAL = 1
URGENCY_WEIGHT_HIGH = 3
URGENCY_WEIGHT_CRITICAL = 5

JOINT_FACTOR = 2

MIN_DIFFICULTY = 1
MAX_DIFFICULTY = 10

# Priority flag triggers when urgency >= HIGH OR difficulty_score >= 7.
PRIORITY_DIFFICULTY_THRESHOLD = 7


# ---------------------------------------------------------------------------
# Business hours (PRD §2.7).
# Business day runs 09:00 to 17:00 UTC, Mon..Fri.
# ---------------------------------------------------------------------------
BUSINESS_HOURS_PER_DAY = 8
BUSINESS_DAY_START_UTC_HOUR = 9
BUSINESS_DAY_END_UTC_HOUR = 17
BUSINESS_DAY_SECONDS = BUSINESS_HOURS_PER_DAY * 3600  # 28800


# ---------------------------------------------------------------------------
# Time-limit / pause / survey / reopen windows (PRD §2.7, §3.6, §3.9, §3.10).
# ---------------------------------------------------------------------------
SURVEY_EXPIRY_HOURS = 48          # PRD §3.9 business hours
REOPEN_WINDOW_HOURS = 72          # PRD §3.10 business hours
DUPLICATE_DETECTION_WINDOW_SECONDS = 600  # PRD §3.2
REMINDER_INTERVAL_HOURS = 24      # PRD §3.11 business hours
DISSATISFACTION_THRESHOLD_SCORE = 2  # PRD §3.10
MAX_ESCALATION_LEVEL = 3          # PRD §3.11


# ---------------------------------------------------------------------------
# Warning state thresholds (PRD §3.8).
# YELLOW when remaining/total <= 0.25 (inclusive).
# ---------------------------------------------------------------------------
YELLOW_THRESHOLD_FRACTION = 0.25
RED_THRESHOLD_FRACTION = 0.0


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3).
# "limit defaults to 10, has a minimum of 1, and a maximum of 100;
#  offset defaults to 0".
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Downstream platforms (PRD §2.9).
# ---------------------------------------------------------------------------
TARGET_PLATFORMS = ("IM", "GOVT_AFFAIRS", "INTER_DEPT")


# ---------------------------------------------------------------------------
# Round half-up helpers (PRD §2.8).
# ---------------------------------------------------------------------------
def round_half_up(value: float, decimals: int = 0) -> float:
    """PRD §2.8: 'rounded half-up to two decimal places... rounding is
    applied once at the end (never per-row before averaging).'"""
    factor = 10 ** decimals
    if value >= 0:
        return math.floor(value * factor + 0.5) / factor
    return -math.floor(-value * factor + 0.5) / factor


def urgency_weight(urgency: str) -> int:
    """PRD §3.12: 'urgency weight of 0 for LOW, 1 for NORMAL, 3 for HIGH,
    and 5 for CRITICAL.'"""
    return {
        "LOW": URGENCY_WEIGHT_LOW,
        "NORMAL": URGENCY_WEIGHT_NORMAL,
        "HIGH": URGENCY_WEIGHT_HIGH,
        "CRITICAL": URGENCY_WEIGHT_CRITICAL,
    }[urgency]


def expected_difficulty_score(urgency: str, difficulty_base: int,
                              joint_handling: bool) -> int:
    """PRD §3.12: 'the larger of 1 and the smaller of 10 and the raw sum.'
    raw = urgency_weight + difficulty_base + (2 if joint else 0)."""
    raw = (
        urgency_weight(urgency) + difficulty_base
        + (JOINT_FACTOR if joint_handling else 0)
    )
    return max(MIN_DIFFICULTY, min(MAX_DIFFICULTY, raw))


__all__ = [
    "URGENCY_WEIGHT_LOW", "URGENCY_WEIGHT_NORMAL",
    "URGENCY_WEIGHT_HIGH", "URGENCY_WEIGHT_CRITICAL",
    "JOINT_FACTOR", "MIN_DIFFICULTY", "MAX_DIFFICULTY",
    "PRIORITY_DIFFICULTY_THRESHOLD",
    "BUSINESS_HOURS_PER_DAY", "BUSINESS_DAY_START_UTC_HOUR",
    "BUSINESS_DAY_END_UTC_HOUR", "BUSINESS_DAY_SECONDS",
    "SURVEY_EXPIRY_HOURS", "REOPEN_WINDOW_HOURS",
    "DUPLICATE_DETECTION_WINDOW_SECONDS", "REMINDER_INTERVAL_HOURS",
    "DISSATISFACTION_THRESHOLD_SCORE", "MAX_ESCALATION_LEVEL",
    "YELLOW_THRESHOLD_FRACTION", "RED_THRESHOLD_FRACTION",
    "PAGINATION_DEFAULT_LIMIT", "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT", "PAGINATION_DEFAULT_OFFSET",
    "TARGET_PLATFORMS",
    "round_half_up", "urgency_weight", "expected_difficulty_score",
]
