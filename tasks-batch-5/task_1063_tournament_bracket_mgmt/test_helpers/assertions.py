"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_venue(data: dict):
    _common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["open_minute"], int)
    assert isinstance(data["close_minute"], int)


def assert_station(data: dict):
    _common(data)
    assert is_valid_uuid(data["venue_id"])
    assert isinstance(data["label"], str)


def assert_stream_channel(data: dict):
    _common(data)
    assert data["platform"] in {"TWITCH", "YOUTUBE", "FACEBOOK"}


def assert_player(data: dict):
    _common(data)
    assert isinstance(data["display_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["rating"], int)
    assert isinstance(data["tax_id_provided"], bool)


def assert_tournament(data: dict):
    _common(data)
    assert data["status"] in {
        "DRAFT", "REGISTRATION_OPEN", "REGISTRATION_CLOSED", "BRACKET_READY",
        "IN_PROGRESS", "COMPLETED", "CANCELLED",
    }
    assert data["format"] in {"SINGLE_ELIM", "DOUBLE_ELIM", "ROUND_ROBIN", "SWISS"}
    assert isinstance(data["prize_pool_cents"], int)
    assert isinstance(data["paid_places"], int)


def assert_registration(data: dict):
    _common(data)
    assert data["status"] in {
        "REGISTERED", "CHECKED_IN", "WITHDRAWN", "ELIMINATED", "CHAMPION",
    }
    assert is_valid_uuid(data["tournament_id"])
    assert is_valid_uuid(data["player_id"])


def assert_match(data: dict):
    _common(data)
    assert data["status"] in {
        "PENDING", "SCHEDULED", "REPORTED", "CONFIRMED", "DISPUTED", "VOIDED",
    }
    assert is_valid_uuid(data["tournament_id"])


def assert_payout(data: dict):
    _common(data)
    assert data["variant"] in {"PROVISIONAL", "FINAL"}
    assert data["status"] in {"PENDING", "PAID", "VOID"}
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["tax_withheld_cents"], int)
    assert isinstance(data["net_amount_cents"], int)
    assert data["net_amount_cents"] == data["gross_amount_cents"] - data["tax_withheld_cents"]


def assert_dispute(data: dict):
    _common(data)
    assert data["status"] in {"OPEN", "UPHELD", "REJECTED"}
    assert is_valid_uuid(data["match_id"])


def assert_stream_assignment(data: dict):
    _common(data)
    assert data["status"] in {"SCHEDULED", "CANCELLED"}


def assert_money_conservation(tournament: dict, payouts: list):
    """PRD §2.8: sum(non-VOID gross) + unallocated_prize_cents == prize_pool_cents."""
    non_void = sum(p["gross_amount_cents"] for p in payouts if p["status"] != "VOID")
    total = non_void + tournament["unallocated_prize_cents"]
    assert total == tournament["prize_pool_cents"], (
        f"money conservation broken: {non_void} + {tournament['unallocated_prize_cents']} "
        f"!= {tournament['prize_pool_cents']}"
    )


def assert_participant_conservation(tournament: dict):
    """PRD §2.9: alive_count + eliminated_count == checked_in_count."""
    assert (
        tournament["alive_count"] + tournament["eliminated_count"]
        == tournament["checked_in_count"]
    ), (
        f"participant conservation broken: {tournament['alive_count']} + "
        f"{tournament['eliminated_count']} != {tournament['checked_in_count']}"
    )
