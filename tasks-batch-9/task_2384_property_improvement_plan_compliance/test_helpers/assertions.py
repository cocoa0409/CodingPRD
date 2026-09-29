"""Domain assertions built on top of the framework's generic validators."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# ---------------------------------------------------------------------------
# Identity, timestamps and the version counter
# ---------------------------------------------------------------------------


def assert_identity_fields(entity: Dict[str, Any], label: str = "resource") -> None:
    """Every resource carries a server-minted UUID ``id`` and an ISO ``created_at``."""
    assert is_valid_uuid(entity.get("id")), f"{label}.id must be a UUID with no type prefix: {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp: {entity.get('created_at')!r}"
    )


def assert_versioned_fields(entity: Dict[str, Any], label: str = "resource") -> None:
    """Almost every resource additionally carries ``updated_at`` and ``version``."""
    assert_identity_fields(entity, label)
    assert is_iso8601_timestamp(entity.get("updated_at")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp: {entity.get('updated_at')!r}"
    )
    assert isinstance(entity.get("version"), int), f"{label}.version must be an integer"
    assert entity["version"] >= 1, f"{label}.version starts at 1 on creation, got {entity['version']}"


def assert_append_only_entry(entry: Dict[str, Any]) -> None:
    """A ledger row carries only ``id`` and ``created_at``: no ``updated_at``, no ``version``."""
    assert_identity_fields(entry, "ComplianceLedgerEntry")
    assert "updated_at" not in entry, (
        "updated_at must be absent from a ComplianceLedgerEntry representation entirely"
    )
    assert "version" not in entry, (
        "version must be absent from a ComplianceLedgerEntry representation entirely"
    )


# ---------------------------------------------------------------------------
# Field-level helpers
# ---------------------------------------------------------------------------


def assert_money_field(entity: Dict[str, Any], field: str) -> None:
    """Monetary amounts are integer counts of cents, never decimal strings or floats."""
    value = entity.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer count of cents, got {value!r}"
    )


def assert_decimal_scale(value: Any, places: int, label: str) -> None:
    """The value must carry no more than ``places`` decimal places."""
    assert value is not None, f"{label} must be present"
    exponent = Decimal(str(value)).normalize().as_tuple().exponent
    scale = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    assert scale <= places, f"{label} must carry at most {places} decimal places, got {value!r}"


def assert_field_equals(entity: Dict[str, Any], field: str, expected: Any, label: str = "") -> None:
    prefix = f"{label}." if label else ""
    assert entity.get(field) == expected, (
        f"{prefix}{field} should be {expected!r}, got {entity.get(field)!r}"
    )


def assert_fields_equal(entity: Dict[str, Any], expected: Dict[str, Any], label: str = "") -> None:
    for field, value in expected.items():
        assert_field_equals(entity, field, value, label)


# ---------------------------------------------------------------------------
# Plan, item and posture assertions
# ---------------------------------------------------------------------------


def assert_plan_dimensions(
    plan: Dict[str, Any],
    status: Optional[str] = None,
    dispute_state: Optional[str] = None,
) -> None:
    """The two plan dimensions are independent, so they are asserted independently."""
    if status is not None:
        assert plan.get("status") == status, (
            f"plan lifecycle dimension should be {status}, got {plan.get('status')!r}"
        )
    if dispute_state is not None:
        assert plan.get("dispute_state") == dispute_state, (
            f"plan dispute dimension should be {dispute_state}, got {plan.get('dispute_state')!r}"
        )


def assert_item_state(
    item: Dict[str, Any],
    status: Optional[str] = None,
    deadline_date: Optional[str] = None,
    is_overdue: Optional[bool] = None,
) -> None:
    if status is not None:
        assert item.get("status") == status, (
            f"item status should be {status}, got {item.get('status')!r}"
        )
    if deadline_date is not None:
        assert item.get("deadline_date") == deadline_date, (
            f"item deadline_date should be {deadline_date}, got {item.get('deadline_date')!r}"
        )
    if is_overdue is not None:
        assert item.get("is_overdue") is is_overdue, (
            f"item is_overdue should be {is_overdue}, got {item.get('is_overdue')!r}"
        )


def assert_posture(prop: Dict[str, Any], score: int, posture: str) -> None:
    assert prop.get("compliance_risk_score") == score, (
        f"compliance_risk_score should be {score}, got {prop.get('compliance_risk_score')!r}"
    )
    assert prop.get("compliance_posture") == posture, (
        f"compliance_posture should be {posture}, got {prop.get('compliance_posture')!r}"
    )


def assert_priority_ranks(items: Iterable[Dict[str, Any]], expected: Dict[str, int]) -> None:
    """``expected`` maps item id to the contiguous rank it should hold."""
    actual = {item["id"]: item.get("priority_rank") for item in items}
    for item_id, rank in expected.items():
        assert actual.get(item_id) == rank, (
            f"item {item_id} should hold priority_rank {rank}, got {actual.get(item_id)!r}"
        )


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------


def ledger_entries_of_type(entries: Iterable[Dict[str, Any]], entry_type: str) -> List[Dict[str, Any]]:
    return [entry for entry in entries if entry.get("entry_type") == entry_type]


def assert_ledger_contains(
    entries: Iterable[Dict[str, Any]],
    entry_type: str,
    delta_cents: Optional[int] = None,
    item_id: Any = "__unchecked__",
    count: Optional[int] = None,
) -> Dict[str, Any]:
    """Assert a ledger entry of ``entry_type`` exists, optionally pinning its fields."""
    matches = ledger_entries_of_type(entries, entry_type)
    assert matches, f"expected a ledger entry of type {entry_type}, found {[e.get('entry_type') for e in entries]}"
    if count is not None:
        assert len(matches) == count, (
            f"expected {count} ledger entries of type {entry_type}, found {len(matches)}"
        )
    entry = matches[-1]
    assert_append_only_entry(entry)
    if delta_cents is not None:
        assert entry.get("delta_cents") == delta_cents, (
            f"{entry_type}.delta_cents should be {delta_cents}, got {entry.get('delta_cents')!r}"
        )
    if item_id != "__unchecked__":
        assert entry.get("item_id") == item_id, (
            f"{entry_type}.item_id should be {item_id!r}, got {entry.get('item_id')!r}"
        )
    return entry


def assert_no_ledger_entry_of_type(entries: Iterable[Dict[str, Any]], entry_type: str) -> None:
    matches = ledger_entries_of_type(entries, entry_type)
    assert not matches, f"expected no ledger entry of type {entry_type}, found {len(matches)}"


# ---------------------------------------------------------------------------
# Conserved quantities
# ---------------------------------------------------------------------------


def assert_reserve_corpus_conserved(prop: Dict[str, Any], draws: Iterable[Dict[str, Any]]) -> None:
    """balance + disbursed draws == initial balance + contributions, at every instant."""
    disbursed = sum(
        draw["amount_cents"] for draw in draws if draw.get("status") == "DISBURSED"
    )
    corpus = prop["initial_reserve_balance_cents"] + prop["reserve_contributed_total_cents"]
    assert prop["reserve_balance_cents"] + disbursed == corpus, (
        f"reserve corpus drifted: balance {prop['reserve_balance_cents']} + disbursed {disbursed} "
        f"should equal {corpus}"
    )


def assert_key_inventory_conserved(
    prop: Dict[str, Any], active_phases: Iterable[Dict[str, Any]]
) -> None:
    """rooms_out_of_service_current equals the active phases' keys, and the split sums to room_count."""
    expected_out = sum(phase["rooms_out_of_service"] for phase in active_phases)
    assert prop["rooms_out_of_service_current"] == expected_out, (
        f"rooms_out_of_service_current should equal the active phases' keys {expected_out}, "
        f"got {prop['rooms_out_of_service_current']}"
    )
    sellable = prop["room_count"] - prop["rooms_out_of_service_current"]
    assert prop["rooms_out_of_service_current"] + sellable == prop["room_count"], (
        "keys out of service plus sellable keys must equal room_count"
    )


