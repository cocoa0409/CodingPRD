"""Domain assertions for the Vehicle Distribution & Port Processing API.

These helpers only ever compare a response against values the caller supplies.
None of them recomputes a business figure, so a test that asserts a cent total
must state that total literally.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import MODEL_LINES


# --------------------------------------------------------------------------
# identity, timestamps, versioning
# --------------------------------------------------------------------------
def assert_record_identity(record: Mapping[str, Any]) -> None:
    """Every resource carries a server-minted UUID ``id`` and a ``created_at``."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert not str(record["id"]).startswith("vpc"), "id must carry no type prefix"
    assert_timestamp_format(record["created_at"])


def assert_versioned_record(record: Mapping[str, Any], *, expected_version: Optional[int] = None) -> None:
    """A resource that carries ``updated_at`` and a ``version`` integer."""
    assert_record_identity(record)
    assert_timestamp_format(record["updated_at"])
    assert isinstance(record["version"], int), "version must be an integer"
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_fields_absent(record: Mapping[str, Any], field_names: Iterable[str]) -> None:
    for name in field_names:
        assert name not in record, f"field {name!r} must not be present: {record.get(name)!r}"


def assert_timestamps_equal(first: str, second: str) -> None:
    assert first == second, f"timestamps differ: {first!r} != {second!r}"


def assert_iso_instant(value: Any) -> None:
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"not an ISO 8601 UTC instant with three fractional digits: {value!r}"
    )


# --------------------------------------------------------------------------
# vehicle: the two independent state dimensions
# --------------------------------------------------------------------------
def assert_vehicle_dimensions(
    vehicle: Mapping[str, Any],
    *,
    processing_status: Optional[str] = None,
    damage_status: Optional[str] = None,
    yard_presence: Optional[str] = None,
) -> None:
    if processing_status is not None:
        assert vehicle["processing_status"] == processing_status, (
            f"processing_status expected {processing_status}, got {vehicle['processing_status']}"
        )
    if damage_status is not None:
        assert vehicle["damage_status"] == damage_status, (
            f"damage_status expected {damage_status}, got {vehicle['damage_status']}"
        )
    if yard_presence is not None:
        assert vehicle["yard_presence"] == yard_presence, (
            f"yard_presence expected {yard_presence}, got {vehicle['yard_presence']}"
        )


def assert_stop_ship(
    vehicle: Mapping[str, Any],
    *,
    blocked: bool,
    blocking_hold_order_id: Any = "__unchecked__",
) -> None:
    assert vehicle["stop_ship_blocked"] is blocked, (
        f"stop_ship_blocked expected {blocked}, got {vehicle['stop_ship_blocked']}"
    )
    if blocking_hold_order_id != "__unchecked__":
        assert vehicle["blocking_hold_order_id"] == blocking_hold_order_id, (
            "blocking_hold_order_id expected "
            f"{blocking_hold_order_id!r}, got {vehicle['blocking_hold_order_id']!r}"
        )


def assert_storage_charges(
    vehicle: Mapping[str, Any],
    *,
    provisional_cents: Optional[int] = None,
    final_cents: Optional[int] = None,
    blocked_credit_days: Optional[int] = None,
) -> None:
    if provisional_cents is not None:
        assert vehicle["storage_charge_provisional_cents"] == provisional_cents, (
            "storage_charge_provisional_cents expected "
            f"{provisional_cents}, got {vehicle['storage_charge_provisional_cents']}"
        )
    if final_cents is not None:
        assert vehicle["storage_charge_final_cents"] == final_cents, (
            "storage_charge_final_cents expected "
            f"{final_cents}, got {vehicle['storage_charge_final_cents']}"
        )
    if blocked_credit_days is not None:
        assert vehicle["blocked_credit_days"] == blocked_credit_days, (
            f"blocked_credit_days expected {blocked_credit_days}, got {vehicle['blocked_credit_days']}"
        )


