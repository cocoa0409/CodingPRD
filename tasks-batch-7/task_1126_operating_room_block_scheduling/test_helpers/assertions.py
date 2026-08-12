"""Entity assertions and domain invariant checkers (PRD §2.4 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BlockStatus,
    CasePriority,
    CaseStatus,
    CoverageStatus,
    ProcedureClass,
    RequestStatus,
    ReviewDecision,
    ReviewStatus,
    SlotStatus,
    VoteValue,
)


def _assert_common_fields(data: dict):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_snapshot_fields(data: dict):
    """Immutable snapshots / append-only rows carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "updated_at must be absent on this resource"
    assert "version" not in data, "version must be absent on this resource"


def assert_service_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["target_utilization_pct"], (int, float))
    assert isinstance(data["release_deadline_hours"], int)


def assert_surgeon(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("service_line_id", "")), "service_line_id must be a UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["duration_bias_factor"], (int, float))
    assert isinstance(data["completed_cases_count"], int)
    assert isinstance(data["on_time_rate_pct"], (int, float))


def assert_operating_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["room_name"], str) and len(data["room_name"]) > 0
    assert isinstance(data["is_hybrid"], bool)


def assert_block_allocation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("service_line_id", "")), "service_line_id must be a UUID"
    if data.get("surgeon_id") is not None:
        assert is_valid_uuid(data["surgeon_id"]), "surgeon_id must be a UUID when set"
    assert is_valid_uuid(data.get("or_id", "")), "or_id must be a UUID"
    assert isinstance(data["date"], str) and len(data["date"]) == 10
    assert isinstance(data["start_minute"], int) and data["start_minute"] >= 0
    assert isinstance(data["end_minute"], int) and data["end_minute"] <= 1440
    assert data["end_minute"] > data["start_minute"]
    assert isinstance(data["original_minutes"], int)
    assert isinstance(data["reserved_minutes"], int)
    assert isinstance(data["forfeited_minutes"], int)
    assert isinstance(data["occupied_minutes"], int)
    assert is_iso8601_timestamp(data.get("release_deadline_at", "")), (
        "release_deadline_at must be ISO 8601 UTC"
    )
    assert data["status"] in [s.value for s in BlockStatus]


def assert_case_posting(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("surgeon_id", "")), "surgeon_id must be a UUID"
    assert data["procedure_class"] in [c.value for c in ProcedureClass]
    assert data["priority"] in [p.value for p in CasePriority]
    assert data["status"] in [s.value for s in CaseStatus]
    assert isinstance(data["benchmark_duration_minutes"], int)
    assert isinstance(data["predicted_duration_minutes"], int)
    if data.get("block_id") is not None:
        assert is_valid_uuid(data["block_id"]), "block_id must be a UUID when set"
    if data.get("scheduled_start_minute") is not None:
        assert isinstance(data["scheduled_start_minute"], int)
        assert isinstance(data["scheduled_end_minute"], int)
        assert data["scheduled_end_minute"] == (
            data["scheduled_start_minute"] + data["predicted_duration_minutes"]
        ), "scheduled_end_minute must equal start + predicted duration"


def assert_anesthesia_coverage(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("or_id", "")), "or_id must be a UUID"
    assert isinstance(data["date"], str) and len(data["date"]) == 10
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int) and data["end_minute"] > data["start_minute"]
    assert isinstance(data["provider_ref"], str)
    assert data["status"] in [s.value for s in CoverageStatus]


def assert_open_time_slot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("block_id", "")), "block_id must be a UUID"
    assert is_valid_uuid(data.get("or_id", "")), "or_id must be a UUID"
    assert isinstance(data["date"], str) and len(data["date"]) == 10
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["original_minutes"], int)
    assert isinstance(data["remaining_minutes"], int)
    assert isinstance(data["forfeited_minutes"], int)
    assert data["status"] in [s.value for s in SlotStatus]


def assert_reallocation_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("slot_id", "")), "slot_id must be a UUID"
    assert is_valid_uuid(data.get("surgeon_id", "")), "surgeon_id must be a UUID"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert isinstance(data["needed_minutes"], int)
    assert data["status"] in [s.value for s in RequestStatus]


def assert_utilization_report(data: dict):
    """UtilizationReport is an immutable snapshot: id + created_at only."""
    _assert_snapshot_fields(data)
    assert is_valid_uuid(data.get("service_line_id", "")), "service_line_id must be a UUID"
    assert isinstance(data["period_start"], str) and len(data["period_start"]) == 10
    assert isinstance(data["period_end"], str) and len(data["period_end"]) == 10
    assert isinstance(data["allocated_prime_minutes"], int)
    assert isinstance(data["occupied_prime_minutes"], int)
    assert isinstance(data["prime_time_utilization_pct"], (int, float))
    assert isinstance(data["raw_utilization_pct"], (int, float))


def assert_committee_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("service_line_id", "")), "service_line_id must be a UUID"
    assert is_valid_uuid(data.get("utilization_report_id", "")), (
        "utilization_report_id must be a UUID"
    )
    assert isinstance(data["period_end"], str) and len(data["period_end"]) == 10
    assert data["status"] in [s.value for s in ReviewStatus]
    assert data["decision"] in [d.value for d in ReviewDecision]
    assert isinstance(data["tally_reduce"], int)
    assert isinstance(data["tally_maintain"], int)
    assert isinstance(data["tally_abstain"], int)


def assert_committee_vote(data: dict):
    """CommitteeVote is append-only: id + created_at only."""
    _assert_snapshot_fields(data)
    assert is_valid_uuid(data.get("review_id", "")), "review_id must be a UUID"
    assert isinstance(data["member_ref"], str) and len(data["member_ref"]) > 0
    assert data["vote"] in [v.value for v in VoteValue]


def assert_room_minute_ledger(block: dict, slots: list):
    """Room-minute ledger: original == reserved + sum(slot originals) + forfeited.

    Applies while a block holds no separate occupancy accounting beyond the
    block-controlled span (reserved_minutes already contains occupied time).
    """
    derived = sum(s["original_minutes"] for s in slots)
    assert block["original_minutes"] == (
        block["reserved_minutes"] + derived + block["forfeited_minutes"]
    ), (
        f"Ledger broken: original {block['original_minutes']} != reserved "
        f"{block['reserved_minutes']} + slots {derived} + forfeited {block['forfeited_minutes']}"
    )
