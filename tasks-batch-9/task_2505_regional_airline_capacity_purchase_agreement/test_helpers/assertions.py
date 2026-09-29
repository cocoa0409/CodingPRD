"""Domain assertions.

These wrap the repetitive checks the contract demands — money precision, version
progression, the departure-ledger identity, list ordering — so that a test body
reads as a statement about the business rule under examination.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import BLOCK_HOURS_TOLERANCE, MONEY_TOLERANCE
from .types import JsonDict

# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


def round_half_up(value: float, places: int = 2) -> float:
    """Round to ``places`` decimals, half away from zero, as the contract requires."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def money(value: float) -> float:
    """Round a money figure half-up to two decimal places."""
    return round_half_up(value, 2)


def block_hours(value: float) -> float:
    """Round a block-hour figure half-up to three decimal places."""
    return round_half_up(value, 3)


# ---------------------------------------------------------------------------
# Scalar comparisons
# ---------------------------------------------------------------------------


def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    """Assert a two-decimal money figure matches to the cent."""
    assert actual is not None, f"{label} is missing"
    assert float(actual) == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label} should be {expected:.2f} but was {actual}"
    )


def assert_block_hours(actual: Any, expected: float, label: str = "block hours") -> None:
    """Assert a three-decimal block-hour figure matches to the thousandth."""
    assert actual is not None, f"{label} is missing"
    assert float(actual) == pytest.approx(expected, abs=BLOCK_HOURS_TOLERANCE), (
        f"{label} should be {expected:.3f} but was {actual}"
    )


def assert_percentage(actual: Any, expected: float, label: str = "percentage") -> None:
    """Assert a two-decimal percentage figure matches to the hundredth."""
    assert actual is not None, f"{label} is missing"
    assert float(actual) == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label} should be {expected:.2f} but was {actual}"
    )


def assert_status(resource: JsonDict, expected: str, field: str = "status") -> None:
    """Assert a resource's lifecycle attribute reads the expected value."""
    assert resource.get(field) == expected, (
        f"{field} should be {expected} but was {resource.get(field)}"
    )


def assert_version(resource: JsonDict, expected: int) -> None:
    """Assert a resource's version counter stands at the expected value."""
    assert resource.get("version") == expected, (
        f"version should be {expected} but was {resource.get('version')}"
    )


def assert_version_bumped_by(before: JsonDict, after: JsonDict, expected_delta: int = 1) -> None:
    """Assert a resource's version moved by exactly the expected amount."""
    delta = after["version"] - before["version"]
    assert delta == expected_delta, (
        f"version should have moved by {expected_delta} but moved by {delta} "
        f"({before['version']} to {after['version']})"
    )


def assert_is_null(resource: JsonDict, *fields: str) -> None:
    """Assert each named attribute is carried as null."""
    for field in fields:
        assert field in resource, f"{field} should be present on the resource"
        assert resource[field] is None, f"{field} should be null but was {resource[field]}"


# ---------------------------------------------------------------------------
# Common resource properties
# ---------------------------------------------------------------------------


def assert_common_fields(resource: JsonDict, expected_version: Optional[int] = None) -> None:
    """Assert the five properties every resource carries are well formed.

    The identifier is a bare UUID with no prefix, both timestamps are ISO 8601 UTC
    instants, and the version counter is a positive integer.
    """
    resource_id = resource.get("id")
    assert isinstance(resource_id, str) and is_valid_uuid(resource_id), (
        f"id should be a UUID with no prefix but was {resource_id!r}"
    )
    for field in ("created_at", "updated_at"):
        value = resource.get(field)
        assert isinstance(value, str) and is_iso8601_timestamp(value), (
            f"{field} should be an ISO 8601 UTC instant but was {value!r}"
        )
    version = resource.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"version should be a positive integer but was {version!r}"
    )
    if expected_version is not None:
        assert version == expected_version, (
            f"version should be {expected_version} but was {version}"
        )


def assert_fields_absent_from_request(resource: JsonDict, submitted: JsonDict, *fields: str) -> None:
    """Assert server-generated attributes did not take their values from the request."""
    for field in fields:
        assert field not in submitted, f"the test submitted {field}, which defeats the check"
        assert field in resource, f"{field} should be generated by the server"


# ---------------------------------------------------------------------------
# Ledger conservation
# ---------------------------------------------------------------------------


def assert_departure_ledger_identity(cycle: JsonDict) -> None:
    """Assert the month's departure ledger balances against its published count.

    The ledger total must equal the published departure count at every observable
    moment, and must equal the sum of its three positions.
    """
    published = cycle["published_departures"]
    completed = cycle["metric_completed_departures"]
    controllable = cycle["cancelled_controllable_count"]
    uncontrollable = cycle["cancelled_uncontrollable_count"]
    total = cycle["departure_ledger_total"]

    assert completed == published - controllable - uncontrollable, (
        "metric_completed_departures should be the published count less both "
        f"cancellation counters: {published} - {controllable} - {uncontrollable} "
        f"is not {completed}"
    )
    assert total == completed + controllable + uncontrollable, (
        "departure_ledger_total should be the sum of the three ledger positions but "
        f"{total} is not {completed} + {controllable} + {uncontrollable}"
    )
    assert total == published, (
        f"departure_ledger_total should stay equal to published_departures "
        f"({published}) but was {total}"
    )


