"""Domain assertions for the certification API.

These wrap the generic framework helpers with the shapes this contract declares:
the common resource properties, the audit trail's append-only shape, the money
and day-count discipline, and the two ledger invariants.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from . import constants as c
from .types import JsonDict, JsonList


def assert_common_fields(row: JsonDict, expected_version: Optional[int] = None) -> None:
    """Every resource except the audit trail carries id, created_at, updated_at, version."""
    assert is_valid_uuid(row["id"]), f"id must be a bare UUID string: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp: {row['created_at']!r}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC timestamp: {row['updated_at']!r}"
    )
    assert isinstance(row["version"], int), "version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"Expected version {expected_version}, got {row['version']}"
        )


def assert_audit_entry_shape(entry: JsonDict) -> None:
    """An audit entry is append-only, so it carries no updated_at and no version."""
    assert is_valid_uuid(entry["id"]), f"id must be a bare UUID string: {entry['id']!r}"
    assert is_iso8601_timestamp(entry["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp: {entry['created_at']!r}"
    )
    assert "version" not in entry, "An audit entry must not expose a version"
    assert "updated_at" not in entry, "An audit entry must not expose an updated_at"


def assert_integer_cents(row: JsonDict, *field_names: str) -> None:
    """Every monetary quantity is an integer number of cents, never a decimal or string."""
    for name in field_names:
        value = row[name]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{name} must be an integer number of cents, got {value!r}"
        )


def assert_whole_days(row: JsonDict, *field_names: str) -> None:
    """certified_days, entitlement_days_charged and days_late are whole day counts."""
    for name in field_names:
        value = row[name]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{name} must be a whole number of days, got {value!r}"
        )


def assert_event_sequence(entries: JsonList, expected_event_types: List[str]) -> None:
    """The trail reads in ascending sequence_index with the expected events in order."""
    actual_types = [entry["event_type"] for entry in entries]
    assert actual_types == expected_event_types, (
        f"Expected audit events {expected_event_types}, got {actual_types}"
    )
    indices = [entry["sequence_index"] for entry in entries]
    assert indices == list(range(1, len(entries) + 1)), (
        f"sequence_index must be a gapless per-certification counter starting at 1, "
        f"got {indices}"
    )


def assert_entitlement_ledger_balances(
    student: JsonDict, total_currently_charged: int
) -> None:
    """Remaining entitlement equals granted entitlement minus everything charged."""
    assert student["entitlement_days_remaining"] == (
        student["entitlement_days_granted"] - total_currently_charged
    ), (
        f"entitlement_days_remaining {student['entitlement_days_remaining']} must equal "
        f"entitlement_days_granted {student['entitlement_days_granted']} minus the "
        f"{total_currently_charged} days currently charged"
    )


def assert_pool_ledger_balances(
    agreement: JsonDict, total_committed_school_share: int
) -> None:
    """Remaining pool equals the annual pool minus the school share of live awards."""
    assert agreement["pool_remaining_cents"] == (
        agreement["annual_pool_cents"] - total_committed_school_share
    ), (
        f"pool_remaining_cents {agreement['pool_remaining_cents']} must equal "
        f"annual_pool_cents {agreement['annual_pool_cents']} minus the "
        f"{total_committed_school_share} cents of school share currently committed"
    )


def assert_fields(row: JsonDict, expected: Dict[str, Any]) -> None:
    """Assert a batch of field values with one clear message per mismatch."""
    for name, value in expected.items():
        assert name in row, f"Response is missing the field {name!r}"
        assert row[name] == value, (
            f"Expected {name} == {value!r}, got {row[name]!r}"
        )


def assert_derived_enrollment_block(
    certification: JsonDict,
    certified_days: int,
    rate_of_pursuit_pct: int,
    rop_tier_pct: int,
    training_time: str,
    modality: str,
    mha_eligible: bool,
    mha_monthly_rate_cents: int,
) -> None:
    """The block derived at drafting and rebuilt identically on every revision."""
    assert_fields(
        certification,
        {
            "certified_days": certified_days,
            "rate_of_pursuit_pct": rate_of_pursuit_pct,
            "rop_tier_pct": rop_tier_pct,
            "training_time": training_time,
            "modality": modality,
            "mha_eligible": mha_eligible,
            "mha_monthly_rate_cents": mha_monthly_rate_cents,
        },
    )


def assert_covered_tuition_block(
    certification: JsonDict,
    net_covered_cents: int,
    ay_cap_remaining_before_cents: int,
    va_tuition_cents: int,
    cap_charged_cents: int,
    yr_gap_cents: int,
) -> None:
    """The five figures the covered-tuition waterfall writes onto the certification."""
    assert_integer_cents(
        certification,
        "net_covered_cents",
        "ay_cap_remaining_before_cents",
        "va_tuition_cents",
        "cap_charged_cents",
        "yr_gap_cents",
    )
    assert_fields(
        certification,
        {
            "net_covered_cents": net_covered_cents,
            "ay_cap_remaining_before_cents": ay_cap_remaining_before_cents,
            "va_tuition_cents": va_tuition_cents,
            "cap_charged_cents": cap_charged_cents,
            "yr_gap_cents": yr_gap_cents,
        },
    )
    assert certification["cap_charged_cents"] == certification["va_tuition_cents"], (
        "cap_charged_cents must equal va_tuition_cents and nothing else"
    )


def assert_award_amounts(
    award: JsonDict,
    yr_gap_basis_cents: int,
    per_student_remaining_before_cents: int,
    pool_remaining_before_cents: int,
    school_share_cents: int,
    student_out_of_pocket_cents: int,
) -> None:
    """The award snapshot, including VA's dollar-for-dollar match."""
    assert_fields(
        award,
        {
            "yr_gap_basis_cents": yr_gap_basis_cents,
            "per_student_remaining_before_cents": per_student_remaining_before_cents,
            "pool_remaining_before_cents": pool_remaining_before_cents,
            "school_share_cents": school_share_cents,
            "va_match_cents": school_share_cents,
            "student_out_of_pocket_cents": student_out_of_pocket_cents,
        },
    )


def find_entries_by_event(entries: JsonList, event_type: str) -> JsonList:
    """Every audit entry of one event type, in the order the trail returned them."""
    return [entry for entry in entries if entry["event_type"] == event_type]


def assert_system_actor(entry: JsonDict) -> None:
    """A cascade-written entry records the literal system actor on both fields."""
    assert_fields(
        entry,
        {"actor_role": c.ACTOR_SYSTEM, "actor_user_id": c.ACTOR_SYSTEM},
    )
