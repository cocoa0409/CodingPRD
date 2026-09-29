"""Domain assertion helpers.

These wrap the repetitive shape checks that PRD §2.3 (envelope), §2.4 (common
fields), §2.6 (rounding and precision) and §2.13 (provenance) impose, so that
each test body reads as the rule it is proving rather than as plumbing.
"""

from typing import Any, Dict, List, Optional, Sequence

import pytest
import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

# Money, scores, tonnages and priority values are two-decimal quantities.
MONEY_TOLERANCE = 0.01
# Exposure factors, credit ratios and denial rates are four-decimal quantities.
RATIO_TOLERANCE = 0.0001


# ---------------------------------------------------------------------------
# Numeric comparisons
# ---------------------------------------------------------------------------


def assert_amount(actual: Any, expected: float, field: str) -> None:
    """Compare a two-decimal quantity (score, money, tonnage, priority)."""
    assert actual is not None, f"{field} is missing from the payload"
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{field} should be {expected:.2f} but was {actual}"
    )


def assert_ratio(actual: Any, expected: float, field: str) -> None:
    """Compare a four-decimal quantity (exposure factor, ratio, denial rate)."""
    assert actual is not None, f"{field} is missing from the payload"
    assert actual == pytest.approx(expected, abs=RATIO_TOLERANCE), (
        f"{field} should be {expected:.4f} but was {actual}"
    )


def assert_field(data: Dict[str, Any], field: str, expected: Any) -> None:
    """Compare a discrete field (status, enum, count, flag) by equality."""
    assert field in data, f"{field} is missing from the payload"
    assert data[field] == expected, (
        f"{field} should be {expected!r} but was {data[field]!r}"
    )


def assert_fields(data: Dict[str, Any], expected: Dict[str, Any]) -> None:
    """Compare several discrete fields at once."""
    for field, value in expected.items():
        assert_field(data, field, value)


def assert_amounts(data: Dict[str, Any], expected: Dict[str, float]) -> None:
    """Compare several two-decimal quantities at once."""
    for field, value in expected.items():
        assert_amount(data.get(field), value, field)


# ---------------------------------------------------------------------------
# Envelope and common fields
# ---------------------------------------------------------------------------


def assert_object_envelope(response: requests.Response) -> None:
    """A single-resource response declares `response_type` `object` and meta ids."""
    body = response.json()
    assert body.get("response_type") == "object", (
        f"response_type should be 'object' but was {body.get('response_type')!r}"
    )
    meta = body.get("meta") or {}
    assert meta.get("api_request_id"), "meta.api_request_id must be present"
    assert meta.get("api_request_timestamp"), (
        "meta.api_request_timestamp must be present"
    )


def assert_array_envelope(response: requests.Response) -> None:
    """A collection response declares `response_type` `array`."""
    body = response.json()
    assert body.get("response_type") == "array", (
        f"response_type should be 'array' but was {body.get('response_type')!r}"
    )


def assert_error_envelope(response: requests.Response) -> None:
    """An error response declares `response_type` `error`."""
    body = response.json()
    assert body.get("response_type") == "error", (
        f"response_type should be 'error' but was {body.get('response_type')!r}"
    )


def assert_common_fields(data: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A full common-field resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id")), f"id should be a UUID but was {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at")), (
        f"created_at should be an ISO-8601 timestamp but was {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at")), (
        f"updated_at should be an ISO-8601 timestamp but was {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version should be an integer but was {data.get('version')!r}"
    )
    if expected_version is not None:
        assert_field(data, "version", expected_version)


def assert_no_version_field(data: Dict[str, Any], resource: str) -> None:
    """Write-once resources expose no `version` key at all."""
    assert "version" not in data, (
        f"{resource} must not expose a version field, but the payload carried "
        f"version={data.get('version')!r}"
    )


def assert_no_updated_at_field(data: Dict[str, Any], resource: str) -> None:
    """Write-once resources expose no `updated_at` key at all."""
    assert "updated_at" not in data, (
        f"{resource} must not expose an updated_at field, but the payload carried "
        f"updated_at={data.get('updated_at')!r}"
    )


