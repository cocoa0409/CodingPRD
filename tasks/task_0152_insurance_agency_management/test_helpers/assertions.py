"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) validates field presence, types, and value sets for a
resource as described in the PRD. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CARRIER_STATUSES = ["PROSPECTIVE", "ACTIVE", "SUSPENDED", "TERMINATED"]
LINES_OF_BUSINESS = ["AUTO", "HOME", "GL", "WC", "UMBRELLA"]
CANCELLATION_BASES = ["PRO_RATA", "SHORT_RATE"]
PRODUCER_STATUSES = ["ACTIVE", "INACTIVE"]
LICENSE_STATUSES = ["ACTIVE", "EXPIRED", "PENDING"]
APPOINTMENT_STATUSES = ["REQUESTED", "APPROVED", "ACTIVE", "TERMINATED"]
ACCOUNT_TYPES = ["PERSONAL", "COMMERCIAL"]
POLICY_STATUSES = [
    "QUOTED", "BOUND", "ACTIVE", "PENDING_RENEWAL",
    "CANCELLED", "EXPIRED", "REINSTATED", "NON_RENEWED",
]
TERM_KINDS = ["NEW_BUSINESS", "RENEWAL"]
CANCELLATION_REASONS = ["INSURED_REQUEST", "NON_PAYMENT", "UNDERWRITING"]
DOWNLOAD_SOURCES = ["MANUAL", "ACORD_DOWNLOAD"]
SPLIT_ROLES = ["WRITING", "SERVICING", "OVERRIDE"]
SPLIT_STATUSES = ["DRAFT", "LOCKED"]
LEDGER_ENTRY_TYPES = [
    "PREMIUM_RECEIPT", "CARRIER_REMITTANCE", "COMMISSION_DISBURSEMENT",
    "RETURN_PREMIUM_REFUND", "OPENING_BALANCE",
]
STATEMENT_STATUSES = ["OPEN", "FINALIZED", "PAID"]
RENEWAL_STAGES = ["IDENTIFIED", "REVIEW", "QUOTED", "OFFERED", "COMPLETED", "LOST"]


def _assert_common_quartet(data: dict):
    """id, created_at, updated_at, version (PRD §2.4 full-quartet entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_carrier(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["naic_code"], str)
    assert data["status"] in CARRIER_STATUSES, f"bad carrier status {data['status']}"
    assert isinstance(data["download_supported"], bool)
    assert isinstance(data["default_new_business_commission_pct"], (int, float))
    assert isinstance(data["default_renewal_commission_pct"], (int, float))


def assert_product(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["carrier_id"])
    assert data["line_of_business"] in LINES_OF_BUSINESS
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["cancellation_basis"] in CANCELLATION_BASES


def assert_producer(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["npn"], str) and len(data["npn"]) > 0
    assert data["status"] in PRODUCER_STATUSES
    assert isinstance(data["default_split_pct"], (int, float))


def assert_license(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["producer_id"])
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["line_of_business"] in LINES_OF_BUSINESS
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expiration_date"])
    assert data["status"] in LICENSE_STATUSES, f"bad license status {data['status']}"


def assert_appointment(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["carrier_id"])
    assert is_valid_uuid(data["producer_id"])
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["status"] in APPOINTMENT_STATUSES


def assert_account(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_valid_uuid(data["servicing_producer_id"])
    assert data["account_type"] in ACCOUNT_TYPES
    assert isinstance(data["active_policy_count"], int)
    assert data["active_policy_count"] >= 0


def assert_policy(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["writing_producer_id"])
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["annual_premium_cents"], int)
    assert data["annual_premium_cents"] > 0
    assert is_iso8601_timestamp(data["effective_date"])
    assert is_iso8601_timestamp(data["expiration_date"])
    assert data["term_kind"] in TERM_KINDS
    assert data["status"] in POLICY_STATUSES
    assert isinstance(data["return_premium_cents"], int)
    assert isinstance(data["earned_premium_cents"], int)
    assert data["download_source"] in DOWNLOAD_SOURCES


def assert_commission_split(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["policy_id"])
    assert is_valid_uuid(data["producer_id"])
    assert isinstance(data["split_pct"], (int, float))
    assert 0 < data["split_pct"] <= 1
    assert data["role"] in SPLIT_ROLES
    assert data["status"] in SPLIT_STATUSES


def assert_trust_account(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["minimum_balance_cents"], int)
    assert data["minimum_balance_cents"] >= 0


def assert_trust_ledger_entry(data: dict):
    """TrustLedgerEntry is leaner: only id + created_at (PRD §2.4) — no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "TrustLedgerEntry must not carry updated_at"
    assert "version" not in data, "TrustLedgerEntry must not carry version"
    assert is_valid_uuid(data["trust_account_id"])
    assert data["entry_type"] in LEDGER_ENTRY_TYPES
    assert isinstance(data["amount_cents"], int)


def assert_commission_statement(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["producer_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert isinstance(data["gross_commission_cents"], int)
    assert isinstance(data["chargeback_cents"], int)
    assert isinstance(data["net_payable_cents"], int)
    assert data["status"] in STATEMENT_STATUSES


def assert_renewal_task(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["policy_id"])
    assert data["stage"] in RENEWAL_STAGES
    assert is_iso8601_timestamp(data["target_effective_date"])
    assert isinstance(data["requote_count"], int)
    assert data["requote_count"] >= 0


def assert_trust_balance_is_sum(balance_cents: int, expected_sum: int):
    """Derived-field reconciliation invariant (PRD §2.6): balance_cents equals the
    sum of posted ledger amounts."""
    assert balance_cents == expected_sum, (
        f"trust balance_cents {balance_cents} must equal posted-entry sum {expected_sum}"
    )


def assert_return_earned_split(policy: dict):
    """PRD §3.6: earned_premium_cents == annual_premium_cents - return_premium_cents."""
    assert (
        policy["earned_premium_cents"]
        == policy["annual_premium_cents"] - policy["return_premium_cents"]
    ), "earned_premium_cents must equal annual_premium_cents - return_premium_cents"
