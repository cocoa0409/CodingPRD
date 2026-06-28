"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    _assert_common(data)
    assert data["program_phase"] in ("ENROLLING", "ACTIVE", "COMPLETED", "TERMINATED")
    assert data["account_standing"] in ("CURRENT", "DELINQUENT", "DEFAULTED")
    assert isinstance(data["target_settlement_pct"], (int, float))
    assert isinstance(data["monthly_deposit_amount"], (int, float))


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["refunded_to_client_cents"], int)


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["balance"], (int, float))
    assert isinstance(data["lifetime_deposited"], (int, float))


def assert_debt(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "IN_NEGOTIATION", "LAWSUIT", "SETTLED", "WITHDRAWN")
    assert isinstance(data["original_balance"], (int, float))
    assert isinstance(data["fee_rate_pct"], (int, float))


def assert_offer(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACCEPTED", "REJECTED", "EXPIRED")
    assert isinstance(data["settlement_amount"], (int, float))
    assert isinstance(data["projected_fee"], (int, float))


def assert_settlement(data: dict):
    _assert_common(data)
    assert data["status"] in ("FUNDED", "COMPLETED", "VOIDED")
    assert isinstance(data["funded_amount"], (int, float))


def assert_tax_event(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "VOIDED")
    assert isinstance(data["reportable"], bool)
    assert isinstance(data["forgiven_amount"], (int, float))
