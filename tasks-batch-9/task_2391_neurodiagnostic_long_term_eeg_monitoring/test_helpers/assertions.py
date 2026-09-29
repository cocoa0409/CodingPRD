"""
Domain assertions.

These wrap the recurring checks of this contract so that a test body reads as
the rule it is exercising: the three numeric precisions, instant equality that
tolerates the fractional-second spelling, the conserved day-ledger equality, the
reduced preamble of append-only evidence, and the paired state dimensions.
"""

from decimal import Decimal
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import CAPTURE_DECIMALS, STORAGE_DECIMALS, TURNAROUND_DECIMALS

_EPSILON = 1e-9


# ---------------------------------------------------------------------------
# Numeric precision
# ---------------------------------------------------------------------------


def _assert_decimal_places(value: Any, places: int, label: str) -> None:
    assert value is not None, f"{label} is unexpectedly null"
    assert isinstance(value, (int, float)) and not isinstance(
        value, bool
    ), f"{label} should be numeric, got {value!r}"
    text = f"{Decimal(str(value)):f}"
    if "." in text:
        actual_places = len(text.split(".", 1)[1].rstrip("0"))
    else:
        actual_places = 0
    assert actual_places <= places, (
        f"{label} carries more than {places} decimal places: {value!r}"
    )


def assert_storage_value(value: Any, expected: float, label: str = "storage figure") -> None:
    """A storage volume or percentage: 2 decimal places, exact value."""
    _assert_decimal_places(value, STORAGE_DECIMALS, label)
    assert abs(float(value) - expected) < _EPSILON, (
        f"{label} should be {expected:.2f}, got {value!r}"
    )


def assert_turnaround_value(
    value: Any, expected: float, label: str = "turnaround figure"
) -> None:
    """A turnaround figure: 2 decimal places, exact value."""
    _assert_decimal_places(value, TURNAROUND_DECIMALS, label)
    assert abs(float(value) - expected) < _EPSILON, (
        f"{label} should be {expected:.2f}, got {value!r}"
    )


def assert_capture_value(value: Any, expected: float, label: str = "capture figure") -> None:
    """A capture figure: 3 decimal places, exact value."""
    _assert_decimal_places(value, CAPTURE_DECIMALS, label)
    assert abs(float(value) - expected) < _EPSILON, (
        f"{label} should be {expected:.3f}, got {value!r}"
    )


def assert_whole_minutes(value: Any, expected: int, label: str = "minutes") -> None:
    """A whole-minute figure, truncated rather than rounded."""
    assert value == expected, f"{label} should be {expected}, got {value!r}"
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} should be an integer count, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------


def _normalize_instant(value: str) -> str:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = frac.rstrip("0")
        text = head if not frac else f"{head}.{frac}"
    return text


def assert_instant_equals(actual: Any, expected: str, label: str = "instant") -> None:
    """Compare two ISO 8601 UTC instants without depending on trailing zeros."""
    assert actual is not None, f"{label} is unexpectedly null"
    assert _normalize_instant(str(actual)) == _normalize_instant(expected), (
        f"{label} should be {expected}, got {actual!r}"
    )


# ---------------------------------------------------------------------------
# Record preambles
# ---------------------------------------------------------------------------


def assert_full_preamble(record: Dict[str, Any], label: str = "record") -> None:
    """`id`, `created_at`, `updated_at` and `version` all present and well formed."""
    assert is_valid_uuid(record.get("id")), (
        f"{label} id should be a UUID, got {record.get('id')!r}"
    )
    assert is_iso8601_timestamp(record.get("created_at")), (
        f"{label} created_at should be an ISO 8601 timestamp, got {record.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(record.get("updated_at")), (
        f"{label} updated_at should be an ISO 8601 timestamp, got {record.get('updated_at')!r}"
    )
    assert isinstance(record.get("version"), int), (
        f"{label} version should be an integer, got {record.get('version')!r}"
    )


def assert_append_only_preamble(record: Dict[str, Any], label: str = "record") -> None:
    """Append-only evidence exposes only `id` and `created_at` of the preamble."""
    assert is_valid_uuid(record.get("id")), (
        f"{label} id should be a UUID, got {record.get('id')!r}"
    )
    assert is_iso8601_timestamp(record.get("created_at")), (
        f"{label} created_at should be an ISO 8601 timestamp, got {record.get('created_at')!r}"
    )
    assert "updated_at" not in record, f"{label} should not expose updated_at"
    assert "version" not in record, f"{label} should not expose version"


def assert_version_is(record: Dict[str, Any], expected: int, label: str = "record") -> None:
    assert record.get("version") == expected, (
        f"{label} version should be {expected}, got {record.get('version')!r}"
    )