# --------------------------------------------------------------------------
# conserved inventories
# --------------------------------------------------------------------------
def assert_kit_ledger(
    kit: Mapping[str, Any],
    *,
    on_hand_qty: int,
    reserved_qty: int,
    available_qty: int,
    consumed_qty: int,
    received_qty_total: Optional[int] = None,
) -> None:
    """Assert the four derived kit quantities and the conservation invariant."""
    assert kit["on_hand_qty"] == on_hand_qty, f"on_hand_qty expected {on_hand_qty}, got {kit['on_hand_qty']}"
    assert kit["reserved_qty"] == reserved_qty, f"reserved_qty expected {reserved_qty}, got {kit['reserved_qty']}"
    assert kit["available_qty"] == available_qty, (
        f"available_qty expected {available_qty}, got {kit['available_qty']}"
    )
    assert kit["consumed_qty"] == consumed_qty, f"consumed_qty expected {consumed_qty}, got {kit['consumed_qty']}"
    total = received_qty_total if received_qty_total is not None else kit["received_qty_total"]
    assert kit["on_hand_qty"] + kit["consumed_qty"] == total, (
        "kit conservation violated: on_hand_qty + consumed_qty != received_qty_total "
        f"({kit['on_hand_qty']} + {kit['consumed_qty']} != {total})"
    )
    assert kit["available_qty"] == kit["on_hand_qty"] - kit["reserved_qty"], (
        "available_qty must equal on_hand_qty less reserved_qty"
    )


def assert_slot_ledger(
    carrier: Mapping[str, Any],
    *,
    committed_slots: int,
    available_slots: int,
    slot_capacity: Optional[int] = None,
) -> None:
    """Assert the carrier slot ledger and the slot conservation invariant."""
    assert carrier["committed_slots"] == committed_slots, (
        f"committed_slots expected {committed_slots}, got {carrier['committed_slots']}"
    )
    assert carrier["available_slots"] == available_slots, (
        f"available_slots expected {available_slots}, got {carrier['available_slots']}"
    )
    capacity = slot_capacity if slot_capacity is not None else carrier["slot_capacity"]
    assert carrier["committed_slots"] + carrier["available_slots"] == capacity, (
        "slot conservation violated: committed_slots + available_slots != slot_capacity "
        f"({carrier['committed_slots']} + {carrier['available_slots']} != {capacity})"
    )


def assert_open_allocation_count(dealer: Mapping[str, Any], expected: int) -> None:
    assert dealer["open_allocation_count"] == expected, (
        f"open_allocation_count expected {expected}, got {dealer['open_allocation_count']}"
    )


# --------------------------------------------------------------------------
# yard posture and center ledgers
# --------------------------------------------------------------------------
def assert_yard_state(
    center: Mapping[str, Any],
    *,
    occupied_slots: Optional[int] = None,
    free_slots: Optional[int] = None,
    posture: Optional[str] = None,
) -> None:
    if occupied_slots is not None:
        assert center["yard_occupied_slots"] == occupied_slots, (
            f"yard_occupied_slots expected {occupied_slots}, got {center['yard_occupied_slots']}"
        )
    if free_slots is not None:
        assert center["yard_free_slots"] == free_slots, (
            f"yard_free_slots expected {free_slots}, got {center['yard_free_slots']}"
        )
    if posture is not None:
        assert center["yard_posture"] == posture, (
            f"yard_posture expected {posture}, got {center['yard_posture']}"
        )
    assert center["yard_occupied_slots"] + center["yard_free_slots"] == center["yard_capacity_slots"], (
        "yard_free_slots must be yard_capacity_slots less yard_occupied_slots"
    )


def assert_center_ledgers(
    center: Mapping[str, Any],
    *,
    provisional_storage_accrued_cents: Optional[int] = None,
    realized_storage_revenue_cents: Optional[int] = None,
    repair_spend_cents: Optional[int] = None,
) -> None:
    if provisional_storage_accrued_cents is not None:
        assert center["provisional_storage_accrued_cents"] == provisional_storage_accrued_cents, (
            "provisional_storage_accrued_cents expected "
            f"{provisional_storage_accrued_cents}, got {center['provisional_storage_accrued_cents']}"
        )
    if realized_storage_revenue_cents is not None:
        assert center["realized_storage_revenue_cents"] == realized_storage_revenue_cents, (
            "realized_storage_revenue_cents expected "
            f"{realized_storage_revenue_cents}, got {center['realized_storage_revenue_cents']}"
        )
    if repair_spend_cents is not None:
        assert center["repair_spend_cents"] == repair_spend_cents, (
            f"repair_spend_cents expected {repair_spend_cents}, got {center['repair_spend_cents']}"
        )


