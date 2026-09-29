"""Domain assertions for the Immigration Legal Services Program contract.

These wrap the generic validators with the vocabulary this PRD uses, so a test
reads as a claim about the contract rather than as dictionary plumbing.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from .api_errors import ERROR_HTTP_STATUS

# ---------------------------------------------------------------------------
# Response-shape helpers
# ---------------------------------------------------------------------------


def created(response) -> Dict[str, Any]:
    """Assert a 201 create and return the ``data`` block."""
    return validate_success(response, 201)


def ok(response) -> Dict[str, Any]:
    """Assert a 200 response and return the ``data`` block."""
    return validate_success(response, 200)


def assert_error(response, error_id: str) -> Dict[str, Any]:
    """Assert the declared error id together with its catalogued HTTP status."""
    assert error_id in ERROR_HTTP_STATUS, (
        "{0} is not in the PRD section 5 error catalogue".format(error_id)
    )
    return validate_error(response, error_id, ERROR_HTTP_STATUS[error_id])


def assert_error_is_one_of(response, error_ids: Iterable[str]) -> Dict[str, Any]:
    """Assert the response is an error drawn from a named set, with its own status.

    Used only where the PRD states a rule but does not pin which catalogued id
    reports it, so more than one id is faithful to the same sentence.
    """
    candidates = list(error_ids)
    for error_id in candidates:
        assert error_id in ERROR_HTTP_STATUS, (
            "{0} is not in the PRD section 5 error catalogue".format(error_id)
        )
    body = response.json()
    actual = (body.get("data") or {}).get("error_id")
    assert actual in candidates, "expected one of {0}, got {1!r} (HTTP {2})".format(
        candidates, actual, response.status_code
    )
    return validate_error(response, actual, ERROR_HTTP_STATUS[actual])


def rows(response) -> List[Dict[str, Any]]:
    """Assert a paginated list response and return just the row list."""
    items, _pagination = validate_paginated(response)
    return items


def page(response):
    """Return both the row list and the pagination ``meta`` of a list response."""
    return validate_paginated(response)


def assert_page_meta(response, **expected: Any) -> List[Dict[str, Any]]:
    """Assert named pagination ``meta`` fields and return the rows."""
    items, meta = validate_paginated(response)
    for field, value in expected.items():
        assert field in meta, "missing pagination field {0!r}".format(field)
        assert meta[field] == value, "meta.{0}: expected {1!r}, got {2!r}".format(
            field, value, meta[field]
        )
    return items


def assert_row_count(response, expected: int) -> List[Dict[str, Any]]:
    """Assert a list response reports exactly ``expected`` total rows."""
    items, pagination = validate_paginated(response)
    total = pagination.get("total_count", pagination.get("total"))
    assert total == expected, "expected total_count {0}, got {1}".format(expected, total)
    return items


def assert_no_rows(response) -> None:
    """Assert a list response is empty in both the rows and the total."""
    assert_row_count(response, 0)


def only_row(response) -> Dict[str, Any]:
    """Assert exactly one row and return it."""
    items = assert_row_count(response, 1)
    return items[0]


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------


def assert_fields(data: Dict[str, Any], **expected: Any) -> None:
    """Assert every named field equals its expected value."""
    for field, value in expected.items():
        assert field in data, "response is missing field {0!r}".format(field)
        assert data[field] == value, "{0}: expected {1!r}, got {2!r}".format(
            field, value, data[field]
        )


def assert_null_fields(data: Dict[str, Any], *fields: str) -> None:
    """Assert every named field is present and null."""
    for field in fields:
        assert field in data, "response is missing field {0!r}".format(field)
        assert data[field] is None, "{0}: expected null, got {1!r}".format(
            field, data[field]
        )


def assert_data_blocks_identical(
    first: Dict[str, Any],
    second: Dict[str, Any],
    ignore: Iterable[str] = (),
    label: str = "",
) -> None:
    """Assert two data blocks agree field for field.

    Used for the immediate-consistency claims: a write response and an
    immediate re-read must not differ, so no derived value may be produced by a
    later sweep. ``label`` only names the pair under comparison in the failure
    message; it never changes what is asserted.
    """
    where = "[{0}] ".format(label) if label else ""
    skip = set(ignore)
    keys_a = set(first) - skip
    keys_b = set(second) - skip
    assert keys_a == keys_b, "{0}field sets differ: {1} vs {2}".format(
        where, sorted(keys_a), sorted(keys_b)
    )
    for key in sorted(keys_a):
        assert first[key] == second[key], "{0}{1} differs: {2!r} vs {3!r}".format(
            where, key, first[key], second[key]
        )


def assert_version_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """Assert an optimistic-concurrency version did not move."""
    assert before["version"] == after["version"], (
        "version moved from {0} to {1} across a request that must not have "
        "written".format(before["version"], after["version"])
    )


def assert_version_advanced_by(
    before: Dict[str, Any], after: Dict[str, Any], delta: int
) -> None:
    """Assert a version advanced by exactly ``delta``."""
    actual = after["version"] - before["version"]
    assert actual == delta, "expected version to advance by {0}, advanced by {1}".format(
        delta, actual
    )


def assert_common_fields(data: Dict[str, Any]) -> None:
    """Assert the shared envelope every entity in this contract carries."""
    for field in ("id", "created_at", "updated_at", "version"):
        assert field in data, "missing common field {0!r}".format(field)
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert is_iso8601_timestamp(data["updated_at"]), data["updated_at"]
    assert isinstance(data["version"], int) and data["version"] >= 1, data["version"]


def assert_utc_millis(value: str) -> None:
    """Assert a timestamp is rendered with millisecond precision and a Z suffix."""
    assert isinstance(value, str), value
    assert value.endswith("Z"), "expected a Z-suffixed UTC instant, got {0!r}".format(
        value
    )
    assert len(value) == 24 and value[19] == ".", (
        "expected millisecond precision, got {0!r}".format(value)
    )


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def round_half_up(value, places: int):
    """Half-up rounding to ``places`` decimals, matching the PRD rounding rule."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def assert_decimal_equals(actual, expected, places: int) -> None:
    """Assert a decimal-valued field equals ``expected`` at ``places`` decimals."""
    assert round_half_up(actual, places) == round_half_up(expected, places), (
        "expected {0} at {1}dp, got {2}".format(expected, places, actual)
    )


