"""Domain assertions shared by the test suite."""

import re
from typing import Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    API_REQUEST_ID_PREFIX,
    ERECTION_STAGE_SEQUENCE,
)

_THREE_FRACTIONAL_DIGITS = re.compile(r"\.\d{3}(Z|[+-]\d{2}:\d{2})$")


def assert_timestamp_has_three_fractional_digits(value: str) -> None:
    """Every timestamp is ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 timestamp: {value!r}"
    assert _THREE_FRACTIONAL_DIGITS.search(value), (
        f"timestamp {value!r} does not carry exactly three fractional digits"
    )


def assert_bare_uuid(value: str) -> None:
    """An ``id`` is a UUID string with no type prefix."""
    assert is_valid_uuid(value), f"not a UUID: {value!r}"
    assert len(value) == 36, f"id {value!r} is not a bare 36-character UUID"


def assert_common_fields(data: dict) -> None:
    """``id``, ``created_at``, ``updated_at`` and a ``version`` starting at 1."""
    assert_bare_uuid(data["id"])
    assert_timestamp_has_three_fractional_digits(data["created_at"])
    assert_timestamp_has_three_fractional_digits(data["updated_at"])
    assert isinstance(data["version"], int)
    assert data["version"] >= 1


def assert_append_only_fields(data: dict) -> None:
    """A design component carries only ``id`` and ``created_at``."""
    assert_bare_uuid(data["id"])
    assert_timestamp_has_three_fractional_digits(data["created_at"])
    assert "updated_at" not in data, "an immutable component must have no updated_at"
    assert "version" not in data, "an immutable component must have no version"


def assert_meta_envelope(body: dict) -> None:
    meta = body["meta"]
    assert meta["api_request_id"].startswith(API_REQUEST_ID_PREFIX)
    assert_timestamp_has_three_fractional_digits(meta["api_request_timestamp"])


def assert_error_envelope(body: dict, expected_error_id: str) -> None:
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == expected_error_id
    assert body["data"]["message"]
    assert_meta_envelope(body)


def assert_pagination_meta(
    meta: dict,
    limit: int,
    offset: int,
    total_count: int,
    has_more: bool,
) -> None:
    assert meta["limit"] == limit
    assert meta["offset"] == offset
    assert meta["total_count"] == total_count
    assert meta["has_more"] is has_more


def assert_weight(actual, expected: float) -> None:
    """Weights in pounds are retained to two decimal places."""
    assert actual == pytest.approx(expected, abs=0.01)


def assert_rate(actual, expected: float) -> None:
    """Discount rates are expressed to two decimal places."""
    assert actual == pytest.approx(expected, abs=0.001)


# ------------------------------------------------------------------- ledgers --
def assert_credit_ledger_conserved(builder: dict) -> None:
    """Used plus available equals the limit at all times."""
    assert (
        builder["credit_used_cents"] + builder["credit_available_cents"]
        == builder["credit_limit_cents"]
    )


def assert_pounds_ledger_conserved(order: dict) -> None:
    """Assigned plus unassigned equals the total at all times."""
    assert order["assigned_weight_lbs"] + order["unassigned_weight_lbs"] == (
        pytest.approx(order["total_shippable_weight_lbs"], abs=0.01)
    )


# ------------------------------------------------------------ per-entity shape --
def assert_jurisdiction(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["code"], str)
    assert isinstance(data["criteria_revision"], int)
    assert data["criteria_revision"] >= 1
    assert isinstance(data["authorized_builder_count"], int)
    assert data["max_authorized_builders"] >= 1


def assert_builder(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("PENDING_AUTHORIZATION", "AUTHORIZED", "SUSPENDED")
    assert_credit_ledger_conserved(data)


def assert_configuration(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "LOCKED", "CRITERIA_STALE")


def assert_draft_configuration_is_uncomputed(data: dict) -> None:
    """While DRAFT every geometry, load and weight field stays null."""
    assert data["status"] == "DRAFT"
    for field in (
        "building_length_ft",
        "footprint_sqft",
        "roof_slope_factor",
        "panel_area_sqft",
        "design_wind_pressure_psf",
        "dead_load_psf",
        "roof_snow_load_psf",
        "estimated_frame_weight_lbs",
        "criteria_revision_at_lock",
        "locked_at",
    ):
        assert data[field] is None, f"{field} must be null while the configuration is DRAFT"


def assert_accessory_kit(data: dict) -> None:
    assert_common_fields(data)
    assert data["extended_price_cents"] == data["unit_price_cents"] * data["quantity"]


def assert_quote(data: dict) -> None:
    assert_common_fields(data)
    assert data["quote_variant"] == "PRELIMINARY"
    assert data["status"] in ("DRAFT", "ISSUED", "ACCEPTED")


def assert_design(data: dict) -> None:
    assert_common_fields(data)
    assert data["design_variant"] in ("ASD", "LRFD")
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "REVISION_REQUIRED",
        "SUPERSEDED",
        "VOIDED",
    )


def assert_design_component(data: dict) -> None:
    assert_append_only_fields(data)
    assert data["erection_stage"] in ERECTION_STAGE_SEQUENCE


def assert_drawing_package(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "SEALED", "VOIDED")


def assert_order(data: dict) -> None:
    assert_common_fields(data)
    assert data["engineering_status"] in (
        "ENG_PENDING",
        "ENG_APPROVED",
        "ENG_SEALED",
        "ENG_REWORK",
    )
    assert data["production_status"] in (
        "PROD_NOT_RELEASED",
        "PROD_RELEASED",
        "PROD_IN_FABRICATION",
        "PROD_COMPLETE",
        "PROD_HOLD",
    )
    assert isinstance(data["permit_hold"], bool)
    assert isinstance(data["commercial_hold"], bool)
    assert_pounds_ledger_conserved(data)


def assert_production_line(data: dict) -> None:
    assert_common_fields(data)
    assert data["line_type"] in ("PLATE_CUT_WELD", "ROLL_FORM", "PANEL_ROLL")
    assert data["changeover_buffer_minutes"] >= 0


def assert_production_lot(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "COMPLETE", "CANCELLED")


def assert_shipment_load(data: dict) -> None:
    assert_common_fields(data)
    assert data["status"] in ("PLANNED", "DISPATCHED", "CANCELLED")
    assert data["stage_sequence"] == ERECTION_STAGE_SEQUENCE[data["erection_stage"]]


def assert_erection_sequence(
    data: dict,
    order_id: str,
    sequence: str,
    next_dispatchable_stage: str,
    planned_load_count: int,
    dispatched_load_count: int,
    blocked_load_count: int,
) -> None:
    assert data["order_id"] == order_id
    assert data["sequence"] == sequence
    assert data["next_dispatchable_stage"] == next_dispatchable_stage
    assert data["planned_load_count"] == planned_load_count
    assert data["dispatched_load_count"] == dispatched_load_count
    assert data["blocked_load_count"] == blocked_load_count


def assert_order_dimensions(
    order: dict,
    engineering_status: str,
    production_status: str,
    permit_hold: Optional[bool] = None,
    commercial_hold: Optional[bool] = None,
) -> None:
    assert order["engineering_status"] == engineering_status
    assert order["production_status"] == production_status
    if permit_hold is not None:
        assert order["permit_hold"] is permit_hold
    if commercial_hold is not None:
        assert order["commercial_hold"] is commercial_hold
