"""Entity assertions, instant comparison and domain invariant checkers."""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ---------------------------------------------------------------------------
# Instant handling
# ---------------------------------------------------------------------------

_MILLISECOND_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 instant, tolerating every rendering the PRD allows.

    Accepts a trailing `Z`, any number of fractional-second digits, and an
    explicit `+HH:MM` / `-HH:MM` offset. A date-only value is promoted to that
    calendar date at midnight UTC, exactly as PRD 2.5 prescribes for date-only
    fields taking part in instant arithmetic.
    """
    assert isinstance(value, str) and value, f"Expected an instant string, got {value!r}"
    text = value.strip()
    if _DATE_ONLY_RE.match(text):
        text = text + "T00:00:00+00:00"
    elif text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: Any, expected: Any, message: str = "") -> None:
    """Compare two datetimes as resolved instants, never as strings.

    The server may render an instant it minted as `...T08:00:00.123Z` while the
    value it was derived from was written `...T08:00:00Z`; both denote one
    instant and this helper compares the instants, not the spellings.
    """
    suffix = f" - {message}" if message else ""
    assert actual is not None, f"Expected instant {expected!r}, got None{suffix}"
    left = parse_instant(actual)
    right = parse_instant(expected)
    assert left == right, (
        f"Instants differ: got {actual!r} ({left.isoformat()}), "
        f"expected {expected!r} ({right.isoformat()}){suffix}"
    )


def assert_instant_before(earlier: Any, later: Any, message: str = "") -> None:
    suffix = f" - {message}" if message else ""
    assert parse_instant(earlier) < parse_instant(later), (
        f"Expected {earlier!r} to be strictly before {later!r}{suffix}"
    )


def assert_millisecond_instant_format(value: Any, field_name: str = "instant") -> None:
    """PRD 2.5: a server-minted instant carries exactly three fractional digits."""
    assert isinstance(value, str), f"{field_name} must be a string, got {value!r}"
    assert _MILLISECOND_INSTANT_RE.match(value), (
        f"{field_name} must be rendered YYYY-MM-DDTHH:MM:SS.mmmZ with exactly "
        f"three fractional-second digits, got {value!r}"
    )


def assert_date_only_format(value: Any, field_name: str = "date") -> None:
    """PRD 2.5: date-only fields are rendered YYYY-MM-DD."""
    assert isinstance(value, str), f"{field_name} must be a string, got {value!r}"
    assert _DATE_ONLY_RE.match(value), (
        f"{field_name} must be rendered YYYY-MM-DD, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Common shape assertions
# ---------------------------------------------------------------------------


def assert_versioned_resource(data: Dict[str, Any], entity_name: str = "resource") -> None:
    """PRD 2.4: id + created_at + updated_at + version on every resource but ConditionPolicy."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a server-minted UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_catalogue_row(data: Dict[str, Any], entity_name: str = "resource") -> None:
    """PRD 2.4: ConditionPolicy exposes only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, (
        f"{entity_name} must not carry updated_at, got {data.get('updated_at')!r}"
    )
    assert "version" not in data, (
        f"{entity_name} must not carry version, got {data.get('version')!r}"
    )


def assert_rider(data: Dict[str, Any]) -> None:
    assert_versioned_resource(data, "Rider")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert_date_only_format(data["date_of_birth"], "Rider.date_of_birth")
    assert data["status"] in ("INTAKE", "ACTIVE", "MEDICAL_HOLD", "WITHDRAWN")
    assert data["assessment_status"] in (
        "NEVER_ASSESSED",
        "CURRENT",
        "DUE",
        "OVERDUE",
    )
    assert data["household_income_band"] in ("BAND_A", "BAND_B", "BAND_C", "BAND_D")
    assert data["demographic_group"] in ("VETERAN", "YOUTH", "ADULT", "SENIOR")
    assert data["program_code"] in (
        "THERAPEUTIC_RIDING",
        "HIPPOTHERAPY",
        "EQUINE_LEARNING",
        "VAULTING",
    )
    assert data["funding_mode"] in ("PRIVATE_PAY_ALLOWED", "FUNDED_ONLY")
    assert isinstance(data["payer_rate_cents"], int) and data["payer_rate_cents"] >= 0
    assert isinstance(data["condition_codes"], list)
    assert isinstance(data["goals_met_count"], int)


def assert_horse(data: Dict[str, Any]) -> None:
    assert_versioned_resource(data, "Horse")
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("AVAILABLE", "VET_HOLD", "FARRIER_HOLD", "REST_HOLD")
    assert isinstance(data["max_load_lb"], (int, float))
    assert_date_only_format(
        data["current_week_start_date"], "Horse.current_week_start_date"
    )
    assert isinstance(data["current_week_committed_minutes"], int)
    assert isinstance(data["current_day_committed_minutes"], int)
    assert isinstance(data["current_day_session_count"], int)


def assert_session(data: Dict[str, Any]) -> None:
    assert_versioned_resource(data, "Session")
    assert data["schedule_status"] in (
        "CREW_PENDING",
        "CONFIRMED",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
    )
    assert data["billing_status"] in ("UNBILLED", "CHARGED", "FUNDED", "REVERSED")
    assert data["activity_type"] in (
        "THERAPEUTIC_RIDING",
        "HIPPOTHERAPY",
        "EQUINE_LEARNING",
        "VAULTING",
    )
    assert isinstance(data["duration_minutes"], int)
    assert isinstance(data["quoted_fee_cents"], int)
    assert isinstance(data["crew_satisfied"], bool)
    assert data["precaution_tier"] in ("CLEAR", "PRECAUTION", "CONTRAINDICATION")
    assert data["required_instructor_tier"] in (
        "IN_TRAINING",
        "REGISTERED",
        "ADVANCED",
        "MASTER",
    )


def assert_volunteer(data: Dict[str, Any]) -> None:
    assert_versioned_resource(data, "Volunteer")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "INACTIVE")
    assert isinstance(data["age_years"], int)
    assert isinstance(data["open_assignment_count"], int)


def assert_instructor(data: Dict[str, Any]) -> None:
    assert_versioned_resource(data, "Instructor")
    assert data["certification_level"] in (
        "IN_TRAINING",
        "REGISTERED",
        "ADVANCED",
        "MASTER",
    )
    assert data["certification_status"] in ("CURRENT", "GRACE", "LAPSED", "SUSPENDED")


def assert_charge(data: Dict[str, Any]) -> None:
    assert_versioned_resource(data, "Charge")
    assert data["charge_type"] in (
        "SESSION_FEE",
        "LATE_CANCELLATION_FEE",
        "NO_SHOW_FEE",
    )
    assert data["status"] in ("PENDING", "FUNDED", "REVERSED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["scholarship_excluded"], bool)


def assert_incident(data: Dict[str, Any]) -> None:
    assert_versioned_resource(data, "Incident")
    assert data["severity"] in ("SEV_1", "SEV_2", "SEV_3")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "CLOSED")
    assert isinstance(data["reported_late"], bool)
    assert isinstance(data["rider_hold_applied"], bool)
    assert isinstance(data["horse_hold_applied"], bool)
    assert isinstance(data["volunteer_suspension_applied"], bool)
    assert isinstance(data["instructor_suspension_applied"], bool)


# ---------------------------------------------------------------------------
# Funding allocation helpers
# ---------------------------------------------------------------------------


def allocation_total(allocations: Iterable[Dict[str, Any]], source_type: str) -> int:
    """Sum `amount_cents` over every allocation line of one source type.

    Summing rather than picking a single row keeps the assertion neutral about
    whether an implementation also emits a zero-amount line for a source that
    contributed nothing.
    """
    return sum(
        int(line["amount_cents"])
        for line in allocations
        if line.get("source_type") == source_type
    )


def allocations_of(
    allocations: Iterable[Dict[str, Any]], source_type: str
) -> List[Dict[str, Any]]:
    return [line for line in allocations if line.get("source_type") == source_type]


def positive_allocation(
    allocations: Iterable[Dict[str, Any]], source_type: str
) -> Dict[str, Any]:
    """Return the single allocation line of `source_type` carrying money."""
    lines = [
        line
        for line in allocations
        if line.get("source_type") == source_type and int(line["amount_cents"]) > 0
    ]
    assert len(lines) == 1, (
        f"Expected exactly one {source_type} allocation line with a positive "
        f"amount_cents, found {len(lines)}: {lines}"
    )
    return lines[0]


def assert_charge_conservation(charge: Dict[str, Any], allocations: List[Dict[str, Any]]) -> None:
    """PRD 2.12: a charge's gross always equals the sum of its ALLOCATED lines."""
    allocated = sum(
        int(line["amount_cents"])
        for line in allocations
        if line.get("status") == "ALLOCATED"
    )
    if charge["status"] == "REVERSED":
        assert charge["allocated_cents"] == 0, (
            f"A REVERSED charge must report allocated_cents 0, got {charge['allocated_cents']}"
        )
        assert charge["balance_due_cents"] == 0, (
            f"A REVERSED charge must report balance_due_cents 0, got {charge['balance_due_cents']}"
        )
        assert allocated == 0, "A REVERSED charge must have no ALLOCATED lines left"
    else:
        assert charge["amount_cents"] == allocated, (
            f"Charge gross {charge['amount_cents']} must equal the sum of ALLOCATED "
            f"lines {allocated}"
        )
        assert charge["allocated_cents"] == allocated, (
            f"Charge.allocated_cents {charge['allocated_cents']} must equal {allocated}"
        )


def assert_grant_partition(grant: Dict[str, Any]) -> None:
    """PRD 2.12: awarded_amount_cents == remaining_amount_cents + allocated_amount_cents."""
    assert (
        grant["awarded_amount_cents"]
        == grant["remaining_amount_cents"] + grant["allocated_amount_cents"]
    ), (
        f"Grant partition broken: awarded {grant['awarded_amount_cents']} != "
        f"remaining {grant['remaining_amount_cents']} + allocated "
        f"{grant['allocated_amount_cents']}"
    )


def find_by_id(rows: Iterable[Dict[str, Any]], row_id: str) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None
