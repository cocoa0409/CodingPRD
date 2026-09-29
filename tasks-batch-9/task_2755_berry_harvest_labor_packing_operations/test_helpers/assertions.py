"""
Domain assertions for the Berry Harvest Ops API.

These wrap the generic helpers of ``prd_bench_local_runner.testing`` with the
specific shapes the PRD promises: the audit triple of section 2.4, the
append-only water register of the same section, the precision families of
section 2.6, and the pagination meta of section 2.3.

Decimal quantities are compared at their declared precision rather than by raw
equality, because a JSON number rendered as ``10.0`` and one rendered as
``10.00`` are the same two-decimal value.
"""

from typing import Any, Dict, Optional, Sequence

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .api_client import canonical_instant

# ─── Envelope and identity ────────────────────────────────────────────────


def assert_identifier(value: Any, label: str = "id") -> None:
    """PRD 2.4: an `id` is "a server-minted UUID carrying no type prefix"."""
    assert is_valid_uuid(value), f"{label} is not a bare UUID: {value!r}"


def assert_three_fractional_digits(value: Any, label: str) -> None:
    """
    PRD 2.4 renders audit timestamps "with exactly three fractional digits".
    """
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} is not ISO 8601 UTC: {value!r}"
    assert value.endswith("Z"), f"{label} must end in Z: {value!r}"
    body = value[:-1]
    assert "." in body, f"{label} must carry fractional digits: {value!r}"
    fraction = body.split(".", 1)[1]
    assert len(fraction) == 3, (
        f"{label} must carry exactly three fractional digits: {value!r}"
    )


def assert_audit_triple(resource: Dict[str, Any], label: str = "resource") -> None:
    """
    PRD 2.4: ten of the eleven families carry "`created_at` and `updated_at`
    ... and `version`, an integer that begins at 1 when the resource is
    created".
    """
    assert_identifier(resource.get("id"), f"{label}.id")
    assert_three_fractional_digits(resource.get("created_at"), f"{label}.created_at")
    assert_three_fractional_digits(resource.get("updated_at"), f"{label}.updated_at")
    assert isinstance(resource.get("version"), int), (
        f"{label}.version must be an integer, got {resource.get('version')!r}"
    )
    assert resource["version"] >= 1, f"{label}.version must be at least 1"


def assert_water_register_shape(water_test: Dict[str, Any]) -> None:
    """
    PRD 2.4: "A water sample carries only `id` and `created_at`. It has no
    `updated_at` and no `version` field at all".
    """
    assert_identifier(water_test.get("id"), "water_test.id")
    assert_three_fractional_digits(
        water_test.get("created_at"), "water_test.created_at"
    )
    assert "updated_at" not in water_test, (
        "WaterTest must not carry updated_at (PRD 2.4 append-only register)"
    )
    assert "version" not in water_test, (
        "WaterTest must not carry version (PRD 2.4 append-only register)"
    )


def assert_request_meta(meta: Dict[str, Any]) -> None:
    """
    PRD 2.2: the `api_request_id` "starts with `req_`" and the
    `api_request_timestamp` is "a server-generated ISO 8601 UTC timestamp with
    three fractional digits".
    """
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"api_request_id must start with 'req_': {request_id!r}"
    )
    assert_three_fractional_digits(
        meta.get("api_request_timestamp"), "meta.api_request_timestamp"
    )


def assert_object_response(response) -> None:
    """PRD 2.2: response_type is "object" for a single resource."""
    body = response.json()
    assert body.get("response_type") == "object", (
        f"Expected response_type 'object', got {body.get('response_type')!r}"
    )
    assert_request_meta(body["meta"])


def assert_array_response(response) -> None:
    """PRD 2.2: response_type is "array" for a list of resources."""
    body = response.json()
    assert body.get("response_type") == "array", (
        f"Expected response_type 'array', got {body.get('response_type')!r}"
    )
    assert_request_meta(body["meta"])


def assert_page_meta(
    meta: Dict[str, Any],
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    """
    PRD 2.3: the meta of a list response carries "`limit` and `offset` echoing
    the effective values used for the page, `total_count` giving the number of
    records that match the filter before pagination is applied, and `has_more`
    reporting whether any matching record remains beyond the current page".
    """
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"total_count {meta['total_count']} != {expected_total}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, f"limit {meta['limit']} != {expected_limit}"
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"offset {meta['offset']} != {expected_offset}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"has_more {meta['has_more']} != {expected_has_more}"
        )


# ─── Precision families (PRD 2.6) ─────────────────────────────────────────


def _as_number(value: Any, label: str) -> float:
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a JSON number, got {value!r}"
    )
    return float(value)


def assert_decimal_value(value: Any, expected: float, places: int, label: str) -> None:
    """Compare a decimal quantity at its declared number of decimal places."""
    actual = _as_number(value, label)
    assert round(actual, places) == round(float(expected), places), (
        f"{label} expected {expected} at {places}dp, got {value}"
    )


def assert_pounds(value: Any, expected: float, label: str = "pounds") -> None:
    """PRD 2.6: "Pounds carry 2 decimal places and are rounded half up"."""
    assert_decimal_value(value, expected, 2, label)