def assert_write_once_shape(data: Dict[str, Any], resource: str) -> None:
    """Neither `updated_at` nor `version` appears on a write-once resource."""
    assert_no_updated_at_field(data, resource)
    assert_no_version_field(data, resource)


# ---------------------------------------------------------------------------
# Listings and pagination
# ---------------------------------------------------------------------------


def assert_page(
    response: requests.Response,
    expected_rows: int,
    expected_total: int,
    expected_has_more: bool,
) -> List[Dict[str, Any]]:
    """Validate one page of a listing and return its rows."""
    rows, meta = validate_paginated(response)
    assert len(rows) == expected_rows, (
        f"page should carry {expected_rows} rows but carried {len(rows)}"
    )
    assert meta["total_count"] == expected_total, (
        f"meta.total_count should be {expected_total} but was {meta['total_count']}"
    )
    assert meta["has_more"] is expected_has_more, (
        f"meta.has_more should be {expected_has_more} but was {meta['has_more']}"
    )
    return rows


def assert_empty_listing(response: requests.Response) -> None:
    """A listing that must be empty: no rows and a zero total."""
    assert_page(response, expected_rows=0, expected_total=0, expected_has_more=False)


def assert_ids_in_order(rows: Sequence[Dict[str, Any]], expected_ids: Sequence[str]) -> None:
    """The listing's rows appear in exactly the expected id order."""
    actual = [row["id"] for row in rows]
    assert actual == list(expected_ids), (
        f"listing order should be {list(expected_ids)} but was {actual}"
    )


# ---------------------------------------------------------------------------
# Screening-area shorthands
# ---------------------------------------------------------------------------


def assert_area_scores(
    area: Dict[str, Any], statewide: float, county: float
) -> None:
    """Both score variants of an area at once."""
    assert_amount(area.get("ej_screen_score_statewide"), statewide, "ej_screen_score_statewide")
    assert_amount(area.get("ej_screen_score_county"), county, "ej_screen_score_county")


def assert_area_components(
    area: Dict[str, Any], pollution: float, health: float, demographic: float
) -> None:
    """The three statewide category means stored alongside the statewide score."""
    assert_amount(
        area.get("pollution_component_statewide"), pollution, "pollution_component_statewide"
    )
    assert_amount(
        area.get("health_component_statewide"), health, "health_component_statewide"
    )
    assert_amount(
        area.get("demographic_component_statewide"),
        demographic,
        "demographic_component_statewide",
    )


def assert_ledgers(
    area: Optional[Dict[str, Any]] = None,
    facility: Optional[Dict[str, Any]] = None,
    permitted_load_tpy: Optional[float] = None,
    existing_load_tpy: Optional[float] = None,
) -> None:
    """Check the area and facility emissions ledgers."""
    if area is not None and permitted_load_tpy is not None:
        assert_amount(area.get("permitted_load_tpy"), permitted_load_tpy, "permitted_load_tpy")
    if facility is not None and existing_load_tpy is not None:
        assert_amount(facility.get("existing_load_tpy"), existing_load_tpy, "existing_load_tpy")


# ---------------------------------------------------------------------------
# Error shorthands
# ---------------------------------------------------------------------------


def assert_rejected(response: requests.Response, error_id: str) -> Dict[str, Any]:
    """The call was refused with exactly `error_id`, in the error envelope."""
    assert_error_envelope(response)
    return validate_error(response, error_id)


def assert_created(response: requests.Response) -> Dict[str, Any]:
    """A creating call returns 201 with the object envelope."""
    data = validate_success(response, 201)
    assert_object_envelope(response)
    return data


def assert_ok(response: requests.Response) -> Dict[str, Any]:
    """A read or transition returns 200 with the object envelope."""
    data = validate_success(response, 200)
    assert_object_envelope(response)
    return data


def assert_no_content(response: requests.Response) -> None:
    """The single condition-voiding operation returns 204 with no body."""
    assert response.status_code == 204, (
        f"expected 204 No Content but got {response.status_code}: {response.text}"
    )
    assert response.text == "" or response.text is None, (
        f"204 response must carry no body but carried {response.text!r}"
    )
