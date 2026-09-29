"""Domain assertions: envelope shape, entity shape, precision and instants."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    API_REQUEST_ID_PREFIX,
    COLLATERAL_INCREMENT_USD,
)
from .types import PRICING_NODE_ABSENT_FIELDS, PRICING_NODE_FIELDS

# ---------------------------------------------------------------------------
# Instant canonicalisation
#
# PRD section 2.2 renders every server-generated timestamp "in ISO-8601 UTC
# form with exactly three fractional-second digits".  Instants that a test
# supplies itself — a response deadline, a window bound, an hour start — come
# back as the same instant rather than as the same string, so every comparison
# below is made on the canonical instant and never on the raw sub-second width.
# ---------------------------------------------------------------------------


def canonical_instant(value: str) -> str:
    """Reduce an ISO-8601 UTC instant to a canonical millisecond string."""
    assert isinstance(value, str), f"expected an ISO-8601 string, got {value!r}"
    raw = value.strip()
    if raw.endswith("Z"):
        body = raw[:-1]
    elif raw.endswith("+00:00"):
        body = raw[:-6]
    else:
        raise AssertionError(f"expected a UTC instant, got {value!r}")
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = body, "000"
    return f"{head}.{frac}Z"


def assert_instant_equals(actual: Optional[str], expected: str,
                          label: str = "instant") -> None:
    """Assert two ISO-8601 UTC instants denote the same millisecond."""
    assert actual is not None, f"{label} must not be null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label} expected {expected}, got {actual}"
    )


def assert_date_equals(actual: Optional[str], expected_date: str,
                       label: str = "date") -> None:
    """Assert a datetime field falls on the expected calendar date."""
    assert actual is not None, f"{label} must not be null"
    assert canonical_instant(actual).startswith(expected_date), (
        f"{label} expected the date {expected_date}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """Every response carries `meta.api_request_id` and a UTC timestamp."""
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith(API_REQUEST_ID_PREFIX), (
        "meta.api_request_id must begin with 'req_', got "
        f"{meta.get('api_request_id')!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        f"meta.api_request_timestamp must be ISO-8601, got "
        f"{meta.get('api_request_timestamp')!r}"
    )


def assert_error_envelope(response) -> Dict[str, Any]:
    """An error envelope carries only the two request fields in `meta`."""
    body = response.json()
    assert body["response_type"] == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )
    assert_envelope_meta(body)
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "an error envelope's meta contains only the two request fields, got "
        f"{sorted(body['meta'].keys())}"
    )
    data = body["data"]
    assert set(data.keys()) == {"error_id", "message"}, (
        f"error data carries error_id and message, got {sorted(data.keys())}"
    )
    return data


def assert_page_meta(meta: Dict[str, Any], *, total_count: int,
                     limit: int, offset: int, has_more: bool) -> None:
    """`meta` of a list response carries the four pagination fields."""
    assert meta["total_count"] == total_count, (
        f"total_count expected {total_count}, got {meta['total_count']}"
    )
    assert meta["limit"] == limit, f"limit expected {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, (
        f"offset expected {offset}, got {meta['offset']}"
    )
    assert meta["has_more"] is has_more, (
        f"has_more expected {has_more}, got {meta['has_more']}"
    )


# ---------------------------------------------------------------------------
# Entity shape
# ---------------------------------------------------------------------------


def assert_common_fields(data: Dict[str, Any],
                         expected_version: Optional[int] = None) -> None:
    """Every entity but `PricingNode` carries all four common fields."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a UUID with no prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO-8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO-8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )
    if expected_version is not None:
        assert data["version"] == expected_version, (
            f"version expected {expected_version}, got {data['version']}"
        )


def assert_pricing_node_shape(data: Dict[str, Any]) -> None:
    """`PricingNode` carries only `id` and `created_at` of the common fields."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO-8601, got {data.get('created_at')!r}"
    )
    for absent in PRICING_NODE_ABSENT_FIELDS:
        assert absent not in data, (
            f"a pricing node carries no {absent}; both updated_at and version "
            f"are absent from it entirely, got {sorted(data.keys())}"
        )
    for declared in PRICING_NODE_FIELDS:
        assert declared in data, f"a pricing node must carry {declared}"


def assert_all_null(data: Dict[str, Any], fields: List[str]) -> None:
    """Assert each named field is present and null."""
    for field in fields:
        assert field in data, f"{field} must be present on the response"
        assert data[field] is None, f"{field} must be null, got {data[field]!r}"


def assert_absent_or_null(data: Dict[str, Any], field: str) -> None:
    """Assert an optional field is either absent or null."""
    assert data.get(field) is None, (
        f"{field} must be null, got {data.get(field)!r}"
    )


def assert_version_advanced_by(before: int, after: int, expected: int,
                              label: str = "version") -> None:
    """Assert a row's version advanced by exactly the expected number."""
    assert after == before + expected, (
        f"{label} expected {before} + {expected} = {before + expected}, "
        f"got {after}"
    )


# ---------------------------------------------------------------------------
# Precision
# ---------------------------------------------------------------------------


def _decimals(value: float) -> int:
    text = f"{value!r}"
    if "e" in text or "E" in text:
        return 0
    return len(text.split(".")[1]) if "." in text else 0


def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    """Assert a monetary amount equals the expected value to the cent."""
    assert actual is not None, f"{label} must not be null"
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label} must be numeric, got {actual!r}"
    )
    assert abs(float(actual) - expected) < 0.005, (
        f"{label} expected {expected:.2f}, got {actual}"
    )
    assert _decimals(float(actual)) <= 2, (
        f"{label} is carried to two decimal places, got {actual}"
    )


