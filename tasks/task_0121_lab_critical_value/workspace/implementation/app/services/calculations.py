"""All numeric calculations per scaffold §1.3 — uses decimal.Decimal throughout."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# Scaffold constants
LAB_LOCATION_CODE = "LAB_MAIN"
STAT_WINDOW_MIN = 10
ROUTINE_WINDOW_MIN = 30
ESCALATION_EXTENSION_MIN = 10
HIGH_WEIGHT = 2
LOW_WEIGHT = 1
HISTORY_LOOKBACK = 2
HISTORY_BOOST_PER_PRIOR_CRITICAL = Decimal("0.25")


def _d(x: Any) -> Decimal:
    """Convert int/float/str/Decimal to Decimal safely (route floats through str)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, (int,)):
        return Decimal(x)
    return Decimal(str(x))


def _round_half_up_2dp(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round_half_up_4dp(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# compute_critical_flags
# ---------------------------------------------------------------------------

def compute_critical_flags(
    measurements: list[dict[str, Any]],
    panel: dict[str, Any],
) -> list[dict[str, Any]]:
    """Strict outside-range comparison at 4 fractional decimal digits.

    Per scaffold: equal-to-bound is NOT critical (strict <, strict >).
    """
    flags: list[dict[str, Any]] = []
    spec_by_code: dict[str, dict[str, Any]] = {
        a["analyte_code"]: a for a in panel["analytes"]
    }
    for m in measurements:
        spec = spec_by_code.get(m["analyte_code"])
        if spec is None:
            continue
        value_d = _d(m["value"])
        low = spec.get("critical_low")
        high = spec.get("critical_high")
        if low is not None and value_d < _d(low):
            flags.append({
                "analyte_code": m["analyte_code"],
                "side": "LOW",
                "value": _flag_value(m["value"]),
                "bound": _flag_value(low),
            })
        elif high is not None and value_d > _d(high):
            flags.append({
                "analyte_code": m["analyte_code"],
                "side": "HIGH",
                "value": _flag_value(m["value"]),
                "bound": _flag_value(high),
            })
    return flags


def _flag_value(x: Any) -> Any:
    """Preserve numeric type going back out — ints stay ints, floats stay floats."""
    if isinstance(x, bool):
        return x
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        return x
    # If supplied as string or Decimal, fall back to float for JSON
    try:
        return float(_d(x))
    except Exception:
        return x


# ---------------------------------------------------------------------------
# severity_score_provisional — sum-then-round
# ---------------------------------------------------------------------------

def severity_score_provisional(critical_flags: list[dict[str, Any]]) -> float:
    """Per-flag distance and weight accumulated raw, rounded ONCE at the end."""
    raw = Decimal("0")
    for f in critical_flags:
        value = _d(f["value"])
        bound = _d(f["bound"])
        denom = max(abs(bound), Decimal("1"))
        distance = abs(value - bound) / denom
        weight = HIGH_WEIGHT if f["side"] == "HIGH" else LOW_WEIGHT
        raw += Decimal(weight) * distance
    return float(_round_half_up_2dp(raw))


# ---------------------------------------------------------------------------
# severity_score_final — round-per-piece-then-sum, with history boost
# ---------------------------------------------------------------------------

def severity_score_final(
    critical_flags: list[dict[str, Any]],
    history_critical_count: int,
) -> float:
    """Per-flag piece rounded BEFORE summing; NO further rounding on the sum."""
    historical_factor = Decimal("1.0") + HISTORY_BOOST_PER_PRIOR_CRITICAL * Decimal(history_critical_count)
    total = Decimal("0")
    for f in critical_flags:
        value = _d(f["value"])
        bound = _d(f["bound"])
        denom = max(abs(bound), Decimal("1"))
        distance = abs(value - bound) / denom
        weight = HIGH_WEIGHT if f["side"] == "HIGH" else LOW_WEIGHT
        piece = Decimal(weight) * distance * historical_factor
        piece = _round_half_up_2dp(piece)
        total += piece
    return float(total)


# ---------------------------------------------------------------------------
# specimen_stability_check — strict > comparison at 4 fractional minutes
# ---------------------------------------------------------------------------

def specimen_stability_exceeded(
    collected_at: datetime,
    arrived_at: datetime,
    stability_minutes: int,
) -> bool:
    delta = arrived_at - collected_at
    transit_minutes = Decimal(str(delta.total_seconds())) / Decimal("60")
    transit_minutes = _round_half_up_4dp(transit_minutes)
    return transit_minutes > _d(stability_minutes)


# ---------------------------------------------------------------------------
# ack_deadline
# ---------------------------------------------------------------------------

def ack_deadline_at(first_sent_at: datetime, priority: str) -> datetime:
    window = STAT_WINDOW_MIN if priority == "STAT" else ROUTINE_WINDOW_MIN
    return first_sent_at + timedelta(minutes=window)


def ack_deadline_extended(current_deadline: datetime) -> datetime:
    return current_deadline + timedelta(minutes=ESCALATION_EXTENSION_MIN)


# ---------------------------------------------------------------------------
# ack_latency_minutes — 2 decimal places
# ---------------------------------------------------------------------------

def ack_latency_minutes(first_sent_at: datetime, acknowledged_at: datetime) -> float:
    delta = acknowledged_at - first_sent_at
    minutes = Decimal(str(delta.total_seconds())) / Decimal("60")
    return float(_round_half_up_2dp(minutes))
