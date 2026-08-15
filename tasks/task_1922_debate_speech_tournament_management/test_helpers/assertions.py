"""Entity assertions and domain invariant checkers (PRD §2.4 field contracts)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BallotStatus,
    ContractStatus,
    DivisionLevel,
    EntryStatus,
    EventType,
    FinalPlacement,
    JudgeStatus,
    JudgeType,
    ObligationStatus,
    OrderKind,
    OrderStatus,
    PairingFormat,
    PairingSide,
    PairingStatus,
    ResultsVisibility,
    RoundKind,
    RoundStatus,
    SchoolStatus,
    TournamentStatus,
)


def _assert_common_fields(data, label):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be a positive integer"


def _assert_light_fields(data, label):
    """For the two light resources: only id and created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_tournament(data):
    _assert_common_fields(data, "Tournament")
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in [s.value for s in TournamentStatus]
    assert data["results_visibility"] in [s.value for s in ResultsVisibility]
    assert isinstance(data["prelim_round_count"], int)
    assert 2 <= data["prelim_round_count"] <= 6
    assert isinstance(data["entry_fee_cents"], int) and data["entry_fee_cents"] >= 0
    assert isinstance(data["tournament_staff_count"], int)
    assert data["tournament_staff_count"] >= 0
    assert isinstance(data["late_fee_surcharge_pct"], (int, float))


def assert_school(data):
    _assert_common_fields(data, "School")
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in [s.value for s in SchoolStatus]
    assert isinstance(data["confirmed_entry_count"], int)
    assert isinstance(data["judge_obligation_rounds"], int)
    assert isinstance(data["covered_judge_rounds"], int)
    assert isinstance(data["shortfall_rounds"], int)
    assert data["obligation_status"] in [s.value for s in ObligationStatus]
    assert isinstance(data["invoice_balance_cents"], int)


def assert_school_invariants(data):
    """Derived-field invariants that must hold on any school read (PRD §3.2)."""
    assert data["shortfall_rounds"] == max(
        0, data["judge_obligation_rounds"] - data["covered_judge_rounds"]
    ), "shortfall_rounds is the uncovered remainder, never below zero"
    expected = "SATISFIED" if data["shortfall_rounds"] == 0 else "DEFICIENT"
    assert data["obligation_status"] == expected, (
        f"obligation_status SATISFIED exactly when shortfall is zero; got "
        f"{data['obligation_status']} with shortfall {data['shortfall_rounds']}"
    )


def assert_division(data):
    _assert_common_fields(data, "EventDivision")
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert data["event_type"] in [s.value for s in EventType]
    assert isinstance(data["event_code"], str) and data["event_code"]
    assert data["division"] in [s.value for s in DivisionLevel]
    assert isinstance(data["per_school_entry_cap"], int)
    assert data["per_school_entry_cap"] >= 1
    assert isinstance(data["global_entry_cap"], int) and data["global_entry_cap"] >= 1
    assert isinstance(data["competing_entry_count"], int)


def assert_entry(data):
    _assert_common_fields(data, "Entry")
    assert is_valid_uuid(data.get("school_id", ""))
    assert is_valid_uuid(data.get("division_id", ""))
    assert isinstance(data["competitor_name"], str) and data["competitor_name"]
    assert data["status"] in [s.value for s in EntryStatus]
    for field in ("wins", "losses", "speaker_points_raw", "speaker_points_adjusted",
                  "rank_points_raw", "rank_points_adjusted", "opponent_strength",
                  "fee_charged_cents"):
        assert isinstance(data[field], int), f"Entry.{field} must be an integer"
    assert isinstance(data["has_received_bye"], bool)
    if data["final_placement"] is not None:
        assert data["final_placement"] in [s.value for s in FinalPlacement]


def assert_judge(data):
    _assert_common_fields(data, "Judge")
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert data["judge_type"] in [s.value for s in JudgeType]
    assert data["status"] in [s.value for s in JudgeStatus]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["commitment_rounds"], int)
    assert isinstance(data["assigned_round_count"], int)
    if data["judge_type"] == "HIRED":
        assert data["school_id"] is None, "HIRED judges carry no school affiliation"


def assert_judge_conflict(data):
    _assert_light_fields(data, "JudgeConflict")
    assert is_valid_uuid(data.get("judge_id", ""))
    assert is_valid_uuid(data.get("school_id", ""))


def assert_room(data):
    _assert_common_fields(data, "Room")
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_round(data):
    _assert_common_fields(data, "Round")
    assert is_valid_uuid(data.get("division_id", ""))
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert data["kind"] in [s.value for s in RoundKind]
    assert data["status"] in [s.value for s in RoundStatus]
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert isinstance(data["pairings_total"], int)
    assert isinstance(data["pairings_verified_count"], int)


def assert_pairing(data):
    _assert_common_fields(data, "Pairing")
    assert is_valid_uuid(data.get("round_id", ""))
    assert data["format"] in [s.value for s in PairingFormat]
    assert data["status"] in [s.value for s in PairingStatus]
    assert isinstance(data["is_bye"], bool)


def assert_pairing_entry(data):
    _assert_light_fields(data, "PairingEntry")
    assert is_valid_uuid(data.get("pairing_id", ""))
    assert is_valid_uuid(data.get("entry_id", ""))
    assert data["side"] in [s.value for s in PairingSide]
    assert isinstance(data["draw_position"], int) and data["draw_position"] >= 1


def assert_ballot(data):
    _assert_common_fields(data, "Ballot")
    assert is_valid_uuid(data.get("pairing_id", ""))
    assert is_valid_uuid(data.get("judge_id", ""))
    assert data["status"] in [s.value for s in BallotStatus]
    assert isinstance(data["allow_low_point_win"], bool)


def assert_contract(data):
    _assert_common_fields(data, "HiredJudgeContract")
    assert is_valid_uuid(data.get("school_id", ""))
    assert data["status"] in [s.value for s in ContractStatus]
    assert isinstance(data["rounds_requested"], int) and data["rounds_requested"] >= 1
    assert isinstance(data["rounds_released"], int) and data["rounds_released"] >= 0
    assert isinstance(data["fee_quote_cents"], int)


def assert_contract_invariants(data):
    """rounds_active is always rounds_requested minus rounds_released (PRD §3.3)."""
    assert data["rounds_active"] == data["rounds_requested"] - data["rounds_released"]
    assert data["rounds_active"] >= 0, "active rounds never fall below zero"


def assert_order(data):
    _assert_common_fields(data, "LogisticsOrder")
    assert is_valid_uuid(data.get("tournament_id", ""))
    assert data["kind"] in [s.value for s in OrderKind]
    assert data["status"] in [s.value for s in OrderStatus]
    assert isinstance(data["headcount_demand"], int)
    assert isinstance(data["meal_count"], int)
    assert isinstance(data["awards_count"], int)
