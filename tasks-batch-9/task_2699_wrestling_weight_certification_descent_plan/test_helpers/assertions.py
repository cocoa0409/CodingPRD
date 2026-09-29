"""
Domain assertions layered on top of the framework's generic helpers.

Three families matter most here.  The first is one-decimal half-up rounding,
which every weight, allowance and body-fat figure obeys, and the two-decimal
half-up variant the audit discrepancy figures use.  The second is the shape
split between mutable rows and the three append-only rows that carry neither
``updated_at`` nor ``version``.  The third is the pair of conserved aggregates:
the team severity ledger and the event seed-integrity sum.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .constants import (
    AUDIT_DECIMAL_PLACES,
    DAYS_PER_WEEK,
    DEFAULT_WEIGHT_CLASSES,
    FLAG_ESCALATED,
    FLAG_OPEN,
    FLAG_SEVERITY,
    PROBATION_LOWER_BOUND,
    TEAM_CLEAR,
    TEAM_PROBATION,
    TEAM_WATCH,
    WATCH_LOWER_BOUND,
    WATCH_UPPER_BOUND,
    WEIGHT_DECIMAL_PLACES,
)

_ONE_PLACE = Decimal("0.1")
_TWO_PLACES = Decimal("0.01")


# ── Half-up rounding, the discipline the whole domain runs on ────────

def round_half_up(value: Any, places: int = WEIGHT_DECIMAL_PLACES) -> float:
    """Round a number half up to ``places`` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def round_weight(value: Any) -> float:
    """Round to the one decimal place weights and allowances are carried to."""
    return round_half_up(value, WEIGHT_DECIMAL_PLACES)


def round_audit(value: Any) -> float:
    """Round to the two decimal places audit discrepancy figures are carried to."""
    return round_half_up(value, AUDIT_DECIMAL_PLACES)


def assert_weight_equals(actual: Any, expected: float, label: str = "weight") -> None:
    """Compare two one-decimal weight figures exactly at that precision."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert round_weight(actual) == round_weight(expected), (
        f"{label}: expected {expected}, got {actual!r}"
    )


def assert_audit_score_equals(actual: Any, expected: float, label: str = "score") -> None:
    """Compare two audit discrepancy figures at two decimal places."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert round_audit(actual) == round_audit(expected), (
        f"{label}: expected {expected}, got {actual!r}"
    )


# ── The certified-figure arithmetic ──────────────────────────────────

def expected_lean_body_weight(measured_weight_lbs: float, body_fat_pct: float) -> float:
    """The measured weight times one minus the fat fraction, rounded to one place."""
    lean = Decimal(str(measured_weight_lbs)) * (
        Decimal("1") - Decimal(str(body_fat_pct)) / Decimal("100")
    )
    return float(lean.quantize(_ONE_PLACE, rounding=ROUND_HALF_UP))


def expected_minimum_certified_weight(
    measured_weight_lbs: float, body_fat_pct: float, floor_pct: float
) -> float:
    """The already-rounded lean weight divided by one minus the floor fraction.

    The rounding order is pinned: the unrounded lean weight never enters the
    division.
    """
    lean = Decimal(str(expected_lean_body_weight(measured_weight_lbs, body_fat_pct)))
    minimum = lean / (Decimal("1") - Decimal(str(floor_pct)) / Decimal("100"))
    return float(minimum.quantize(_ONE_PLACE, rounding=ROUND_HALF_UP))


def smallest_class_at_or_above(
    threshold: float, weight_classes: Sequence[int] = DEFAULT_WEIGHT_CLASSES
) -> Optional[int]:
    """The smallest ladder member greater than or equal to ``threshold``.

    The comparison is inclusive, so a threshold landing exactly on a class limit
    selects that class rather than the next one up.  Returns ``None`` when no
    class in the ladder reaches the threshold.
    """
    candidates = [c for c in weight_classes if Decimal(str(c)) >= Decimal(str(threshold))]
    return min(candidates) if candidates else None


def weekly_step_allowable_weights(
    alpha: float, rate_pct: float, target: float
) -> List[float]:
    """The compounding schedule, rounded to one place after every single week."""
    weights = [round_weight(alpha)]
    while Decimal(str(weights[-1])) > Decimal(str(target)):
        previous = Decimal(str(weights[-1]))
        nxt = previous * (Decimal("1") - Decimal(str(rate_pct)) / Decimal("100"))
        weights.append(float(nxt.quantize(_ONE_PLACE, rounding=ROUND_HALF_UP)))
    return weights


