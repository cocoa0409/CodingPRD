"""
Domain assertion helpers.

These wrap the generic format assertions with the two conservation identities the
PRD declares as non-negotiable, plus the small structural checks that repeat in
almost every test (common fields present, money is a JSON integer, four-way
ledger decomposition, placement encumbrance mirror, seat conservation).
"""

from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# Tolerance for the two-decimal computed scores and the four-decimal variance.
SCORE_TOL = 0.005
VARIANCE_TOL = 0.00005


def assert_common_fields(resource: Dict[str, Any]) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource.get('id')!r}"
    assert "_" not in str(resource["id"]), "id must carry no type prefix"
    assert is_iso8601_timestamp(resource["created_at"]), resource.get("created_at")
    assert is_iso8601_timestamp(resource["updated_at"]), resource.get("updated_at")
    assert isinstance(resource["version"], int), "version must be an integer"
    assert resource["version"] >= 1, "version starts at 1"


def assert_integer_cents(resource: Dict[str, Any], *field_names: str) -> None:
    """Every field whose name ends in _cents is a JSON integer, never a float."""
    names = field_names or [k for k in resource if k.endswith("_cents")]
    for name in names:
        value = resource.get(name)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{name} must be an integer number of cents, got {value!r}"
        )


def assert_ledger_identity(account: Dict[str, Any]) -> None:
    """authorized_cents always equals available + encumbered + disbursed."""
    total = (
        account["available_cents"]
        + account["encumbered_cents"]
        + account["disbursed_cents"]
    )
    assert account["authorized_cents"] == total, (
        "Conservation identity broken: authorized "
        f"{account['authorized_cents']} != available {account['available_cents']} "
        f"+ encumbered {account['encumbered_cents']} "
        f"+ disbursed {account['disbursed_cents']}"
    )


def assert_ledger(
    account: Dict[str, Any],
    available: Optional[int] = None,
    encumbered: Optional[int] = None,
    disbursed: Optional[int] = None,
) -> None:
    """Assert the account's ledger decomposition and its conservation identity."""
    assert_ledger_identity(account)
    if available is not None:
        assert account["available_cents"] == available, "available_cents"
    if encumbered is not None:
        assert account["encumbered_cents"] == encumbered, "encumbered_cents"
    if disbursed is not None:
        assert account["disbursed_cents"] == disbursed, "disbursed_cents"


def assert_placement_encumbrance_mirror(placement: Dict[str, Any]) -> None:
    """
    The placement's encumbrance_cents mirrors its four components: the unpaid
    remainder of the contract plus the addendum, transport and reserve components.
    """
    expected = (
        max(0, placement["contract_encumbrance_cents"] - placement["paid_total_ytd_cents"])
        + placement["addendum_encumbrance_cents"]
        + placement["transport_encumbrance_cents"]
        + placement["transition_reserve_cents"]
    )
    assert placement["encumbrance_cents"] == expected, (
        f"encumbrance_cents {placement['encumbrance_cents']} does not mirror its "
        f"components (expected {expected})"
    )


def assert_seat_conservation(route: Dict[str, Any]) -> None:
    """seat_capacity always equals seats_available + seats_committed."""
    assert route["seat_capacity"] == route["seats_available"] + route["seats_committed"], (
        f"Seat conservation broken on route {route.get('route_code')}: capacity "
        f"{route['seat_capacity']} != available {route['seats_available']} + "
        f"committed {route['seats_committed']}"
    )


def assert_route_seats(
    route: Dict[str, Any], committed: int, available: int
) -> None:
    assert_seat_conservation(route)
    assert route["seats_committed"] == committed, "seats_committed"
    assert route["seats_available"] == available, "seats_available"


def assert_score(actual: float, expected: float) -> None:
    """A report_score or readiness aggregate is rounded half up to two places."""
    assert actual == pytest.approx(expected, abs=SCORE_TOL), (
        f"Expected score {expected}, got {actual}"
    )


def assert_variance(actual: float, expected: float) -> None:
    """variance_pct is rounded half up to four decimal places."""
    assert actual == pytest.approx(expected, abs=VARIANCE_TOL), (
        f"Expected variance_pct {expected}, got {actual}"
    )


def assert_quarter_hour(hours: float) -> None:
    """Service hours are decimal numbers in quarter-hour increments."""
    assert round(hours / 0.25) == pytest.approx(hours / 0.25, abs=1e-9), (
        f"{hours} is not an exact multiple of 0.25"
    )


def assert_meta_envelope(body: Dict[str, Any]) -> None:
    """meta.api_request_id starts with req_ and the timestamp has three places."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    stamp = meta["api_request_timestamp"]
    assert is_iso8601_timestamp(stamp), stamp
    assert "." in stamp and len(stamp.split(".")[1]) == 4, (
        f"api_request_timestamp needs three fractional digits: {stamp}"
    )


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    assert meta["limit"] == limit, "meta.limit"
    assert meta["offset"] == offset, "meta.offset"
    assert meta["total_count"] == total_count, "meta.total_count"
    assert meta["has_more"] is has_more, "meta.has_more"


def assert_invoice_lines(
    invoice: Dict[str, Any],
    tuition: int,
    residential: int,
    service_total: int,
    transport: int,
    gross: int,
) -> None:
    """The four billing lines are each rounded before they are summed into gross."""
    assert invoice["tuition_line_cents"] == tuition, "tuition_line_cents"
    assert invoice["residential_line_cents"] == residential, "residential_line_cents"
    assert invoice["service_lines_total_cents"] == service_total, (
        "service_lines_total_cents"
    )
    assert invoice["transport_line_cents"] == transport, "transport_line_cents"
    assert invoice["gross_billable_cents"] == gross, "gross_billable_cents"
    assert (
        tuition + residential + service_total + transport == gross
    ), "gross must be the sum of the four rounded lines"


def _instant_key(value: str) -> str:
    """
    Normalise an ISO 8601 UTC instant to the point in time it denotes.

    The PRD pins the *value* of every transition stamp — submitted_at, decided_at,
    contract_executed_at, activated_at, terminated_at, promoted_at — to "the
    logical clock's current instant", and it pins the three-fractional-digit
    rendering only for created_at, updated_at and meta.api_request_timestamp. A
    stamp echoed as 2026-09-01T08:00:00Z and one rendered as
    2026-09-01T08:00:00.000Z therefore both satisfy the PRD, so instants are
    compared as instants rather than byte for byte.
    """
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    from datetime import datetime, timezone

    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def assert_instant_equals(actual: Optional[str], expected: str) -> None:
    """A transition stamp holds exactly the logical clock instant it was taken at."""
    assert actual is not None, f"expected the instant {expected}, got null"
    assert _instant_key(actual) == _instant_key(expected), (
        f"expected the instant {expected}, got {actual}"
    )


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    """A read never mutates: version and updated_at must both be untouched."""
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']}"
    )
    assert after["updated_at"] == before["updated_at"], "updated_at moved"
