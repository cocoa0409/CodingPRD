"""Domain assertion helpers.

Every weight, index and percentage figure this API publishes is rounded
half-up to two decimals, so numeric comparisons go through
``pytest.approx(expected, abs=0.01)`` rather than exact equality.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import pytest

from .constants import MONEY_TOLERANCE

# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def assert_kg(actual: Any, expected: float, label: str) -> None:
    """Assert a weight in kilograms, to the published two-decimal precision."""
    assert actual is not None, f"{label} is missing from the response"
    assert float(actual) == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label} should be {expected:.2f} kg but was {actual}"
    )


def assert_index(actual: Any, expected: float, label: str) -> None:
    """Assert an index-unit figure to two decimals."""
    assert actual is not None, f"{label} is missing from the response"
    assert float(actual) == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label} should be {expected:.2f} index units but was {actual}"
    )


def assert_pct_mac(actual: Any, expected: float, label: str) -> None:
    """Assert a centre-of-gravity position expressed as a percentage of MAC."""
    assert actual is not None, f"{label} is missing from the response"
    assert float(actual) == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label} should be {expected:.2f} %MAC but was {actual}"
    )


def assert_two_decimals(value: Any, label: str) -> None:
    """Assert a published figure carries no more than two decimal places."""
    assert value is not None, f"{label} is missing from the response"
    scaled = round(float(value) * 100)
    assert abs(float(value) * 100 - scaled) < 1e-6, (
        f"{label} should be rounded to 2 decimals but was {value}"
    )


def assert_multiple_of_ten(value: Any, label: str) -> None:
    """Assert a figure sits on a whole 10-kilogram step."""
    assert value is not None, f"{label} is missing from the response"
    assert float(value) % 10 == pytest.approx(0.0, abs=1e-6), (
        f"{label} should be a whole multiple of 10 kg but was {value}"
    )


# ---------------------------------------------------------------------------
# System fields
# ---------------------------------------------------------------------------


def assert_system_fields(entity: Mapping[str, Any], label: str = "entity") -> None:
    """Assert the four server-managed fields are present and well formed."""
    from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

    assert "id" in entity, f"{label} should carry a server-minted id"
    assert is_valid_uuid(str(entity["id"])), f"{label} id should be a UUID, got {entity['id']!r}"
    for field in ("created_at", "updated_at"):
        assert field in entity, f"{label} should carry {field}"
        assert is_iso8601_timestamp(str(entity[field])), (
            f"{label} {field} should be an ISO 8601 timestamp, got {entity[field]!r}"
        )
    assert "version" in entity, f"{label} should carry a version counter"
    assert isinstance(entity["version"], int), f"{label} version should be an integer"


def assert_freshly_created(entity: Mapping[str, Any], label: str = "entity") -> None:
    """A brand new record starts at version 1 with matching timestamps."""
    assert_system_fields(entity, label)
    assert entity["version"] == 1, f"a newly created {label} should start at version 1"
    assert entity["created_at"] == entity["updated_at"], (
        f"a newly created {label} should have created_at equal to updated_at"
    )


def assert_version_is(entity: Mapping[str, Any], expected: int, label: str = "entity") -> None:
    assert entity.get("version") == expected, (
        f"{label} version should be {expected} but was {entity.get('version')}"
    )


def assert_unchanged(before: Mapping[str, Any], after: Mapping[str, Any], label: str = "entity") -> None:
    """Assert a read left the record untouched."""
    assert after.get("version") == before.get("version"), (
        f"{label} version should not move on a read"
    )
    assert after.get("updated_at") == before.get("updated_at"), (
        f"{label} updated_at should not move on a read"
    )


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def assert_object_envelope(body: Mapping[str, Any]) -> None:
    assert body.get("response_type") == "object", (
        f"a single-resource response should declare response_type 'object', got {body.get('response_type')!r}"
    )
    _assert_meta(body)


def assert_array_envelope(body: Mapping[str, Any]) -> None:
    assert body.get("response_type") == "array", (
        f"a collection response should declare response_type 'array', got {body.get('response_type')!r}"
    )
    _assert_meta(body)


def assert_error_envelope(body: Mapping[str, Any], expected_error_id: Optional[str] = None) -> None:
    assert body.get("response_type") == "error", (
        f"a failure response should declare response_type 'error', got {body.get('response_type')!r}"
    )
    data = body.get("data") or {}
    assert set(data.keys()) == {"error_id", "message"}, (
        f"an error payload should carry exactly error_id and message, got {sorted(data.keys())}"
    )
    assert isinstance(data.get("message"), str) and data["message"].strip(), (
        "an error payload should carry a non-empty human-readable message"
    )
    if expected_error_id is not None:
        assert data.get("error_id") == str(expected_error_id), (
            f"expected error_id {expected_error_id} but got {data.get('error_id')}"
        )
    meta = body.get("meta") or {}
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"an error envelope's meta should carry only the two request fields, got {sorted(meta.keys())}"
    )
    _assert_meta(body)


def _assert_meta(body: Mapping[str, Any]) -> None:
    meta = body.get("meta") or {}
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"meta.api_request_id should be a string beginning with 'req_', got {request_id!r}"
    )
    assert meta.get("api_request_timestamp"), "meta.api_request_timestamp should be present"


def assert_pagination_meta(
    meta: Mapping[str, Any],
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    for field in ("limit", "offset", "total_count", "has_more"):
        assert field in meta, f"a collection envelope's meta should carry {field}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count should be {total_count} but was {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"has_more should be {has_more} but was {meta['has_more']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"limit should be {limit} but was {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset should be {offset} but was {meta['offset']}"


def assert_ascending_by_created_at(rows: Sequence[Mapping[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"collections should be ordered by created_at ascending, got {stamps}"


# ---------------------------------------------------------------------------
# Flight helpers
# ---------------------------------------------------------------------------


def assert_flight_state(
    flight: Mapping[str, Any],
    status: Optional[str] = None,
    load_release_state: Optional[str] = None,
    dg_hold_count: Optional[int] = None,
) -> None:
    if status is not None:
        assert flight.get("status") == status, (
            f"flight status should be {status} but was {flight.get('status')}"
        )
    if load_release_state is not None:
        assert flight.get("load_release_state") == load_release_state, (
            f"flight load_release_state should be {load_release_state} "
            f"but was {flight.get('load_release_state')}"
        )
    if dg_hold_count is not None:
        assert flight.get("dg_hold_count") == dg_hold_count, (
            f"flight dg_hold_count should be {dg_hold_count} but was {flight.get('dg_hold_count')}"
        )


def assert_flight_capacity(
    flight: Mapping[str, Any],
    dry_operating_weight_kg: Optional[float] = None,
    dry_operating_index: Optional[float] = None,
    performance_limited_takeoff_weight_kg: Optional[float] = None,
    allowed_payload_kg: Optional[float] = None,
    limiting_factor: Optional[str] = None,
) -> None:
    """Assert the four derived capacity figures and the binding limit."""
    if dry_operating_weight_kg is not None:
        assert_kg(flight.get("dry_operating_weight_kg"), dry_operating_weight_kg, "dry_operating_weight_kg")
    if dry_operating_index is not None:
        assert_index(flight.get("dry_operating_index"), dry_operating_index, "dry_operating_index")
    if performance_limited_takeoff_weight_kg is not None:
        assert_kg(
            flight.get("performance_limited_takeoff_weight_kg"),
            performance_limited_takeoff_weight_kg,
            "performance_limited_takeoff_weight_kg",
        )
    if allowed_payload_kg is not None:
        assert_kg(flight.get("allowed_payload_kg"), allowed_payload_kg, "allowed_payload_kg")
    if limiting_factor is not None:
        assert flight.get("limiting_factor") == limiting_factor, (
            f"limiting_factor should be {limiting_factor} but was {flight.get('limiting_factor')}"
        )


# ---------------------------------------------------------------------------
# Load plan helpers
# ---------------------------------------------------------------------------

_PLAN_KG_FIELDS = (
    "base_payload_kg",
    "frozen_underload_kg",
    "planned_payload_kg",
    "deferred_bag_weight_kg",
    "zero_fuel_weight_kg",
    "takeoff_weight_kg",
    "taxi_weight_kg",
    "landing_weight_kg",
    "underload_kg",
)
_PLAN_INDEX_FIELDS = ("index_zfw", "index_tow")
_PLAN_PCT_FIELDS = ("mac_zfw_pct", "mac_tow_pct")


def assert_plan_figures(plan: Mapping[str, Any], **expected: Any) -> None:
    """Assert any subset of a plan's published figures and flags.

    Weight fields are compared in kilograms, index fields in index units and
    ``mac_*_pct`` fields as percentages of MAC; ``status``,
    ``restriction_status`` and ``envelope_ok`` are compared exactly.
    """
    for field, value in expected.items():
        if field in _PLAN_KG_FIELDS:
            assert_kg(plan.get(field), value, field)
        elif field in _PLAN_INDEX_FIELDS:
            assert_index(plan.get(field), value, field)
        elif field in _PLAN_PCT_FIELDS:
            assert_pct_mac(plan.get(field), value, field)
        else:
            assert plan.get(field) == value, (
                f"plan {field} should be {value!r} but was {plan.get(field)!r}"
            )


def assert_plan_is_reset_to_draft(plan: Mapping[str, Any]) -> None:
    """A plan knocked back to DRAFT publishes zeroed derived figures."""
    assert plan.get("status") == "DRAFT", (
        f"an invalidated plan should return to DRAFT but was {plan.get('status')}"
    )
    for field in (
        "base_payload_kg",
        "planned_payload_kg",
        "zero_fuel_weight_kg",
        "index_zfw",
        "mac_zfw_pct",
        "takeoff_weight_kg",
        "index_tow",
        "mac_tow_pct",
        "underload_kg",
    ):
        assert_kg(plan.get(field), 0.0, field)
    assert plan.get("envelope_ok") is False, "a DRAFT plan should not claim an in-envelope result"


def assert_offload_preview(
    preview: Mapping[str, Any],
    strategy: Optional[str] = None,
    excess_weight_kg: Optional[float] = None,
    offloaded_total_kg: Optional[float] = None,
    offloaded_piece_count: Optional[int] = None,
    offloaded_awb_numbers: Optional[List[str]] = None,
) -> None:
    if strategy is not None:
        assert preview.get("strategy") == strategy, (
            f"preview strategy should be {strategy} but was {preview.get('strategy')}"
        )
    if excess_weight_kg is not None:
        assert_kg(preview.get("excess_weight_kg"), excess_weight_kg, "excess_weight_kg")
    if offloaded_total_kg is not None:
        assert_kg(preview.get("offloaded_total_kg"), offloaded_total_kg, "offloaded_total_kg")
    if offloaded_piece_count is not None:
        assert preview.get("offloaded_piece_count") == offloaded_piece_count, (
            f"offloaded_piece_count should be {offloaded_piece_count} "
            f"but was {preview.get('offloaded_piece_count')}"
        )
    if offloaded_awb_numbers is not None:
        assert list(preview.get("offloaded_awb_numbers") or []) == offloaded_awb_numbers, (
            f"offloaded_awb_numbers should be {offloaded_awb_numbers} "
            f"but was {preview.get('offloaded_awb_numbers')}"
        )


# ---------------------------------------------------------------------------
# Load sheet helpers
# ---------------------------------------------------------------------------

_SHEET_KG_FIELDS = (
    "issued_takeoff_weight_kg",
    "issued_payload_kg",
    "lmc_allowance_kg",
    "lmc_net_weight_delta_kg",
    "lmc_absolute_weight_delta_kg",
    "final_takeoff_weight_kg",
    "final_payload_kg",
)
_SHEET_INDEX_FIELDS = ("issued_index_tow", "final_index_tow")
_SHEET_PCT_FIELDS = ("final_mac_tow_pct",)


def assert_sheet_figures(sheet: Mapping[str, Any], **expected: Any) -> None:
    """Assert any subset of a load sheet's snapshot, allowance and final figures."""
    for field, value in expected.items():
        if field in _SHEET_KG_FIELDS:
            assert_kg(sheet.get(field), value, field)
        elif field in _SHEET_INDEX_FIELDS:
            assert_index(sheet.get(field), value, field)
        elif field in _SHEET_PCT_FIELDS:
            assert_pct_mac(sheet.get(field), value, field)
        else:
            assert sheet.get(field) == value, (
                f"sheet {field} should be {value!r} but was {sheet.get(field)!r}"
            )


