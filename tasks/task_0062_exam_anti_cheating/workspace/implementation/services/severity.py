"""Abnormal-event severity classification per PRD §3.4."""
from decimal import Decimal

from services.util import round_half_up_2dp


_BASE = {
    "FACE_LEAVE": Decimal("30"),
    "MULTI_PERSON": Decimal("70"),
    "WINDOW_SWITCH": Decimal("40"),
    "EXTERNAL_DEVICE": Decimal("80"),
}

_CHANNEL = {
    "SCREEN": Decimal("1.0"),
    "NETWORK": Decimal("1.0"),
    "PROCESS": Decimal("1.1"),
    "CAMERA": Decimal("1.2"),
    "AUDIO": Decimal("1.2"),
}

_MODE = {
    "REALTIME_ALERT": Decimal("1.0"),
    "AFTER_THE_FACT": Decimal("0.5"),
}


def compute_severity(behavior_rule_code: str, monitoring_channel: str,
                     marking_mode: str) -> tuple[str, float]:
    """Return (severity_bucket, severity_score)."""
    base = _BASE[behavior_rule_code]
    channel = _CHANNEL[monitoring_channel]
    mode = _MODE[marking_mode]
    raw = base * channel * mode
    score = round_half_up_2dp(raw)

    if score < 35:
        bucket = "INFO"
    elif score < 70:
        bucket = "WARNING"
    else:
        bucket = "CRITICAL"
    return bucket, score


def should_force_recheck(behavior_rule_code: str, severity_bucket: str,
                         attempt_status: str) -> bool:
    return (
        severity_bucket == "CRITICAL"
        and behavior_rule_code in {"FACE_LEAVE", "MULTI_PERSON"}
        and attempt_status == "ACTIVE"
    )


def should_cascade_disqualify(behavior_rule_code: str, severity_bucket: str,
                              attempt_status: str) -> bool:
    return (
        severity_bucket == "CRITICAL"
        and behavior_rule_code in {"MULTI_PERSON", "EXTERNAL_DEVICE"}
        and attempt_status == "ACTIVE"
    )