def assert_cents(data: Dict[str, Any], field: str, expected: int) -> None:
    """Assert a money field is an exact integer cent amount."""
    actual = data[field]
    assert isinstance(actual, int), "{0} must be integer cents, got {1!r}".format(
        field, actual
    )
    assert actual == expected, "{0}: expected {1}, got {2}".format(
        field, expected, actual
    )


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------


def assert_slot_conservation(cycle: Dict[str, Any]) -> None:
    """general + detained + available == total_case_slots, always."""
    total = (
        cycle["general_slots_consumed"]
        + cycle["detained_slots_consumed"]
        + cycle["available_slot_count"]
    )
    assert total == cycle["total_case_slots"], (
        "slot conservation broken: {0} + {1} + {2} != {3}".format(
            cycle["general_slots_consumed"],
            cycle["detained_slots_consumed"],
            cycle["available_slot_count"],
            cycle["total_case_slots"],
        )
    )


def assert_readiness(
    matter: Dict[str, Any],
    index: Optional[str] = None,
    ready_strict: Optional[bool] = None,
    blocking_count: Optional[int] = None,
    gate: Optional[str] = None,
) -> None:
    """Assert the readiness triple (plus the selected gate) on a matter read."""
    if index is not None:
        assert_decimal_equals(matter["readiness_index_weighted"], index, 4)
    if ready_strict is not None:
        assert matter["readiness_ready_strict"] is ready_strict, matter[
            "readiness_ready_strict"
        ]
    if blocking_count is not None:
        assert matter["evidence_blocking_count"] == blocking_count, matter[
            "evidence_blocking_count"
        ]
    if gate is not None:
        assert matter["readiness_gate_applied"] == gate, matter["readiness_gate_applied"]


def assert_matter_dimensions(
    matter: Dict[str, Any],
    representation_status: Optional[str] = None,
    filing_status: Optional[str] = None,
) -> None:
    """Assert one or both of the matter's two independent status dimensions."""
    if representation_status is not None:
        assert matter["representation_status"] == representation_status, matter[
            "representation_status"
        ]
    if filing_status is not None:
        assert matter["filing_status"] == filing_status, matter["filing_status"]


def data_of(response) -> Dict[str, Any]:
    """Return the ``data`` block of a successful response without status checks."""
    return get_success_data(response)
