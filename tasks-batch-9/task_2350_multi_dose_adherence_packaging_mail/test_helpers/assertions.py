"""Domain assertion helpers built on the framework validators."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .constants import (
    CARRIER_SERVICE_COST_CENTS,
    PACKAGING_COST_CENTS,
    PAGINATION_FIELDS,
    SHIPMENT_KIND_COST_CENTS,
)

__all__ = [
    "assert_envelope_shape",
    "assert_identity_fields",
    "assert_adherence_event_shape",
    "assert_no_pagination_fields",
    "assert_cycle_state",
    "assert_line_state",
    "assert_roll_state",
    "assert_shipment_state",
    "assert_patient_posture",
    "assert_memo",
    "assert_freight_cost",
    "assert_ids_in_order",
    "assert_total_count",
    "find_line_for_prescription",
    "line_by_prescription",
    "pouch_by_index",
    "memo_by_reason",
    "expected_freight_cents",
]


def assert_envelope_shape(response: Any, response_type: str) -> Dict[str, Any]:
    """Assert the success envelope's meta block and ``response_type``."""
    body = response.json()
    assert body["response_type"] == response_type, body
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), meta
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta
    return body


def assert_identity_fields(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """Assert the server-minted identity and audit fields of an ordinary entity."""
    assert is_valid_uuid(entity["id"]), entity["id"]
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int)
    if expected_version is not None:
        assert entity["version"] == expected_version, entity


def assert_adherence_event_shape(event: Dict[str, Any]) -> None:
    """Assert an adherence event carries no mutable audit fields."""
    assert is_valid_uuid(event["id"]), event["id"]
    assert is_iso8601_timestamp(event["created_at"]), event["created_at"]
    assert "version" not in event, event
    assert "updated_at" not in event, event


def assert_no_pagination_fields(response: Any) -> Dict[str, Any]:
    """Assert a single-resource read omits the four pagination fields."""
    body = response.json()
    for field in PAGINATION_FIELDS:
        assert field not in body["meta"], body["meta"]
    return body


def assert_cycle_state(
    cycle: Dict[str, Any],
    packaging_status: Optional[str] = None,
    insurance_status: Optional[str] = None,
    version: Optional[int] = None,
) -> None:
    """Assert a fill cycle's two independent state dimensions."""
    if packaging_status is not None:
        assert cycle["packaging_status"] == packaging_status, cycle
    if insurance_status is not None:
        assert cycle["insurance_status"] == insurance_status, cycle
    if version is not None:
        assert cycle["version"] == version, cycle


def assert_line_state(
    line: Dict[str, Any],
    line_status: Optional[str] = None,
    hold_reason: Optional[str] = "__unset__",
    packable_route: Optional[str] = None,
) -> None:
    """Assert a cycle line's status, hold reason and route."""
    if line_status is not None:
        assert line["line_status"] == line_status, line
    if hold_reason != "__unset__":
        assert line["hold_reason"] == hold_reason, line
    if packable_route is not None:
        assert line["packable_route"] == packable_route, line


def assert_roll_state(
    roll: Dict[str, Any],
    verification_status: Optional[str] = None,
    mismatch_pouch_count: Optional[int] = None,
    rework_count: Optional[int] = None,
) -> None:
    """Assert a pouch roll's bench state and counters."""
    if verification_status is not None:
        assert roll["verification_status"] == verification_status, roll
    if mismatch_pouch_count is not None:
        assert roll["mismatch_pouch_count"] == mismatch_pouch_count, roll
    if rework_count is not None:
        assert roll["rework_count"] == rework_count, roll


def assert_shipment_state(
    shipment: Dict[str, Any],
    status: Optional[str] = None,
    ship_cost_cents: Optional[int] = None,
) -> None:
    """Assert a parcel's transit state and freight cost."""
    if status is not None:
        assert shipment["status"] == status, shipment
    if ship_cost_cents is not None:
        assert shipment["ship_cost_cents"] == ship_cost_cents, shipment


