"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version begins at 1"


def assert_game(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["game_type"] in ("JACKPOT", "INSTANT", "DAILY")
    assert isinstance(data["claim_window_days"], int) and data["claim_window_days"] >= 1
    assert data["status"] == "ACTIVE"


def assert_retailer(data: dict):
    _common(data)
    assert isinstance(data["business_name"], str) and len(data["business_name"]) > 0
    assert isinstance(data["tax_id"], str) and len(data["tax_id"]) > 0
    assert data["license_status"] in ("PENDING", "ACTIVE", "SUSPENDED", "REVOKED")
    assert isinstance(data["commission_balance_cents"], int)
    assert data["commission_balance_cents"] >= 0, "commission_balance_cents never goes negative"
    assert isinstance(data["lifetime_settled_cents"], int)
    assert data["lifetime_settled_cents"] >= 0


def assert_terminal(data: dict):
    _common(data)
    assert is_valid_uuid(data["retailer_id"])
    assert isinstance(data["serial_number"], str) and len(data["serial_number"]) > 0
    assert data["status"] in ("PROVISIONED", "ACTIVE", "DEACTIVATED")
    assert isinstance(data["tickets_sold_count"], int) and data["tickets_sold_count"] >= 0


def assert_player(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["self_exclusion_status"] in ("NONE", "EXCLUDED", "REINSTATED")


def assert_ticket(data: dict):
    _common(data)
    assert is_valid_uuid(data["game_id"])
    assert is_valid_uuid(data["terminal_id"])
    assert isinstance(data["serial"], str) and len(data["serial"]) > 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 1
    assert isinstance(data["declared_tier"], int) and 0 <= data["declared_tier"] <= 9
    assert isinstance(data["gross_prize_cents"], int) and data["gross_prize_cents"] >= 0
    assert data["validation_status"] in (
        "UNVALIDATED", "VALIDATED_WINNER", "VALIDATED_NONWINNER", "PAID_AT_COUNTER",
        "COUNTER_REVERSED", "CLAIM_PENDING", "REJECTED", "ESCHEATED",
    )
    assert data["second_chance_status"] in (
        "INELIGIBLE", "ELIGIBLE", "ENTERED", "DRAWN_WINNER", "DRAWN_LOSER",
    )
    assert is_iso8601_timestamp(data["claim_deadline"]), "claim_deadline must be ISO 8601"


def assert_prize_claim(data: dict):
    _common(data)
    assert is_valid_uuid(data["ticket_id"])
    assert is_valid_uuid(data["player_id"])
    assert data["payout_option"] in ("CASH", "ANNUITY")
    assert data["status"] in (
        "SUBMITTED", "ADJUDICATING", "APPROVED_CASH", "APPROVED_ANNUITY",
        "PAID", "REJECTED", "VOIDED",
    )
    for fld in ("gross_payout_cents", "federal_withholding_cents", "state_withholding_cents",
                "net_payout_cents", "annual_installment_cents"):
        assert isinstance(data[fld], int), f"{fld} must be int cents"


def assert_drawing(data: dict):
    _common(data)
    assert is_valid_uuid(data["game_id"])
    assert isinstance(data["prize_pool_cents"], int) and data["prize_pool_cents"] >= 1
    assert isinstance(data["entry_count"], int) and data["entry_count"] >= 0
    assert data["status"] in ("OPEN", "DRAWN", "CANCELLED")


def assert_entry(data: dict):
    _common(data)
    assert is_valid_uuid(data["drawing_id"])
    assert is_valid_uuid(data["ticket_id"])
    assert data["outcome"] in ("PENDING", "WON", "LOST")


def assert_settlement(data: dict):
    _common(data)
    assert is_valid_uuid(data["retailer_id"])
    assert data["status"] in ("DRAFT", "FINALIZED", "VOIDED")
    for fld in ("gross_commission_cents", "clawback_cents", "net_settlement_cents"):
        assert isinstance(data[fld], int), f"{fld} must be int cents"
    assert data["net_settlement_cents"] >= 0, "net_settlement_cents floored at 0"


def assert_escheat_record(data: dict):
    _common(data)
    assert is_valid_uuid(data["ticket_id"])
    assert isinstance(data["escheated_amount_cents"], int)
    assert is_iso8601_timestamp(data["escheated_at"])
