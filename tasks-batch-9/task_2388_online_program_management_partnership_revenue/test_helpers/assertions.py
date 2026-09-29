"""Domain assertions for the Online Program Management Partnership API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# --- Identity and timestamps ---------------------------------------------


def assert_identity_fields(entity: Dict[str, Any]) -> None:
    """Every resource is addressed by a UUID `id` and stamped with `created_at`."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), f"bad created_at: {entity['created_at']!r}"


def assert_versioned_entity(entity: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A resource carrying the full identity set also carries `updated_at` and `version`."""
    assert_identity_fields(entity)
    assert is_iso8601_timestamp(entity["updated_at"]), f"bad updated_at: {entity['updated_at']!r}"
    assert isinstance(entity["version"], int) and entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_append_only_entity(entity: Dict[str, Any]) -> None:
    """An append-only ledger entry carries only `id` and `created_at`."""
    assert_identity_fields(entity)
    assert "updated_at" not in entity, "append-only ledger entry must not expose updated_at"
    assert "version" not in entity, "append-only ledger entry must not expose version"


def normalise_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant with or without fractional digits."""
    assert value.endswith("Z"), f"timestamp is not UTC-suffixed: {value!r}"
    return datetime.fromisoformat(value[:-1]).replace(tzinfo=timezone.utc)


def assert_logical_instant(actual: str, expected: str) -> None:
    """A system timestamp must carry the logical clock instant, not wall-clock time."""
    assert is_iso8601_timestamp(actual), f"bad timestamp format: {actual!r}"
    assert normalise_instant(actual) == normalise_instant(expected), (
        f"expected the logical instant {expected}, got {actual}"
    )


# --- Money and rates ------------------------------------------------------


def assert_integer_cents(value: Any, field: str = "amount") -> None:
    """Every monetary quantity is an integer number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}"
    )


def assert_all_integer_cents(entity: Dict[str, Any], fields: Iterable[str]) -> None:
    for field in fields:
        if entity.get(field) is not None:
            assert_integer_cents(entity[field], field)


def assert_score_2dp(value: Any, field: str = "demand score") -> None:
    """A demand score is rounded half up to 2 decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == float(value), f"{field} carries more than 2 decimals: {value!r}"


def assert_ratio_4dp(value: Any, field: str = "conversion_rate") -> None:
    """A conversion rate or breach ratio is rounded half up to 4 decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 4) == float(value), f"{field} carries more than 4 decimals: {value!r}"


# --- The two conserved ledgers (PRD 2.7) ---------------------------------


def assert_cash_position(
    partnership: Dict[str, Any], payments_cents: int, refunds_cents: int
) -> None:
    """INV-1: partnership collected cash is every PAYMENT less every REFUND."""
    expected = payments_cents - refunds_cents
    assert partnership["collected_tuition_cents"] == expected, (
        "collected_tuition_cents must equal payments minus refunds: "
        f"expected {expected}, got {partnership['collected_tuition_cents']}"
    )


def assert_enrollment_cash_position(
    enrollment: Dict[str, Any], collected_cents: int, refunded_cents: int
) -> None:
    """INV-1 at the enrollment grain: gross collected and gross refunded both persist."""
    assert enrollment["collected_cents"] == collected_cents
    assert enrollment["refunded_cents"] == refunded_cents


def assert_marketing_envelope(partnership: Dict[str, Any], posted_net_cents: int) -> None:
    """INV-2: the budget equals the remaining budget plus posted net spend."""
    assert (
        partnership["marketing_budget_remaining_cents"] + posted_net_cents
        == partnership["marketing_budget_cents"]
    ), (
        "marketing_budget_cents must equal marketing_budget_remaining_cents plus posted net spend: "
        f"{partnership['marketing_budget_remaining_cents']} + {posted_net_cents} != "
        f"{partnership['marketing_budget_cents']}"
    )


def assert_teach_out_buckets_conserve(plan: Dict[str, Any]) -> None:
    """The three teach-out liability buckets sum exactly to the teach-out cost."""
    total = (
        plan["holdback_applied_cents"]
        + plan["partner_obligation_cents"]
        + plan["university_residual_cents"]
    )
    assert total == plan["teach_out_cost_cents"], (
        f"buckets sum to {total} but teach_out_cost_cents is {plan['teach_out_cost_cents']}"
    )


# --- Settlement waterfall (PRD 3.8) -------------------------------------


def assert_waterfall_internally_consistent(statement: Dict[str, Any]) -> None:
    """subtotal, holdback and net_payable must agree with the pinned step order."""
    assert (
        statement["subtotal_cents"]
        == statement["share_gross_cents"] - statement["marketing_recoupment_cents"]
    ), "subtotal_cents must be share_gross_cents minus marketing_recoupment_cents"
    assert (
        statement["net_payable_cents"]
        == statement["subtotal_cents"]
        - statement["holdback_cents"]
        + statement["fee_for_service_cents"]
    ), "net_payable_cents must be subtotal minus holdback plus fee_for_service"


# --- Pagination -----------------------------------------------------------


def assert_pagination_meta(
    meta: Dict[str, Any], limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """A list response reports limit, offset, total_count and has_more."""
    assert meta["limit"] == limit
    assert meta["offset"] == offset
    assert meta["total_count"] == total_count
    assert meta["has_more"] is has_more