def assert_fields_null(record: Dict[str, Any], *names: str) -> None:
    for name in names:
        assert name in record, f"expected field {name} to be present"
        assert record[name] is None, f"{name} should be null, got {record[name]!r}"


def assert_fields_zero(record: Dict[str, Any], *names: str) -> None:
    for name in names:
        assert name in record, f"expected field {name} to be present"
        assert float(record[name]) == 0, f"{name} should be 0, got {record[name]!r}"


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_ledger_conserved(authorization: Dict[str, Any]) -> None:
    """`authorized_days` equals `days_consumed` plus `days_reserved` plus `days_available`."""
    authorized = authorization["authorized_days"]
    consumed = authorization["days_consumed"]
    reserved = authorization["days_reserved"]
    available = authorization["days_available"]
    assert authorized == consumed + reserved + available, (
        "day ledger is not conserved: "
        f"authorized_days={authorized} but consumed={consumed} + reserved={reserved} "
        f"+ available={available}"
    )


def assert_ledger(
    authorization: Dict[str, Any],
    *,
    authorized_days: Optional[int] = None,
    days_consumed: Optional[int] = None,
    days_reserved: Optional[int] = None,
    days_available: Optional[int] = None,
) -> None:
    """Assert the requested ledger buckets and then the conserved equality."""
    expectations = {
        "authorized_days": authorized_days,
        "days_consumed": days_consumed,
        "days_reserved": days_reserved,
        "days_available": days_available,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert authorization[field] == expected, (
                f"{field} should be {expected}, got {authorization[field]!r}"
            )
    assert_ledger_conserved(authorization)


def assert_unit_storage(
    unit: Dict[str, Any],
    *,
    storage_used_gb: Optional[float] = None,
    storage_pressure_pct: Optional[float] = None,
    posture: Optional[str] = None,
) -> None:
    if storage_used_gb is not None:
        assert_storage_value(unit["storage_used_gb"], storage_used_gb, "storage_used_gb")
    if storage_pressure_pct is not None:
        assert_storage_value(
            unit["storage_pressure_pct"], storage_pressure_pct, "storage_pressure_pct"
        )
    if posture is not None:
        assert unit["posture"] == posture, (
            f"unit posture should be {posture}, got {unit['posture']!r}"
        )


def assert_admission_dimensions(
    admission: Dict[str, Any], clinical_state: str, authorization_state: str
) -> None:
    assert admission["clinical_state"] == clinical_state, (
        f"clinical_state should be {clinical_state}, got {admission['clinical_state']!r}"
    )
    assert admission["authorization_state"] == authorization_state, (
        "authorization_state should be "
        f"{authorization_state}, got {admission['authorization_state']!r}"
    )


def assert_study_dimensions(
    study: Dict[str, Any], acquisition_state: str, data_state: str
) -> None:
    assert study["acquisition_state"] == acquisition_state, (
        f"acquisition_state should be {acquisition_state}, got {study['acquisition_state']!r}"
    )
    assert study["data_state"] == data_state, (
        f"data_state should be {data_state}, got {study['data_state']!r}"
    )


def assert_alert_dimensions(
    alert: Dict[str, Any], triage_state: str, response_state: str
) -> None:
    assert alert["triage_state"] == triage_state, (
        f"triage_state should be {triage_state}, got {alert['triage_state']!r}"
    )
    assert alert["response_state"] == response_state, (
        f"response_state should be {response_state}, got {alert['response_state']!r}"
    )


def assert_case_tallies(
    case: Dict[str, Any],
    *,
    eligible_vote_count: Optional[int] = None,
    candidate_votes: Optional[int] = None,
    non_candidate_votes: Optional[int] = None,
    defer_votes: Optional[int] = None,
    distinct_specialty_count: Optional[int] = None,
    quorum_met: Optional[bool] = None,
) -> None:
    expectations = {
        "eligible_vote_count": eligible_vote_count,
        "candidate_votes": candidate_votes,
        "non_candidate_votes": non_candidate_votes,
        "defer_votes": defer_votes,
        "distinct_specialty_count": distinct_specialty_count,
        "quorum_met": quorum_met,
    }
    for field, expected in expectations.items():
        if expected is not None:
            assert case[field] == expected, (
                f"{field} should be {expected!r}, got {case[field]!r}"
            )


def assert_ids_equal(actual: Any, expected: str, label: str = "identifier") -> None:
    assert actual == expected, f"{label} should be {expected}, got {actual!r}"


def assert_id_set(records: Iterable[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    actual = sorted(record["id"] for record in records)
    assert actual == sorted(expected_ids), (
        f"listing returned {actual}, expected {sorted(expected_ids)}"
    )