def assert_patient_posture(
    patient: Dict[str, Any],
    autoship_status: Optional[str] = None,
    pause_reason: Optional[str] = "__unset__",
    adherence_score_pct: Optional[int] = None,
    credit_balance_cents: Optional[int] = None,
    consecutive_missed_pickups: Optional[int] = None,
) -> None:
    """Assert a patient's auto-ship posture and derived figures."""
    if autoship_status is not None:
        assert patient["autoship_status"] == autoship_status, patient
    if pause_reason != "__unset__":
        assert patient["pause_reason"] == pause_reason, patient
    if adherence_score_pct is not None:
        assert patient["adherence_score_pct"] == adherence_score_pct, patient
    if credit_balance_cents is not None:
        assert patient["credit_balance_cents"] == credit_balance_cents, patient
    if consecutive_missed_pickups is not None:
        assert patient["consecutive_missed_pickups"] == consecutive_missed_pickups, patient


def assert_memo(
    memo: Dict[str, Any],
    reason: Optional[str] = None,
    amount_cents: Optional[int] = None,
    status: Optional[str] = None,
    cycle_id: Optional[str] = None,
    applied_to_cycle_id: Optional[str] = "__unset__",
) -> None:
    """Assert a credit memo's reason, amount and application state."""
    if reason is not None:
        assert memo["reason"] == reason, memo
    if amount_cents is not None:
        assert memo["amount_cents"] == amount_cents, memo
    if status is not None:
        assert memo["status"] == status, memo
    if cycle_id is not None:
        assert memo["cycle_id"] == cycle_id, memo
    if applied_to_cycle_id != "__unset__":
        assert memo["applied_to_cycle_id"] == applied_to_cycle_id, memo


def expected_freight_cents(shipment_kind: str, carrier_service: str, packaging: str) -> int:
    """The sum of the three independent additive freight components."""
    return (
        SHIPMENT_KIND_COST_CENTS[shipment_kind]
        + PACKAGING_COST_CENTS[packaging]
        + CARRIER_SERVICE_COST_CENTS[carrier_service]
    )


def assert_freight_cost(
    shipment: Dict[str, Any], shipment_kind: str, carrier_service: str, packaging: str
) -> None:
    """Assert a parcel's freight equals the sum of its three components."""
    assert shipment["ship_cost_cents"] == expected_freight_cents(
        shipment_kind, carrier_service, packaging
    ), shipment


def assert_ids_in_order(rows: List[Dict[str, Any]], expected_ids: Iterable[str]) -> None:
    """Assert a listing returned exactly these rows in exactly this order."""
    assert [row["id"] for row in rows] == list(expected_ids), rows


def assert_total_count(response: Any, expected: int) -> List[Dict[str, Any]]:
    """Assert a listing's ``total_count`` and return its rows."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, meta
    return rows


def line_by_prescription(lines: List[Dict[str, Any]], prescription_id: str) -> Dict[str, Any]:
    """The one line of this listing that references the given prescription."""
    matches = [line for line in lines if line["prescription_id"] == prescription_id]
    assert len(matches) == 1, matches
    return matches[0]


# Historical alias kept because both spellings read naturally at call sites.
find_line_for_prescription = line_by_prescription


def pouch_by_index(pouches: List[Dict[str, Any]], pouch_index: int) -> Dict[str, Any]:
    """The pouch of this listing carrying the given 1-based index."""
    matches = [pouch for pouch in pouches if pouch["pouch_index"] == pouch_index]
    assert len(matches) == 1, matches
    return matches[0]


def memo_by_reason(memos: List[Dict[str, Any]], reason: str) -> Dict[str, Any]:
    """The one memo of this listing carrying the given reason."""
    matches = [memo for memo in memos if memo["reason"] == reason]
    assert len(matches) == 1, matches
    return matches[0]
