"""Entity assertions and domain invariant checkers.

Each assert_<entity>() validates the envelope fields the PRD guarantees:
the four system-managed common fields plus the entity's declared fields'
types and enum memberships. Value-level expectations live in the tests.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CategoryStatus,
    ContestStatus,
    EntryStatus,
    GreenRoomBookingStatus,
    PerformanceSlotStatus,
    PreJudgingSlotStatus,
    PrizeAwardStatus,
    SafetyStatus,
    ScoreSheetStatus,
)


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be a positive integer"
    )


def assert_contest_event(data: dict):
    _assert_common_fields(data, "ContestEvent")
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["prize_budget_cents"], int) and data["prize_budget_cents"] >= 0
    assert isinstance(data["max_entries_per_contestant"], int)
    assert data["max_entries_per_contestant"] >= 1
    assert data["status"] in [s.value for s in ContestStatus]
    assert isinstance(data["budget_reserved_cents"], int)
    assert isinstance(data["budget_available_cents"], int)


def assert_budget_invariant(contest: dict):
    """PRD: prize_budget_cents == budget_reserved_cents + budget_available_cents."""
    assert contest["prize_budget_cents"] == (
        contest["budget_reserved_cents"] + contest["budget_available_cents"]
    ), (
        f"Budget invariant broken: {contest['prize_budget_cents']} != "
        f"{contest['budget_reserved_cents']} + {contest['budget_available_cents']}"
    )


def assert_category(data: dict):
    _assert_common_fields(data, "Category")
    assert is_valid_uuid(data.get("contest_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert data["skill_division"] in ["JUNIOR", "NOVICE", "JOURNEYMAN", "MASTERS"]
    assert isinstance(data["max_entries"], int) and data["max_entries"] >= 1
    assert data["tabulation_method"] in ["WEIGHTED_MEAN", "TRIMMED_MEAN"]
    assert isinstance(data["prize_purse_cents"], int) and data["prize_purse_cents"] >= 0
    assert data["status"] in [s.value for s in CategoryStatus]
    assert isinstance(data["entry_count"], int) and data["entry_count"] >= 0
    for field in ("prize_rank1_cents", "prize_rank2_cents", "prize_rank3_cents"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_purse_split_conserves(category: dict):
    """PRD: rank3 is the remainder so the three ranks always sum to the purse."""
    total = (
        category["prize_rank1_cents"]
        + category["prize_rank2_cents"]
        + category["prize_rank3_cents"]
    )
    assert total == category["prize_purse_cents"], (
        f"Purse split {total} does not sum to purse {category['prize_purse_cents']}"
    )


def assert_contestant(data: dict):
    _assert_common_fields(data, "Contestant")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["birth_date"], str) and len(data["birth_date"]) == 10
    assert isinstance(data["accessibility_needs"], list)
    assert isinstance(data["consents"], list)
    for item in data["consents"]:
        assert item["scope"] in ["PHOTOGRAPHY", "VIDEO", "LIVESTREAM"]
        assert item["status"] in ["GRANTED", "REVOKED"]


def assert_judge(data: dict):
    _assert_common_fields(data, "Judge")
    assert is_valid_uuid(data.get("contest_id", ""))
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["category_ids"], list) and len(data["category_ids"]) >= 1
    assert "linked_contestant_id" in data


def assert_entry(data: dict):
    _assert_common_fields(data, "Entry")
    assert is_valid_uuid(data.get("contestant_id", ""))
    assert is_valid_uuid(data.get("category_id", ""))
    assert is_valid_uuid(data.get("contest_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["prop_declarations"], list)
    assert isinstance(data["requires_prejudging"], bool)
    assert data["status"] in [s.value for s in EntryStatus]
    assert data["safety_status"] in [s.value for s in SafetyStatus]
    assert isinstance(data["rejected_props"], list)
    assert data["placement_rank"] is None or isinstance(data["placement_rank"], int)
    assert data["final_score"] is None or isinstance(data["final_score"], (int, float))
    assert data["craftsmanship_mean"] is None or isinstance(
        data["craftsmanship_mean"], (int, float)
    )


def assert_prejudging_slot(data: dict):
    _assert_common_fields(data, "PreJudgingSlot")
    assert is_valid_uuid(data.get("category_id", ""))
    assert isinstance(data["panel_name"], str) and data["panel_name"]
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in [s.value for s in PreJudgingSlotStatus]
    assert data["booked_entry_id"] is None or is_valid_uuid(data["booked_entry_id"])


def assert_scoresheet(data: dict):
    _assert_common_fields(data, "ScoreSheet")
    assert is_valid_uuid(data.get("entry_id", ""))
    assert is_valid_uuid(data.get("judge_id", ""))
    assert is_valid_uuid(data.get("category_id", ""))
    assert data["phase"] in ["CRAFTSMANSHIP", "STAGE"]
    for criterion in ("craftsmanship", "accuracy", "presentation"):
        assert isinstance(data[criterion], int), f"{criterion} must be int"
        assert 0 <= data[criterion] <= 10, f"{criterion} must be within 0..10"
    assert isinstance(data["sheet_total"], (int, float))
    assert data["status"] in [s.value for s in ScoreSheetStatus]


def assert_performance_slot(data: dict):
    _assert_common_fields(data, "PerformanceSlot")
    assert is_valid_uuid(data.get("entry_id", ""))
    assert is_valid_uuid(data.get("contest_id", ""))
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert isinstance(data["duration_seconds"], int) and data["duration_seconds"] >= 1
    assert data["status"] in [s.value for s in PerformanceSlotStatus]


def assert_prize_award(data: dict):
    _assert_common_fields(data, "PrizeAward")
    assert is_valid_uuid(data.get("category_id", ""))
    assert is_valid_uuid(data.get("contest_id", ""))
    assert data["rank"] in (1, 2, 3)
    assert is_valid_uuid(data.get("entry_id", ""))
    assert isinstance(data["value_cents"], int) and data["value_cents"] >= 0
    assert isinstance(data["tax_reportable"], bool)
    assert data["status"] in [s.value for s in PrizeAwardStatus]
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["approved_by_user_id"] is None or isinstance(
        data["approved_by_user_id"], str
    )
    assert data["withheld_cents"] is None or isinstance(data["withheld_cents"], int)
    assert data["net_payout_cents"] is None or isinstance(data["net_payout_cents"], int)


def assert_green_room_booking(data: dict):
    _assert_common_fields(data, "GreenRoomBooking")
    assert is_valid_uuid(data.get("contestant_id", ""))
    assert is_valid_uuid(data.get("contest_id", ""))
    assert data["room_name"] in ["NORTH", "SOUTH", "EAST"]
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["requires_accessibility_setup"], bool)
    assert data["status"] in [s.value for s in GreenRoomBookingStatus]