# --------------------------------------------------------------------------
# freight settlement
# --------------------------------------------------------------------------
def assert_freight_breakdown(
    order: Mapping[str, Any],
    *,
    base_linehaul_cents: int,
    fuel_surcharge_cents: int,
    zone_accessorial_cents: int,
    gross_freight_cents: int,
    freight_discount_cents: int,
    freight_total_cents: int,
) -> None:
    """Assert all six freight fields, each supplied literally by the caller."""
    expected = {
        "base_linehaul_cents": base_linehaul_cents,
        "fuel_surcharge_cents": fuel_surcharge_cents,
        "zone_accessorial_cents": zone_accessorial_cents,
        "gross_freight_cents": gross_freight_cents,
        "freight_discount_cents": freight_discount_cents,
        "freight_total_cents": freight_total_cents,
    }
    for field, value in expected.items():
        assert order[field] == value, f"{field} expected {value}, got {order[field]}"
        assert isinstance(order[field], int), f"{field} must be an integer count of cents"


def assert_freight_unsettled(order: Mapping[str, Any]) -> None:
    """The freight fields are stamped at dispatch, not at allocation."""
    for field in (
        "base_linehaul_cents",
        "fuel_surcharge_cents",
        "zone_accessorial_cents",
        "gross_freight_cents",
        "freight_discount_cents",
        "freight_total_cents",
    ):
        assert order[field] == 0, f"{field} must remain 0 before dispatch, got {order[field]}"


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------
def assert_pagination_meta(
    meta: Mapping[str, Any],
    *,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    total_count: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if limit is not None:
        assert meta["limit"] == limit, f"limit expected {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset expected {offset}, got {meta['offset']}"
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"total_count expected {total_count}, got {meta['total_count']}"
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, f"has_more expected {has_more}, got {meta['has_more']}"


def assert_created_at_ascending(rows: Sequence[Mapping[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not ordered by created_at ascending: {stamps}"


# --------------------------------------------------------------------------
# dwell metrics report
# --------------------------------------------------------------------------
def assert_dwell_rows_cover_every_model_line(rows: Sequence[Mapping[str, Any]]) -> None:
    """One row per declared model line, sorted by ``model_line`` ascending."""
    lines = [row["model_line"] for row in rows]
    assert lines == sorted(MODEL_LINES), f"rows expected {sorted(MODEL_LINES)}, got {lines}"


def dwell_row(rows: Sequence[Mapping[str, Any]], model_line: str) -> Dict[str, Any]:
    matches = [row for row in rows if row["model_line"] == model_line]
    assert len(matches) == 1, f"expected exactly one row for {model_line}, got {len(matches)}"
    return dict(matches[0])


def assert_dwell_row(
    row: Mapping[str, Any],
    *,
    unit_count: int,
    avg_dwell_days: float,
    aging_0_15: int,
    aging_16_30: int,
    aging_31_plus: int,
    blocked_count: int,
    accrued_storage_cents: int,
) -> None:
    assert row["unit_count"] == unit_count, f"unit_count expected {unit_count}, got {row['unit_count']}"
    assert row["avg_dwell_days"] == avg_dwell_days, (
        f"avg_dwell_days expected {avg_dwell_days}, got {row['avg_dwell_days']}"
    )
    assert row["aging_0_15"] == aging_0_15, f"aging_0_15 expected {aging_0_15}, got {row['aging_0_15']}"
    assert row["aging_16_30"] == aging_16_30, f"aging_16_30 expected {aging_16_30}, got {row['aging_16_30']}"
    assert row["aging_31_plus"] == aging_31_plus, (
        f"aging_31_plus expected {aging_31_plus}, got {row['aging_31_plus']}"
    )
    assert row["blocked_count"] == blocked_count, (
        f"blocked_count expected {blocked_count}, got {row['blocked_count']}"
    )
    assert row["accrued_storage_cents"] == accrued_storage_cents, (
        f"accrued_storage_cents expected {accrued_storage_cents}, got {row['accrued_storage_cents']}"
    )


# --------------------------------------------------------------------------
# misc
# --------------------------------------------------------------------------
def ids_of(rows: Iterable[Mapping[str, Any]]) -> list:
    return [row["id"] for row in rows]


def assert_subset(record: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    """Assert that every named field of ``record`` holds the expected value."""
    for field, value in expected.items():
        assert record[field] == value, f"{field} expected {value!r}, got {record[field]!r}"
