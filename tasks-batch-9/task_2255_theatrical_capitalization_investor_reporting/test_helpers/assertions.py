"""
Domain-shaped assertion helpers.

These only cover structural facts the PRD states about every response: the
envelope, the common-field set (and the one entity that carries a shorter one),
the four-decimal percentage convention, and the rule that a rejected request
"increments nothing and refreshes no `updated_at`". Value-level arithmetic is
asserted inline in the tests so each expected number stays next to the sentence
that derives it.
"""

from typing import Any, Dict, Mapping, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# Fields every entity but the booking record carries.
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

# The booking record's shorter set.
ENGAGEMENT_FIELDS = ("id", "created_at")


def assert_envelope(body: Mapping[str, Any], expected_response_type: str) -> None:
    """Assert the shared envelope: response_type plus the two meta identifiers."""
    assert body.get("response_type") == expected_response_type, (
        f"expected response_type {expected_response_type!r}, "
        f"got {body.get('response_type')!r}"
    )
    meta = body.get("meta")
    assert isinstance(meta, dict), f"expected a meta object, got {meta!r}"
    assert meta.get("api_request_id"), "meta.api_request_id must be present"
    # "The `api_request_id` is a server-generated unique identifier for the
    # request that starts with `req_`."
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"].startswith(
        "req_"
    ), f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    assert is_iso8601_timestamp(
        meta.get("api_request_timestamp", "")
    ), f"meta.api_request_timestamp must be ISO 8601, got {meta.get('api_request_timestamp')!r}"


def assert_common_fields(row: Mapping[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert the full common-field set on a versioned row."""
    for field in COMMON_FIELDS:
        assert field in row, f"expected common field {field!r} on the row, got {sorted(row)}"
    assert is_valid_uuid(row["id"]), f"id must be a UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(
        row["created_at"]
    ), f"created_at must be ISO 8601, got {row['created_at']!r}"
    assert is_iso8601_timestamp(
        row["updated_at"]
    ), f"updated_at must be ISO 8601, got {row['updated_at']!r}"
    assert isinstance(row["version"], int), f"version must be an integer, got {row['version']!r}"
    assert row["version"] >= 1, f"version starts at 1, got {row['version']!r}"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_engagement_common_fields(row: Mapping[str, Any]) -> None:
    """Assert the booking record carries only `id` and `created_at`."""
    for field in ENGAGEMENT_FIELDS:
        assert field in row, f"expected {field!r} on the booking record, got {sorted(row)}"
    assert is_valid_uuid(row["id"]), f"id must be a UUID, got {row['id']!r}"
    assert is_iso8601_timestamp(
        row["created_at"]
    ), f"created_at must be ISO 8601, got {row['created_at']!r}"
    assert "updated_at" not in row, "the booking record must not carry updated_at"
    assert "version" not in row, "the booking record must not carry version"


def assert_pct_precision(value: Any, label: str = "percentage") -> None:
    """Assert a published ratio is a number carried to at most four decimals."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    scaled = round(float(value) * 10_000)
    assert abs(float(value) * 10_000 - scaled) < 1e-6, (
        f"{label} must be carried to four decimal places, got {value!r}"
    )


def assert_no_write(before: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    """Assert a refused request left the version and the updated_at stamp alone."""
    assert after["version"] == before["version"], (
        f"a rejected request must not increment version: "
        f"{before['version']} -> {after['version']}"
    )
    assert after["updated_at"] == before["updated_at"], (
        f"a rejected request must not refresh updated_at: "
        f"{before['updated_at']} -> {after['updated_at']}"
    )


def find_breakdown_entry(
    breakdown: Sequence[Dict[str, Any]], investor_account_id: str
) -> Dict[str, Any]:
    """Pull the frozen allocation row for one capital account out of a distribution."""
    for entry in breakdown:
        if entry.get("investor_account_id") == investor_account_id:
            return entry
    raise AssertionError(
        f"no allocation_breakdown entry for account {investor_account_id!r} "
        f"in {breakdown!r}"
    )


def sum_breakdown(breakdown: Sequence[Dict[str, Any]]) -> int:
    """Total the frozen per-account amounts of a distribution."""
    return sum(int(entry["amount_cents"]) for entry in breakdown)


def round_half_up(numerator: int, multiplier: float) -> int:
    """Round a product to whole cents the way the documented convention does.

    "Wherever a monetary amount is derived by multiplying by a percentage or
    dividing by a count, the result is rounded to a whole number of cents using
    **round half up**: a value exactly halfway between two whole cents rounds
    away from zero to the larger magnitude."
    """
    from decimal import Decimal, ROUND_HALF_UP

    product = Decimal(str(numerator)) * Decimal(str(multiplier))
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
