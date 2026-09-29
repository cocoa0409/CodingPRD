"""Domain assertion helpers.

These wrap the repeated multi-field checks — the six-line bill, the three-way
payer split, the grant-conservation identity, window occupancy, the two status
dimensions, and the identity-block split between ordinary resources and the two
append-only record collections.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    COURIER_PROJECTION_KEYS,
    COURIER_PROJECTION_REDACTED_FIELD_COUNT,
)

Entity = Dict[str, Any]

# The six bill lines, in the order the pricing vector declares them.
FEE_LINE_FIELDS = [
    "base_line_cents",
    "mileage_line_cents",
    "cold_pack_line_cents",
    "controlled_line_cents",
    "after_hours_line_cents",
    "reattempt_line_cents",
]


# ─── Identity block ───────────────────────────────────


def assert_versioned_entity(entity: Entity) -> None:
    """A resource that carries the full identity block."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int) and entity["version"] >= 1


def assert_append_only_record(record: Entity) -> None:
    """A record of something that already happened: no updated_at, no version."""
    assert is_valid_uuid(record["id"]), f"id is not a UUID: {record['id']!r}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert "updated_at" not in record, "an append-only record must not expose updated_at"
    assert "version" not in record, "an append-only record must not expose version"


def _instant(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(text)


def assert_instant(actual: str, expected: str) -> None:
    """Two ISO 8601 strings name the same instant, whatever the fractional digits."""
    assert is_iso8601_timestamp(actual), actual
    assert _instant(actual) == _instant(expected), f"{actual} is not the instant {expected}"


# ─── Money ────────────────────────────────────────────


def assert_fee_lines(allocation: Entity, expected_lines: Sequence[int]) -> None:
    """The ordered six-line vector, zeros retained in position."""
    actual = [allocation[field] for field in FEE_LINE_FIELDS]
    assert actual == list(expected_lines), f"line vector {actual} != {list(expected_lines)}"
    assert allocation["fee_subtotal_cents"] == sum(expected_lines), (
        f"fee_subtotal_cents {allocation['fee_subtotal_cents']} != sum of lines {sum(expected_lines)}"
    )


def assert_payer_split_identity(allocation: Entity) -> None:
    """plan_grant + patient_payable + pharmacy_payable must reconstruct the subtotal."""
    total = (
        allocation["plan_grant_cents"]
        + allocation["patient_payable_cents"]
        + allocation["pharmacy_payable_cents"]
    )
    assert total == allocation["fee_subtotal_cents"], (
        f"payer split {total} != fee_subtotal_cents {allocation['fee_subtotal_cents']}"
    )


def assert_payer_mix(
    allocation: Entity,
    *,
    patient_gross_share_cents: Optional[int] = None,
    plan_grant_cents: Optional[int] = None,
    absorption_tier_cents: Optional[int] = None,
    pharmacy_absorption_cents: Optional[int] = None,
    patient_payable_cents: Optional[int] = None,
    pharmacy_payable_cents: Optional[int] = None,
) -> None:
    """Assert the named waterfall figures and always re-check the split identity."""
    expected = {
        "patient_gross_share_cents": patient_gross_share_cents,
        "plan_grant_cents": plan_grant_cents,
        "absorption_tier_cents": absorption_tier_cents,
        "pharmacy_absorption_cents": pharmacy_absorption_cents,
        "patient_payable_cents": patient_payable_cents,
        "pharmacy_payable_cents": pharmacy_payable_cents,
    }
    for field, value in expected.items():
        if value is not None:
            assert allocation[field] == value, f"{field} {allocation[field]} != {value}"
    assert_payer_split_identity(allocation)


def assert_cost_share_pct(allocation: Entity, expected: float) -> None:
    """The percentage is recorded to exactly two decimals."""
    assert allocation["cost_share_pct_applied"] == pytest.approx(expected, abs=0.01)


def assert_grant_conservation(grant: Entity) -> None:
    """The budget must always equal remaining plus committed plus consumed."""
    total = grant["remaining_cents"] + grant["committed_cents"] + grant["consumed_cents"]
    assert total == grant["grant_budget_cents"], (
        f"remaining+committed+consumed {total} != grant_budget_cents {grant['grant_budget_cents']}"
    )


def assert_grant_ledger(
    grant: Entity,
    *,
    committed_cents: Optional[int] = None,
    consumed_cents: Optional[int] = None,
    remaining_cents: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    if committed_cents is not None:
        assert grant["committed_cents"] == committed_cents
    if consumed_cents is not None:
        assert grant["consumed_cents"] == consumed_cents
    if remaining_cents is not None:
        assert grant["remaining_cents"] == remaining_cents
    if status is not None:
        assert grant["status"] == status
    assert_grant_conservation(grant)


# ─── Deliveries, windows, couriers ────────────────────


def assert_delivery_state(
    delivery: Entity,
    custody_status: Optional[str] = None,
    settlement_status: Optional[str] = None,
) -> None:
    """The two status dimensions advance independently, so check them separately."""
    if custody_status is not None:
        assert delivery["custody_status"] == custody_status, (
            f"custody_status {delivery['custody_status']} != {custody_status}"
        )
    if settlement_status is not None:
        assert delivery["settlement_status"] == settlement_status, (
            f"settlement_status {delivery['settlement_status']} != {settlement_status}"
        )


def assert_window_occupancy(
    window: Entity,
    reserved_slots: Optional[int] = None,
    available_slots: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    if reserved_slots is not None:
        assert window["reserved_slots"] == reserved_slots
    if available_slots is not None:
        assert window["available_slots"] == available_slots
    if status is not None:
        assert window["status"] == status
    assert window["available_slots"] == window["capacity_slots"] - window["reserved_slots"]
    assert window["available_slots"] >= 0


def assert_reliability_scores(
    courier: Entity,
    rolling: Optional[float] = None,
    lifetime: Optional[float] = None,
) -> None:
    """Both scores are recorded to two decimal places."""
    if rolling is not None:
        assert courier["rolling_reliability_score"] == pytest.approx(rolling, abs=0.01), (
            f"rolling {courier['rolling_reliability_score']} != {rolling}"
        )
    if lifetime is not None:
        assert courier["lifetime_reliability_score"] == pytest.approx(lifetime, abs=0.01), (
            f"lifetime {courier['lifetime_reliability_score']} != {lifetime}"
        )


def assert_courier_counters(
    courier: Entity,
    attempt_total_count: Optional[int] = None,
    delivered_count: Optional[int] = None,
    active_delivery_count: Optional[int] = None,
    status: Optional[str] = None,
) -> None:
    if attempt_total_count is not None:
        assert courier["attempt_total_count"] == attempt_total_count
    if delivered_count is not None:
        assert courier["delivered_count"] == delivered_count
    if active_delivery_count is not None:
        assert courier["active_delivery_count"] == active_delivery_count
    if status is not None:
        assert courier["status"] == status


# ─── HIPAA projection ─────────────────────────────────

# The six values withheld from the courier-limited projection.
WITHHELD_FROM_COURIER = [
    "full_name",
    "date_of_birth",
    "total_rx_value_cents",
    "controlled_schedule",
    "health_plan_id",
    "fee_subtotal_cents",
]


def assert_courier_projection_shape(view: Entity) -> None:
    """Exactly thirteen values, none of the six withheld ones, count pinned at six."""
    assert sorted(view.keys()) == sorted(COURIER_PROJECTION_KEYS), (
        f"projection keys {sorted(view.keys())} != {sorted(COURIER_PROJECTION_KEYS)}"
    )
    for withheld in WITHHELD_FROM_COURIER:
        assert withheld not in view, f"{withheld} must never reach a courier"
    assert view["redacted_field_count"] == COURIER_PROJECTION_REDACTED_FIELD_COUNT


def masked(full_name: str) -> str:
    """Keep each token's first character, asterisk out the rest."""
    return " ".join(token[0] + "*" * (len(token) - 1) for token in full_name.split())


# ─── Collections ──────────────────────────────────────


def ids_of(rows: List[Entity]) -> List[str]:
    return [row["id"] for row in rows]


def assert_contains_id(rows: List[Entity], entity_id: str) -> None:
    assert entity_id in ids_of(rows), f"{entity_id} missing from {ids_of(rows)}"


def assert_excludes_id(rows: List[Entity], entity_id: str) -> None:
    assert entity_id not in ids_of(rows), f"{entity_id} unexpectedly present"


def find_by(rows: List[Entity], **match: Any) -> Entity:
    """Return the single row matching every keyword criterion."""
    hits = [row for row in rows if all(row.get(k) == v for k, v in match.items())]
    assert len(hits) == 1, f"expected exactly one row matching {match}, found {len(hits)}"
    return hits[0]