def assert_score(actual: Any, expected: float, label: str = "score") -> None:
    """Assert a nought-to-one-hundred score to two decimal places."""
    assert actual is not None, f"{label} must not be null"
    assert abs(float(actual) - expected) < 0.005, (
        f"{label} expected {expected:.2f}, got {actual}"
    )
    assert _decimals(float(actual)) <= 2, (
        f"{label} is carried to two decimal places, got {actual}"
    )


def assert_mw(actual: Any, expected: float, label: str = "megawatts",
              places: int = 3) -> None:
    """Assert a megawatt quantity to three (or four) decimal places."""
    assert actual is not None, f"{label} must not be null"
    tolerance = 0.5 * 10 ** (-places)
    assert abs(float(actual) - expected) < tolerance, (
        f"{label} expected {expected}, got {actual}"
    )
    assert _decimals(float(actual)) <= places, (
        f"{label} is carried to {places} decimal places, got {actual}"
    )


def assert_mwh(actual: Any, expected: float, label: str = "megawatt-hours",
               places: int = 4) -> None:
    """Assert a megawatt-hour quantity to four decimal places."""
    assert_mw(actual, expected, label, places)


def assert_share_pct(actual: Any, expected: float,
                     label: str = "allocation_share_pct") -> None:
    """`allocation_share_pct` is carried to four decimal places."""
    assert actual is not None, f"{label} must not be null"
    assert abs(float(actual) - expected) < 0.00005, (
        f"{label} expected {expected}, got {actual}"
    )
    assert _decimals(float(actual)) <= 4, (
        f"{label} is carried to four decimal places, got {actual}"
    )


def assert_index_price(actual: Any, expected: float,
                       label: str = "weighted_avg_index_usd_per_mwh") -> None:
    """The weighted average index is carried to four decimal places."""
    assert actual is not None, f"{label} must not be null"
    assert abs(float(actual) - expected) < 0.00005, (
        f"{label} expected {expected}, got {actual}"
    )
    assert _decimals(float(actual)) <= 4, (
        f"{label} is carried to four decimal places, got {actual}"
    )


def assert_whole_increment(actual: Any, label: str = "requirement") -> None:
    """A non-zero collateral requirement is a whole 250,000 increment."""
    assert actual is not None, f"{label} must not be null"
    value = float(actual)
    remainder = value % COLLATERAL_INCREMENT_USD
    assert remainder < 0.005 or COLLATERAL_INCREMENT_USD - remainder < 0.005, (
        f"{label} is rounded up to the next whole 250,000 increment, got {actual}"
    )


# ---------------------------------------------------------------------------
# Settlement sign convention (PRD section 2.6)
# ---------------------------------------------------------------------------


def assert_settlement_sign_convention(period: Dict[str, Any]) -> None:
    """A positive net is owed by the seller, a negative net by the buyer."""
    net = float(period["net_settlement_usd"])
    seller = float(period["seller_pays_usd"])
    buyer = float(period["buyer_pays_usd"])
    if net > 0.004:
        assert_money(seller, net, "seller_pays_usd")
        assert_money(buyer, 0.00, "buyer_pays_usd")
    elif net < -0.004:
        assert_money(seller, 0.00, "seller_pays_usd")
        assert_money(buyer, abs(net), "buyer_pays_usd")
    else:
        assert_money(seller, 0.00, "seller_pays_usd")
        assert_money(buyer, 0.00, "buyer_pays_usd")


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


def assert_sorted_by_created_at(rows: List[Dict[str, Any]]) -> None:
    """The default sort is `created_at` ascending."""
    stamps = [canonical_instant(row["created_at"]) for row in rows]
    assert stamps == sorted(stamps), (
        f"rows must be sorted by created_at ascending, got {stamps}"
    )


def assert_breakdown_rows(breakdown: List[Dict[str, Any]],
                          expected: List[tuple]) -> None:
    """Assert `allocation_breakdown` matches the expected ordered rows.

    Each expected entry is an ``(offtaker_id, quantity_mwh)`` pair; the
    breakdown is emitted in the largest-remainder sort order.
    """
    assert len(breakdown) == len(expected), (
        f"allocation_breakdown expected {len(expected)} rows, got {breakdown}"
    )
    for index, (row, (offtaker_id, quantity)) in enumerate(zip(breakdown, expected)):
        assert set(row.keys()) == {"offtaker_id", "quantity_mwh"}, (
            "each breakdown row carries an offtaker_id and a quantity_mwh, got "
            f"{sorted(row.keys())}"
        )
        assert row["offtaker_id"] == offtaker_id, (
            f"breakdown row {index} expected offtaker {offtaker_id}, got {row}"
        )
        assert row["quantity_mwh"] == quantity, (
            f"breakdown row {index} expected {quantity} MWh, got {row}"
        )


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def row_by_id(rows: List[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    matches = [row for row in rows if row["id"] == row_id]
    assert matches, f"row {row_id} not present among {ids_of(rows)}"
    return matches[0]


def row_by(rows: List[Dict[str, Any]], field: str, value: Any) -> Dict[str, Any]:
    matches = [row for row in rows if row.get(field) == value]
    assert len(matches) == 1, (
        f"expected exactly one row with {field} == {value!r}, got {len(matches)}"
    )
    return matches[0]
