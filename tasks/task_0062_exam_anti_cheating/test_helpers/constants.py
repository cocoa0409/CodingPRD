"""Domain thresholds and defaults derived from PRD numeric rules.

PRD §3.4 severity_classification: base scores, channel multipliers,
mode multipliers, severity bucket cutoffs.
PRD §3.6 ARBITRATION_THRESHOLD = 2.0.
PRD §3.7 appeal_window_seconds default = 86400.
"""
from __future__ import annotations
from typing import Dict


THRESHOLDS: Dict[str, float] = {
    # Severity base scores by behavior_rule_code (PRD §3.4).
    "BASE_FACE_LEAVE": 30,
    "BASE_WINDOW_SWITCH": 40,
    "BASE_MULTI_PERSON": 70,
    "BASE_EXTERNAL_DEVICE": 80,

    # Channel multipliers (PRD §3.4).
    "CHANNEL_SCREEN": 1.0,
    "CHANNEL_NETWORK": 1.0,
    "CHANNEL_PROCESS": 1.1,
    "CHANNEL_CAMERA": 1.2,
    "CHANNEL_AUDIO": 1.2,

    # Marking-mode multipliers (PRD §3.4).
    "MODE_REALTIME_ALERT": 1.0,
    "MODE_AFTER_THE_FACT": 0.5,

    # Severity bucket cutoffs (PRD §3.4).
    "SEVERITY_INFO_HI": 35,     # severity_score < 35 → INFO
    "SEVERITY_WARNING_HI": 70,  # 35 <= severity_score < 70 → WARNING

    # Grading arbitration threshold (PRD §3.6).
    "ARBITRATION_THRESHOLD": 2.0,
}


TEST_DEFAULTS: Dict[str, int] = {
    # Reasonable default values for tests building exams. Adjusted per-test.
    "EXAM_START_TIME": 1000,
    "EXAM_END_TIME": 2000,
    "APPEAL_WINDOW_SECONDS": 86400,
    "PER_QUESTION_TIME_LIMIT_SECONDS": 0,
}


__all__ = ["THRESHOLDS", "TEST_DEFAULTS"]