def linear_rate_weekly_delta(alpha: float, rate_pct: float) -> float:
    """The single fixed pound delta a linear plan computes once."""
    delta = Decimal(str(alpha)) * Decimal(str(rate_pct)) / Decimal("100")
    return float(delta.quantize(_ONE_PLACE, rounding=ROUND_HALF_UP))


def linear_rate_allowable_weights(
    alpha: float, rate_pct: float, target: float
) -> List[float]:
    """The linear schedule: the untouched baseline minus k times the fixed delta."""
    delta = Decimal(str(linear_rate_weekly_delta(alpha, rate_pct)))
    weights: List[float] = []
    k = 0
    while True:
        value = Decimal(str(alpha)) - Decimal(k) * delta
        weights.append(float(value.quantize(_ONE_PLACE, rounding=ROUND_HALF_UP)))
        if Decimal(str(weights[-1])) <= Decimal(str(target)):
            return weights
        k += 1


def implied_weekly_delta(alpha: float, target: float, requested_weeks: int) -> float:
    """The delta a ``requested_weeks`` figure implies, rounded to one place."""
    delta = (Decimal(str(alpha)) - Decimal(str(target))) / Decimal(requested_weeks)
    return float(delta.quantize(_ONE_PLACE, rounding=ROUND_HALF_UP))


# ── Calendar arithmetic ──────────────────────────────────────────────

def as_date(value: Any) -> date:
    """Parse an ISO 8601 calendar date."""
    assert isinstance(value, str) and value, f"expected a YYYY-MM-DD date, got {value!r}"
    return date.fromisoformat(value[:10])


def plus_days(value: str, days: int) -> str:
    """A calendar date advanced by whole days."""
    return (as_date(value) + timedelta(days=days)).isoformat()


def plus_weeks(value: str, weeks: int) -> str:
    """A calendar date advanced by seven days times ``weeks``."""
    return plus_days(value, DAYS_PER_WEEK * weeks)