def assert_final_equals_issued(sheet: Mapping[str, Any]) -> None:
    """A sheet with no applied change reads final figures identical to issued."""
    assert_kg(sheet.get("final_takeoff_weight_kg"), float(sheet["issued_takeoff_weight_kg"]),
              "final_takeoff_weight_kg")
    assert_index(sheet.get("final_index_tow"), float(sheet["issued_index_tow"]), "final_index_tow")
    assert_kg(sheet.get("final_payload_kg"), float(sheet["issued_payload_kg"]), "final_payload_kg")


# ---------------------------------------------------------------------------
# Cargo and dangerous goods helpers
# ---------------------------------------------------------------------------


def assert_cargo_state(
    cargo: Mapping[str, Any],
    status: Optional[str] = None,
    assigned_compartment_id: Optional[Any] = ...,
    item_kind: Optional[str] = None,
    offload_priority_rank: Optional[int] = None,
) -> None:
    if status is not None:
        assert cargo.get("status") == status, (
            f"consignment {cargo.get('awb_number')} status should be {status} "
            f"but was {cargo.get('status')}"
        )
    if assigned_compartment_id is not ...:
        assert cargo.get("assigned_compartment_id") == assigned_compartment_id, (
            f"consignment {cargo.get('awb_number')} assigned_compartment_id should be "
            f"{assigned_compartment_id!r} but was {cargo.get('assigned_compartment_id')!r}"
        )
    if item_kind is not None:
        assert cargo.get("item_kind") == item_kind, (
            f"consignment item_kind should be {item_kind} but was {cargo.get('item_kind')}"
        )
    if offload_priority_rank is not None:
        assert cargo.get("offload_priority_rank") == offload_priority_rank, (
            f"consignment offload_priority_rank should be {offload_priority_rank} "
            f"but was {cargo.get('offload_priority_rank')}"
        )