# ---------------------------------------------------------------------------
# Computed reads
# ---------------------------------------------------------------------------

RISK_SUMMARY_FIELDS = (
    "property_id",
    "snapshot_score",
    "snapshot_posture",
    "projected_score",
    "projected_posture",
    "projection_horizon_days",
    "overdue_life_safety_count",
    "overdue_guest_facing_count",
    "overdue_back_of_house_count",
    "projected_life_safety_count",
    "projected_guest_facing_count",
    "projected_back_of_house_count",
    "funding_gap_cents",
    "funding_gap_penalty",
    "open_major_defect_count",
    "open_critical_defect_count",
    "open_plan_count",
)

COST_SUMMARY_FIELDS = (
    "plan_id",
    "included_item_count",
    "brand_scoped_total_cents",
    "owner_claimed_total_cents",
    "variance_cents",
    "variance_pct",
    "contingency_pct_applied",
    "funding_requirement_cents",
    "authorized_cents",
    "funding_gap_cents",
    "funding_gap_pct",
)


def assert_risk_summary_shape(summary: Dict[str, Any]) -> None:
    for field in RISK_SUMMARY_FIELDS:
        assert field in summary, f"risk summary must expose {field}"


def assert_cost_summary_shape(summary: Dict[str, Any]) -> None:
    for field in COST_SUMMARY_FIELDS:
        assert field in summary, f"cost summary must expose {field}"


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            f"meta.total_count should be {total_count}, got {meta['total_count']}"
        )
    if limit is not None:
        assert meta["limit"] == limit, f"meta.limit should be {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"meta.offset should be {offset}, got {meta['offset']}"
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"meta.has_more should be {has_more}, got {meta['has_more']}"
        )


__all__ = [
    "assert_identity_fields",
    "assert_versioned_fields",
    "assert_append_only_entry",
    "assert_money_field",
    "assert_decimal_scale",
    "assert_field_equals",
    "assert_fields_equal",
    "assert_plan_dimensions",
    "assert_item_state",
    "assert_posture",
    "assert_priority_ranks",
    "ledger_entries_of_type",
    "assert_ledger_contains",
    "assert_no_ledger_entry_of_type",
    "assert_reserve_corpus_conserved",
    "assert_key_inventory_conserved",
    "assert_risk_summary_shape",
    "assert_cost_summary_shape",
    "assert_pagination_meta",
    "RISK_SUMMARY_FIELDS",
    "COST_SUMMARY_FIELDS",
]