def assert_hours(value: Any, expected: float, label: str = "hours") -> None:
    """PRD 2.6: "Hours carry 2 decimal places and are rounded half up"."""
    assert_decimal_value(value, expected, 2, label)


def assert_rate(value: Any, expected: float, label: str = "rate") -> None:
    """PRD 2.6: rates in pounds per hour "carry 2 decimal places"."""
    assert_decimal_value(value, expected, 2, label)


def assert_ratio(value: Any, expected: float, label: str = "ratio") -> None:
    """PRD 2.6: "Ratios carry 4 decimal places, rounded half up"."""
    assert_decimal_value(value, expected, 4, label)


def assert_geomean(value: Any, expected: float, label: str = "water_geomean_mpn") -> None:
    """PRD 2.6: "Water bacteriology carries 1 decimal place, rounded half up"."""
    assert_decimal_value(value, expected, 1, label)


def assert_temperature(value: Any, expected: float, label: str = "temperature") -> None:
    """PRD 2.6: temperatures "carry 1 decimal place"."""
    assert_decimal_value(value, expected, 1, label)


def assert_brix(value: Any, expected: float, label: str = "forecast_brix") -> None:
    """PRD 2.6: "**Brix** carries 1 decimal place: `forecast_brix`"."""
    assert_decimal_value(value, expected, 1, label)


def assert_cents(value: Any, expected: int, label: str = "cents") -> None:
    """
    PRD 2.6: "Money is held exclusively in **integer cents**. There is no
    fractional-cent field anywhere in the system".
    """
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )
    assert value == expected, f"{label} expected {expected} cents, got {value}"


def assert_instant(value: Any, expected: str, label: str = "instant") -> None:
    """Compare two RFC 3339 UTC instants irrespective of sub-second width."""
    assert canonical_instant(value) == canonical_instant(expected), (
        f"{label} expected {expected}, got {value}"
    )


def assert_unset(resource: Dict[str, Any], field: str, label: str = "resource") -> None:
    """A field the PRD describes as carrying no value: absent or JSON null."""
    assert resource.get(field) is None, (
        f"{label}.{field} should carry no value, got {resource.get(field)!r}"
    )


# ─── Cross-cutting domain checks ──────────────────────────────────────────


def assert_lot_mass_balance(lot: Dict[str, Any]) -> None:
    """
    PRD 3.8: "A lot's `available_lbs` is always `net_packed_lbs` less its
    `allocated_lbs`, `repack_out_lbs`, `cull_lbs` and `optical_reject_lbs`, at
    two decimals".
    """
    if lot.get("disposition_status") in ("REJECTED", "REPACKED"):
        assert_pounds(lot["available_lbs"], 0.00, "lot.available_lbs")
        return
    expected = (
        _as_number(lot["net_packed_lbs"], "lot.net_packed_lbs")
        - _as_number(lot.get("allocated_lbs", 0.0), "lot.allocated_lbs")
        - _as_number(lot.get("repack_out_lbs", 0.0), "lot.repack_out_lbs")
        - _as_number(lot.get("cull_lbs", 0.0), "lot.cull_lbs")
        - _as_number(lot.get("optical_reject_lbs", 0.0), "lot.optical_reject_lbs")
    )
    assert_pounds(lot["available_lbs"], expected, "lot.available_lbs")


def assert_commitment_exposure(
    commitment: Dict[str, Any],
    expected_committed: float,
    expected_shipped: float,
) -> None:
    """
    PRD 3.7: "`open_lbs` is `volume_commitment_lbs` less `committed_lbs`,
    floored at 0.00 and carried to two decimals" and "`fill_pct` is
    `shipped_lbs` divided by `volume_commitment_lbs` at four decimals half up".
    """
    volume = _as_number(
        commitment["volume_commitment_lbs"], "commitment.volume_commitment_lbs"
    )
    assert_pounds(commitment["committed_lbs"], expected_committed, "committed_lbs")
    assert_pounds(commitment["shipped_lbs"], expected_shipped, "shipped_lbs")
    assert_pounds(
        commitment["open_lbs"], max(0.0, volume - expected_committed), "open_lbs"
    )
    assert_ratio(commitment["fill_pct"], round(expected_shipped / volume, 4), "fill_pct")


def assert_status(resource: Dict[str, Any], field: str, expected: str) -> None:
    """Assert a lifecycle field carries exactly the expected member."""
    assert resource.get(field) == expected, (
        f"{field} expected {expected!r}, got {resource.get(field)!r}"
    )


def assert_all_distinct(values: Sequence[Any], label: str = "values") -> None:
    """Assert a sequence has no repeated member (pairwise distinctness)."""
    assert len(set(values)) == len(values), f"{label} are not pairwise distinct: {values}"


def find_by_id(rows: Sequence[Dict[str, Any]], row_id: str) -> Dict[str, Any]:
    """Locate one row of a list response by its identifier."""
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"id {row_id} not present in list of {len(rows)} rows")


def ids_of(rows: Sequence[Dict[str, Any]]) -> list:
    """The identifiers of a list response, in the order returned."""
    return [row.get("id") for row in rows]