def assert_settled_money(agreement: JsonDict, expected_settled: float, expected_open_drafts: int) -> None:
    """Assert the agreement's conserved settlement figures."""
    assert_money(agreement["settled_to_date_usd"], expected_settled, "settled_to_date_usd")
    assert agreement["open_invoice_count"] == expected_open_drafts, (
        f"open_invoice_count should be {expected_open_drafts} but was "
        f"{agreement['open_invoice_count']}"
    )


# ---------------------------------------------------------------------------
# Crew-base staffing picture
# ---------------------------------------------------------------------------


def assert_staffing_picture(
    base: JsonDict,
    *,
    line_qualified: Optional[int] = None,
    in_training: Optional[int] = None,
    assigned_aircraft: Optional[int] = None,
    required_pilots: Optional[int] = None,
    headcount_shortfall: Optional[int] = None,
    pipeline_shortfall: Optional[int] = None,
    posture: Optional[str] = None,
    allocatable_aircraft: Optional[int] = None,
) -> None:
    """Assert whichever of the base's derived staffing figures the caller named."""
    expectations = {
        "line_qualified_pilot_count": line_qualified,
        "in_training_pilot_count": in_training,
        "assigned_aircraft_count": assigned_aircraft,
        "required_pilot_count": required_pilots,
        "headcount_shortfall": headcount_shortfall,
        "pipeline_shortfall": pipeline_shortfall,
        "staffing_posture": posture,
        "allocatable_aircraft_count": allocatable_aircraft,
    }
    for field, expected in expectations.items():
        if expected is None:
            continue
        assert base.get(field) == expected, (
            f"{field} should be {expected} but was {base.get(field)}"
        )


# ---------------------------------------------------------------------------
# List ordering and pagination
# ---------------------------------------------------------------------------


def assert_ordered_by_created_at(records: Sequence[JsonDict]) -> None:
    """Assert a collection page is ordered by creation instant then identifier."""
    keys = [(record["created_at"], record["id"]) for record in records]
    assert keys == sorted(keys), (
        "records should be ordered by created_at ascending with id as the tie-break, "
        f"but arrived as {keys}"
    )


def default_list_order(records: Iterable[JsonDict]) -> List[JsonDict]:
    """The order PRD 2.3 requires of every list: created_at ascending, id ascending.

    The service reads a logical clock that only an administrator advances, so
    records created inside one test normally share a creation instant and the
    identifier tie-break is what actually decides their order.
    """
    return sorted(records, key=lambda record: (record["created_at"], record["id"]))


def grounding_candidate_order(tails: Iterable[JsonDict]) -> List[JsonDict]:
    """The order PRD 3.3 grounds tails in: created_at descending, tail_number ascending.

    Tails registered inside one test share a creation instant under the logical
    clock, so the lexicographic tail-number tie-break is what selects the victim.
    """
    ranked = sorted(tails, key=lambda tail: tail["tail_number"])
    ranked.sort(key=lambda tail: tail["created_at"], reverse=True)
    return ranked


def restoration_candidate_order(tails: Iterable[JsonDict]) -> List[JsonDict]:
    """The order PRD 3.3 returns tails to service in: created_at then tail_number ascending."""
    return sorted(tails, key=lambda tail: (tail["created_at"], tail["tail_number"]))


def assert_page_meta(
    meta: Dict[str, Any],
    *,
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    """Assert the pagination envelope reports the window and the full result size."""
    assert meta.get("limit") == limit, f"meta.limit should be {limit} but was {meta.get('limit')}"
    assert meta.get("offset") == offset, (
        f"meta.offset should be {offset} but was {meta.get('offset')}"
    )
    assert meta.get("total_count") == total_count, (
        f"meta.total_count should be {total_count} but was {meta.get('total_count')}"
    )
    assert meta.get("has_more") is has_more, (
        f"meta.has_more should be {has_more} but was {meta.get('has_more')}"
    )


def ids_of(records: Iterable[JsonDict]) -> List[str]:
    """The identifiers of a collection of records, in the order they arrived."""
    return [record["id"] for record in records]


__all__ = [
    "round_half_up",
    "money",
    "block_hours",
    "assert_money",
    "assert_block_hours",
    "assert_percentage",
    "assert_status",
    "assert_version",
    "assert_version_bumped_by",
    "assert_is_null",
    "assert_common_fields",
    "assert_fields_absent_from_request",
    "assert_departure_ledger_identity",
    "assert_settled_money",
    "assert_staffing_picture",
    "assert_ordered_by_created_at",
    "default_list_order",
    "grounding_candidate_order",
    "restoration_candidate_order",
    "assert_page_meta",
    "ids_of",
]