def as_instant(value: Any) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two ISO 8601 UTC instants by the moment they name."""
    assert as_instant(actual) == as_instant(expected), (
        f"{label}: expected {expected}, got {actual!r}"
    )


# ── Row shapes ───────────────────────────────────────────────────────

def assert_identity_fields(row: Dict[str, Any], label: str = "row") -> None:
    """Every stored row carries a UUID ``id`` and an ISO 8601 ``created_at``."""
    assert is_valid_uuid(row.get("id")), f"{label}: id is not a UUID: {row.get('id')!r}"
    assert is_iso8601_timestamp(row.get("created_at")), (
        f"{label}: created_at is not an ISO 8601 timestamp: {row.get('created_at')!r}"
    )


def assert_mutable_row(row: Dict[str, Any], label: str = "row") -> None:
    """A mutable row additionally carries ``updated_at`` and an integer ``version``."""
    assert_identity_fields(row, label)
    assert is_iso8601_timestamp(row.get("updated_at")), (
        f"{label}: updated_at is not an ISO 8601 timestamp: {row.get('updated_at')!r}"
    )
    assert isinstance(row.get("version"), int) and not isinstance(
        row.get("version"), bool
    ), f"{label}: version is not an integer: {row.get('version')!r}"
    assert row["version"] >= 1, f"{label}: version starts at 1, got {row['version']}"


def assert_append_only_row(row: Dict[str, Any], label: str = "row") -> None:
    """An append-only row carries neither ``updated_at`` nor ``version``."""
    assert_identity_fields(row, label)
    assert "updated_at" not in row, (
        f"{label}: append-only rows carry no updated_at, found {row.get('updated_at')!r}"
    )
    assert "version" not in row, (
        f"{label}: append-only rows carry no version, found {row.get('version')!r}"
    )


def assert_version_is(row: Dict[str, Any], expected: int, label: str = "row") -> None:
    assert row.get("version") == expected, (
        f"{label}: expected version {expected}, got {row.get('version')!r}"
    )


def assert_all_null(row: Dict[str, Any], fields: Iterable[str], label: str = "row") -> None:
    """Assert a named set of fields all read null."""
    for field in fields:
        assert field in row, f"{label}: expected the field {field} to be present"
        assert row[field] is None, (
            f"{label}: expected {field} to be null, got {row[field]!r}"
        )


# ── The two conserved aggregates ─────────────────────────────────────

def expected_severity_total(flags: Iterable[Dict[str, Any]]) -> int:
    """The severity ledger: the sum over flags whose status is OPEN or ESCALATED."""
    return sum(
        int(flag["severity"])
        for flag in flags
        if flag.get("status") in (FLAG_OPEN, FLAG_ESCALATED)
    )


def expected_posture(total: int) -> str:
    """The derived compliance posture for a severity total."""
    if total == 0:
        return TEAM_CLEAR
    if WATCH_LOWER_BOUND <= total <= WATCH_UPPER_BOUND:
        return TEAM_WATCH
    return TEAM_PROBATION


def assert_severity_ledger(
    team: Dict[str, Any], expected_total: int, label: str = "team"
) -> None:
    """The ledger and the posture it derives must agree with each other."""
    assert team.get("open_flag_severity_total") == expected_total, (
        f"{label}: expected open_flag_severity_total {expected_total}, "
        f"got {team.get('open_flag_severity_total')!r}"
    )
    assert team.get("compliance_status") == expected_posture(expected_total), (
        f"{label}: a total of {expected_total} derives "
        f"{expected_posture(expected_total)}, got {team.get('compliance_status')!r}"
    )


def assert_flag_severity_matches_source(flag: Dict[str, Any]) -> None:
    """Severity is pinned per flag source and is never client-supplied."""
    source = flag.get("source")
    assert source in FLAG_SEVERITY, f"unknown flag source {source!r}"
    assert flag.get("severity") == FLAG_SEVERITY[source], (
        f"a {source} flag carries severity {FLAG_SEVERITY[source]}, "
        f"got {flag.get('severity')!r}"
    )


def expected_seed_integrity_sum(class_counts: Iterable[int]) -> int:
    """The sum over occupied classes of n times n plus one, divided by two."""
    return sum(n * (n + 1) // 2 for n in class_counts if n > 0)


def assert_seed_integrity_sum(
    event: Dict[str, Any], class_counts: Sequence[int], label: str = "event"
) -> None:
    expected = expected_seed_integrity_sum(class_counts)
    assert event.get("seed_integrity_sum") == expected, (
        f"{label}: expected seed_integrity_sum {expected} for class counts "
        f"{list(class_counts)}, got {event.get('seed_integrity_sum')!r}"
    )


def assert_seed_sum_matches_entries(
    event: Dict[str, Any], entries: Iterable[Dict[str, Any]], label: str = "event"
) -> None:
    """The stored sum equals the sum of seed numbers actually assigned."""
    total = sum(
        int(entry["seed_number"])
        for entry in entries
        if entry.get("seed_number") is not None
    )
    assert event.get("seed_integrity_sum") == total, (
        f"{label}: seed_integrity_sum {event.get('seed_integrity_sum')!r} does not "
        f"equal the sum of assigned seed numbers {total}"
    )


# ── Milestones ───────────────────────────────────────────────────────

def assert_milestone(
    milestone: Dict[str, Any],
    week_index: int,
    effective_date: str,
    allowable_weight_lbs: float,
    min_eligible_class_lbs: int,
    status: str,
    label: str = "milestone",
) -> None:
    """Check one generated milestone row field by field."""
    assert milestone.get("week_index") == week_index, (
        f"{label}: expected week_index {week_index}, got {milestone.get('week_index')!r}"
    )
    assert milestone.get("effective_date") == effective_date, (
        f"{label}: expected effective_date {effective_date}, "
        f"got {milestone.get('effective_date')!r}"
    )
    assert_weight_equals(
        milestone.get("allowable_weight_lbs"),
        allowable_weight_lbs,
        f"{label} allowable_weight_lbs",
    )
    assert milestone.get("min_eligible_class_lbs") == min_eligible_class_lbs, (
        f"{label}: expected min_eligible_class_lbs {min_eligible_class_lbs}, "
        f"got {milestone.get('min_eligible_class_lbs')!r}"
    )
    assert milestone.get("status") == status, (
        f"{label}: expected status {status}, got {milestone.get('status')!r}"
    )


def expected_min_eligible_class(
    allowable_weight_lbs: float,
    minimum_certified_weight_lbs: float,
    weight_classes: Sequence[int] = DEFAULT_WEIGHT_CLASSES,
) -> Optional[int]:
    """The smallest class at or above the larger of the two figures."""
    floor = max(Decimal(str(allowable_weight_lbs)), Decimal(str(minimum_certified_weight_lbs)))
    return smallest_class_at_or_above(float(floor), weight_classes)


# ── The eligibility floor ────────────────────────────────────────────

def expected_lowest_eligible_class(
    minimum_certified_weight_lbs: float,
    schedule_allowable_weight_lbs: Optional[float],
    growth_allowance_lbs: float,
    min_weight_class_lbs: int,
    weight_classes: Sequence[int] = DEFAULT_WEIGHT_CLASSES,
) -> Optional[int]:
    """The four pinned steps of the class-floor derivation, in order.

    Growth allowance relaxes the candidate search only; it is never folded back
    into the hard-floor class computed at assessment-validation time.
    """
    if schedule_allowable_weight_lbs is None:
        floor = Decimal(str(minimum_certified_weight_lbs))
    else:
        floor = max(
            Decimal(str(minimum_certified_weight_lbs)),
            Decimal(str(schedule_allowable_weight_lbs)),
        )
    growth = Decimal(str(growth_allowance_lbs))
    candidates = [c for c in weight_classes if Decimal(str(c)) + growth >= floor]
    if not candidates:
        return None
    return max(min(candidates), min_weight_class_lbs)


# ── The weigh-in verdict ─────────────────────────────────────────────

def expected_consecutive_day_allowance(
    day_index: int, per_day_lbs: float, season_cap_lbs: float
) -> float:
    """The day-index component, rounded to one place and then capped."""
    raw = Decimal(day_index) * Decimal(str(per_day_lbs))
    rounded = float(raw.quantize(_ONE_PLACE, rounding=ROUND_HALF_UP))
    return min(rounded, round_weight(season_cap_lbs))


def expected_weigh_in_result(
    recorded_weight_lbs: float, weight_class_lbs: float, effective_limit_lbs: float
) -> str:
    """The three ordered comparisons the verdict follows."""
    recorded = Decimal(str(recorded_weight_lbs))
    if recorded <= Decimal(str(weight_class_lbs)):
        return "PASS"
    if recorded <= Decimal(str(effective_limit_lbs)):
        return "PASS_WITH_ALLOWANCE"
    return "FAIL"


# ── Audit scoring ────────────────────────────────────────────────────

def expected_deviation(remeasured_body_fat_pct: float, recorded_body_fat_pct: float) -> float:
    """One per-sample deviation, rounded half up to two decimal places."""
    deviation = abs(
        Decimal(str(remeasured_body_fat_pct)) - Decimal(str(recorded_body_fat_pct))
    )
    return float(deviation.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))


def expected_worst_case_score(deviations: Sequence[float]) -> float:
    """The single largest per-sample deviation."""
    return max(round_audit(d) for d in deviations)


def expected_sample_mean_score(deviations: Sequence[float]) -> float:
    """The sum of the deviations divided by the sample count, to two places."""
    total = sum(Decimal(str(round_audit(d))) for d in deviations)
    mean = total / Decimal(len(deviations))
    return float(mean.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP))


# ── List reading ─────────────────────────────────────────────────────

def paginated_rows(response) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Validate a list response and return its rows and pagination metadata."""
    return validate_paginated(response)


def assert_row_count(response, expected: int, label: str = "listing") -> List[Dict[str, Any]]:
    """A list response must carry exactly ``expected`` rows and say so in meta."""
    rows, meta = validate_paginated(response)
    assert len(rows) == expected, (
        f"{label}: expected {expected} rows, got {len(rows)}"
    )
    assert meta.get("total_count") == expected, (
        f"{label}: expected total_count {expected}, got {meta.get('total_count')!r}"
    )
    return rows


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_ordered_by(
    rows: Sequence[Dict[str, Any]], field: str, label: str = "listing"
) -> None:
    """Assert a listing is returned in ascending order of one field."""
    values = [row.get(field) for row in rows]
    assert values == sorted(values), (
        f"{label}: rows are not in ascending {field} order: {values}"
    )
