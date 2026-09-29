"""Domain assertions and instant/rounding arithmetic for the program API.

The framework supplies generic assertions (UUID shape, envelope validation,
race outcomes). This module adds the assertions that only make sense against
this contract: the three conservation invariants, the audit-field shapes of
PRD 2.4, instant comparison on the full timestamp, and the derived figures
(deadlines, risk tiers, coverage) that a test needs to state an expected value.
"""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, List, Optional, Sequence

from .constants import (
    BASE_DAYS,
    DISPOSITION_FACTOR,
    HOUR_ALLOWANCE,
    HOUR_OVERAGE_RATE_USD,
    OVERDUE_MULTIPLIER,
    RISK_SCORE_CEILING,
    RISK_TIER_ELEVATED_FLOOR,
    RISK_TIER_MODERATE_FLOOR,
    SCAN_DUE_OFFSET_DAYS,
    SEVERITY_WEIGHT,
    expected_surcharge_rate,
)

MONEY_TOLERANCE = 0.01

# ---------------------------------------------------------------------------
# Instant arithmetic
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC instant with three fractional digits."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def instants_equal(left: str, right: str) -> bool:
    """True when two ISO 8601 strings denote the same instant.

    Comparison is on the full instant, so ``2026-03-30T00:00:00Z`` and
    ``2026-03-30T00:00:00.000Z`` are the same moment.
    """
    return parse_instant(left) == parse_instant(right)