def assert_declaration_state(
    declaration: Mapping[str, Any],
    status: Optional[str] = None,
    accepted_by_user_id: Optional[Any] = ...,
    notoc_issued: Optional[bool] = None,
) -> None:
    if status is not None:
        assert declaration.get("status") == status, (
            f"declaration status should be {status} but was {declaration.get('status')}"
        )
    if accepted_by_user_id is not ...:
        assert declaration.get("accepted_by_user_id") == accepted_by_user_id, (
            f"declaration accepted_by_user_id should be {accepted_by_user_id!r} "
            f"but was {declaration.get('accepted_by_user_id')!r}"
        )
    if notoc_issued is not None:
        assert declaration.get("notoc_issued") is notoc_issued, (
            f"declaration notoc_issued should be {notoc_issued} "
            f"but was {declaration.get('notoc_issued')}"
        )


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------


def assert_audit_figures(audit: Mapping[str, Any], **expected: Any) -> None:
    """Assert any subset of an audit's deltas, severity band and status."""
    kg_fields = (
        "pax_delta_kg",
        "bag_delta_kg",
        "cargo_delta_kg",
        "total_absolute_discrepancy_kg",
        "actual_pax_weight_kg",
        "actual_bag_weight_kg",
        "actual_cargo_weight_kg",
    )
    for field, value in expected.items():
        if field in kg_fields:
            assert_kg(audit.get(field), value, field)
        else:
            assert audit.get(field) == value, (
                f"audit {field} should be {value!r} but was {audit.get(field)!r}"
            )


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------


def ids_of(rows: Iterable[Mapping[str, Any]]) -> List[str]:
    return [str(row["id"]) for row in rows]


def by_id(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    return {str(row["id"]): row for row in rows}


def assert_contains_ids(rows: Iterable[Mapping[str, Any]], expected_ids: Sequence[str]) -> None:
    found = set(ids_of(rows))
    for expected in expected_ids:
        assert expected in found, f"expected id {expected} in the collection, got {sorted(found)}"


def assert_excludes_ids(rows: Iterable[Mapping[str, Any]], excluded_ids: Sequence[str]) -> None:
    found = set(ids_of(rows))
    for excluded in excluded_ids:
        assert excluded not in found, f"id {excluded} should not appear in the collection"
