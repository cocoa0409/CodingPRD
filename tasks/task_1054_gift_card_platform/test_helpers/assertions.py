"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure and field domains from
the PRD contract. Uses the framework's generic format validators internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_MERCHANT_STATUSES = ["PENDING", "ACTIVE", "SUSPENDED", "CLOSED"]
_PROGRAM_STATUSES = ["DRAFT", "ACTIVE", "PAUSED", "RETIRED"]
_CAMPAIGN_STATUSES = ["SCHEDULED", "RUNNING", "ENDED"]
_BATCH_STATUSES = ["DRAFT", "COMMITTED", "CANCELLED"]
_CARD_STATUSES = ["INACTIVE", "ACTIVE", "SUSPENDED", "EXPIRED", "ESCHEATED", "CLOSED"]
_HOLD_STATUSES = ["OPEN", "CLEARED", "CONFIRMED"]
_SETTLEMENT_STATUSES = ["OPEN", "FINALIZED", "CANCELLED"]
_ESCHEAT_STATUSES = ["DRAFT", "REMITTED"]
_LEDGER_TYPES = ["ACTIVATION_LOAD", "RELOAD", "INCENTIVE_BONUS", "REDEMPTION",
                 "DORMANCY_FEE", "BREAKAGE", "ESCHEAT_REMIT"]
_LEDGER_STATUSES = ["POSTED", "REVERSED"]


def _assert_common(data: dict):
    """id/created_at/updated_at/version present for standard resources (§2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_merchant(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["settlement_currency"], str) and data["settlement_currency"]
    assert data["status"] in _MERCHANT_STATUSES
    assert isinstance(data["unsettled_redemptions_cents"], int)
    assert isinstance(data["lifetime_net_payout_cents"], int)


def assert_card_program(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["merchant_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["breakage_method"] in ["ESTIMATED", "REMITTANCE"]
    assert data["status"] in _PROGRAM_STATUSES
    assert isinstance(data["expiry_months"], int) and data["expiry_months"] >= 1
    assert isinstance(data["max_balance_cents"], int)
    assert isinstance(data["min_load_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert isinstance(data["breakage_recognized_cents"], int)


def assert_incentive_campaign(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["card_program_id"])
    assert isinstance(data["bonus_bps"], int) and data["bonus_bps"] >= 0
    assert data["status"] in _CAMPAIGN_STATUSES


def assert_card_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["card_program_id"])
    assert data["channel"] in ["DIGITAL", "PHYSICAL"]
    assert isinstance(data["card_count"], int) and data["card_count"] >= 1
    assert isinstance(data["unit_load_cents"], int)
    assert data["status"] in _BATCH_STATUSES


def assert_gift_card(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["card_program_id"])
    assert is_valid_uuid(data["card_batch_id"])
    assert isinstance(data["card_number"], str) and data["card_number"]
    assert data["channel"] in ["DIGITAL", "PHYSICAL"]
    assert data["status"] in _CARD_STATUSES
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["initial_load_cents"], int)


def assert_fraud_hold(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["gift_card_id"])
    assert data["reason"] in ["VELOCITY", "MANUAL", "CHARGEBACK"]
    assert data["status"] in _HOLD_STATUSES
    assert isinstance(data["reversed_redemption_count"], int)


def assert_velocity_rule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["card_program_id"])
    assert isinstance(data["window_hours"], int) and data["window_hours"] >= 1
    assert isinstance(data["max_count"], int)
    assert isinstance(data["max_amount_cents"], int)
    assert isinstance(data["enabled"], bool)


def assert_settlement_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["merchant_id"])
    assert data["status"] in _SETTLEMENT_STATUSES
    assert isinstance(data["gross_redemptions_cents"], int)
    assert isinstance(data["interchange_fee_cents"], int)
    assert isinstance(data["net_payout_cents"], int)
    assert isinstance(data["provisional_net_payout_cents"], int)


def assert_escheat_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["merchant_id"])
    assert isinstance(data["jurisdiction"], str) and data["jurisdiction"]
    assert data["status"] in _ESCHEAT_STATUSES
    assert isinstance(data["escheat_total_cents"], int)
    assert isinstance(data["card_count"], int)


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only: id + created_at only, no updated_at/version (§2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only LedgerEntry must not carry updated_at"
    assert "version" not in data, "append-only LedgerEntry must not carry version"
    assert is_valid_uuid(data["gift_card_id"])
    assert data["entry_type"] in _LEDGER_TYPES
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in _LEDGER_STATUSES