def assert_instant(actual: str, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 strings denote the same instant."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert instants_equal(actual, expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def shift_instant(value: str, *, days: int = 0, seconds: int = 0) -> str:
    """Return the instant ``value`` moved by whole days and/or seconds."""
    return format_instant(parse_instant(value) + timedelta(days=days, seconds=seconds))


def days_between(earlier: str, later: str) -> float:
    """Fractional days from ``earlier`` to ``later``."""
    return (parse_instant(later) - parse_instant(earlier)).total_seconds() / 86400.0


def whole_days_late(submitted_at: str, scan_due_at: str) -> int:
    """``days_late``: whole 24-hour units elapsed since ``scan_due_at``.

    Returns 0 when the submission is at or before the due instant, and discards
    any partial unit otherwise.
    """
    elapsed = parse_instant(submitted_at) - parse_instant(scan_due_at)
    if elapsed.total_seconds() <= 0:
        return 0
    return int(math.floor(elapsed.total_seconds() / 86400.0))


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


def round_half_up(value: float, places: int = 2) -> float:
    """Round half up to ``places`` decimal places, as PRD 2.9 requires."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def assert_money(actual, expected: float, label: str = "amount") -> None:
    """Assert a monetary/percentage/hour figure matches to two decimal places."""
    assert actual is not None, f"{label} is null, expected {expected}"
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be a JSON number, got {type(actual).__name__}: {actual!r}"
    )
    assert abs(float(actual) - expected) < MONEY_TOLERANCE, (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_integer(actual, expected: int, label: str = "counter") -> None:
    """Assert a counter is a whole integer with the expected value."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer, got {type(actual).__name__}: {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected}, got {actual}"


# ---------------------------------------------------------------------------
# Audit field shapes (PRD 2.4)
# ---------------------------------------------------------------------------


def assert_audit_triplet(row: dict, label: str = "row") -> None:
    """Assert a row carries ``created_at``, ``updated_at`` and ``version``."""
    for field in ("created_at", "updated_at"):
        assert field in row and row[field], f"{label} is missing {field}"
        parse_instant(row[field])
    assert isinstance(row.get("version"), int), (
        f"{label}.version must be an integer, got {row.get('version')!r}"
    )
    assert row["version"] >= 1, f"{label}.version must start at 1, got {row['version']}"


def assert_identity_only(row: dict, label: str = "row") -> None:
    """Assert a row carries only ``id`` and ``created_at`` of the audit fields.

    ``ControlBaseline`` and ``ScanSubmission`` carry neither ``updated_at`` nor
    ``version``, and those fields are absent from their responses entirely.
    """
    assert "id" in row, f"{label} is missing id"
    assert "created_at" in row and row["created_at"], f"{label} is missing created_at"
    assert "updated_at" not in row, f"{label} must not carry updated_at"
    assert "version" not in row, f"{label} must not carry version"


# ---------------------------------------------------------------------------
# Conservation invariants (PRD 2.11)
# ---------------------------------------------------------------------------


def assert_hour_conservation(engagement: dict) -> None:
    """``contracted_hours == allocated_hours + unallocated_hours``."""
    total = float(engagement["allocated_hours"]) + float(
        engagement["unallocated_hours"]
    )
    assert_money(
        engagement["contracted_hours"],
        round_half_up(total),
        "contracted_hours vs allocated + unallocated",
    )
    assert float(engagement["unallocated_hours"]) >= 0.0, (
        "unallocated_hours must never be negative, got "
        f"{engagement['unallocated_hours']}"
    )


def assert_seat_conservation(authorization: dict) -> None:
    """``reuse_seats_total == reuse_seats_granted + reuse_seats_available``."""
    granted = authorization["reuse_seats_granted"]
    available = authorization["reuse_seats_available"]
    assert_integer(
        authorization["reuse_seats_total"],
        granted + available,
        "reuse_seats_total vs granted + available",
    )


def assert_finding_partition(authorization: dict) -> None:
    """``total_findings_count == open_findings_count + closed_findings_count``."""
    assert_integer(
        authorization["total_findings_count"],
        authorization["open_findings_count"] + authorization["closed_findings_count"],
        "total_findings_count vs open + closed",
    )


def assert_all_invariants(
    engagement: Optional[dict] = None, authorization: Optional[dict] = None
) -> None:
    """Assert whichever of the three conservation invariants apply."""
    if engagement is not None:
        assert_hour_conservation(engagement)
    if authorization is not None:
        assert_seat_conservation(authorization)
        assert_finding_partition(authorization)


# ---------------------------------------------------------------------------
# Derived figures
# ---------------------------------------------------------------------------


def expected_deadline(
    anchor_at: str, severity: str, granted_extension_days: int = 0
) -> str:
    """``anchor_at`` advanced by the severity base allowance then the extension."""
    return shift_instant(
        anchor_at, days=BASE_DAYS[severity] + granted_extension_days
    )


def expected_engagement_costs(
    labor_cost_usd: float, contracted_hours: float, impact_level: str
) -> dict:
    """The three-part engagement pricing rollup of PRD 3.5."""
    rate = expected_surcharge_rate(labor_cost_usd)
    surcharge = round_half_up(labor_cost_usd * rate)
    overage_hours = max(0.0, contracted_hours - HOUR_ALLOWANCE[impact_level])
    overage = round_half_up(overage_hours * HOUR_OVERAGE_RATE_USD)
    total = round_half_up(labor_cost_usd + surcharge + overage)
    return {
        "surcharge_rate": rate,
        "program_surcharge_usd": surcharge,
        "hour_overage_usd": overage,
        "total_cost_usd": total,
    }


def assert_engagement_costs(
    engagement: dict, labor_cost_usd: float, contracted_hours: float, impact_level: str
) -> None:
    """Assert an engagement's four pricing fields against the PRD rollup."""
    expected = expected_engagement_costs(
        labor_cost_usd, contracted_hours, impact_level
    )
    assert_money(engagement["surcharge_rate"], expected["surcharge_rate"], "surcharge_rate")
    assert_money(
        engagement["program_surcharge_usd"],
        expected["program_surcharge_usd"],
        "program_surcharge_usd",
    )
    assert_money(
        engagement["hour_overage_usd"], expected["hour_overage_usd"], "hour_overage_usd"
    )
    assert_money(engagement["total_cost_usd"], expected["total_cost_usd"], "total_cost_usd")


def expected_family_pct(documented: int, required_control_count: int) -> float:
    """One family's percentage: capped count over requirement, rounded half up."""
    counted = min(documented, required_control_count)
    return round_half_up(counted / required_control_count * 100.0)


def expected_overall_coverage(families: Sequence[tuple]) -> float:
    """Overall coverage from ``(documented, required_control_count)`` pairs.

    Families with a zero requirement are skipped entirely: they contribute to
    neither the numerator nor the weight. Each family percentage is rounded
    before the weighted mean is taken, and the mean is rounded afterwards.
    """
    weighted_sum = 0.0
    weight_total = 0
    for documented, required in families:
        if required == 0:
            continue
        weighted_sum += expected_family_pct(documented, required) * required
        weight_total += required
    if weight_total == 0:
        return 0.00
    return round_half_up(weighted_sum / weight_total)


def expected_risk_tier(score: float) -> str:
    """``poam_risk_tier`` derived from a residual risk score."""
    if score == 0.00:
        return "NONE"
    if score < RISK_TIER_MODERATE_FLOOR:
        return "LOW"
    if score < RISK_TIER_ELEVATED_FLOOR:
        return "MODERATE"
    return "ELEVATED"


def expected_residual_risk(findings: Iterable[dict], as_of: str) -> float:
    """Residual risk over ``{severity, risk_disposition, deadline_at}`` dicts.

    Each finding's contribution is rounded before the sum, the sum is rounded
    afterwards, and the result is capped at the ceiling. A finding is overdue
    when ``as_of`` is at or after its deadline.
    """
    total = 0.0
    for finding in findings:
        weight = SEVERITY_WEIGHT[finding["severity"]]
        factor = DISPOSITION_FACTOR[finding.get("risk_disposition", "NONE")]
        overdue = parse_instant(as_of) >= parse_instant(finding["deadline_at"])
        multiplier = OVERDUE_MULTIPLIER if overdue else 1.0
        total += round_half_up(weight * factor * multiplier)
    return min(round_half_up(total), RISK_SCORE_CEILING)


def assert_risk_tier_matches_score(payload: dict, label: str = "authorization") -> None:
    """Assert ``poam_risk_tier`` agrees with the ``residual_risk_score`` beside it."""
    score = float(payload["residual_risk_score"])
    expected = expected_risk_tier(score)
    assert payload["poam_risk_tier"] == expected, (
        f"{label}: score {score} implies tier {expected}, got {payload['poam_risk_tier']}"
    )


def expected_monitoring_window(period_month: str) -> dict:
    """The three instants a monitoring period derives from its ``period_month``."""
    year, month = (int(part) for part in period_month.split("-"))
    window_start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        window_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        window_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return {
        "window_start": format_instant(window_start),
        "window_end": format_instant(window_end),
        "scan_due_at": format_instant(
            window_end + timedelta(days=SCAN_DUE_OFFSET_DAYS)
        ),
    }


def assert_monitoring_window(period: dict, period_month: str) -> None:
    """Assert a period's derived instants match its ``period_month``."""
    expected = expected_monitoring_window(period_month)
    assert period["period_month"] == period_month, (
        f"period_month: expected {period_month}, got {period['period_month']}"
    )
    assert_instant(period["window_start"], expected["window_start"], "window_start")
    assert_instant(period["window_end"], expected["window_end"], "window_end")
    assert_instant(period["scan_due_at"], expected["scan_due_at"], "scan_due_at")


def expected_scan_status(days_late: int) -> str:
    """A scan submission's ``status`` follows directly from ``days_late``."""
    if days_late == 0:
        return "ACCEPTED"
    if days_late <= 3:
        return "LATE_ACCEPTED"
    return "REJECTED"


# ---------------------------------------------------------------------------
# Ordering and listing
# ---------------------------------------------------------------------------


def assert_created_at_ascending(rows: List[dict]) -> None:
    """Assert a list page is ordered by ``created_at`` ascending."""
    stamps = [parse_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), "rows are not ordered by created_at ascending"


def ids_of(rows: List[dict]) -> List[str]:
    """The ``id`` of each row, in page order."""
    return [row["id"] for row in rows]
