"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

PROGRAM_STATUSES = ["DRAFT", "ACTIVE", "BUDGET_LOCKED", "CLOSED"]
OFFER_STATUSES = ["DRAFT", "PUBLISHED", "SUSPENDED", "CLOSED"]
CLAIMANT_STATUSES = ["ACTIVE", "BLOCKED"]
ADJUDICATION_STATUSES = [
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "HELD",
    "APPROVED", "DENIED", "REVOKED", "WITHDRAWN", "VOIDED",
]
PAYMENT_STATUSES = ["NONE", "SCHEDULED", "PAID", "ESCHEATED"]
PAYOUT_STATUSES = ["PENDING", "RELEASED", "REISSUE_PENDING", "CLEARED", "VOIDED", "ESCHEATED"]
CARD_STATUSES = ["ISSUED", "ACTIVATED", "PARTIALLY_USED", "EXHAUSTED", "ESCHEATED"]
FRAUD_CASE_STATUSES = ["OPEN", "UNDER_INVESTIGATION", "PENDING_INFO", "SUBSTANTIATED", "CLEARED"]
ENTRY_TYPES = [
    "ACCRUAL", "COMMIT", "RELEASE", "PAYMENT", "ESCHEAT_REVERSAL", "BUDGET_ADJUSTMENT",
]


def _assert_common_fields(data: dict, label: str):
    """id + created_at + updated_at + version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer starting at 1"
    )


def _assert_append_only_fields(data: dict, label: str):
    """id + created_at only — no updated_at, no version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"


def assert_program(data: dict):
    _assert_common_fields(data, "Program")
    assert data["status"] in PROGRAM_STATUSES, f"Unexpected program status {data['status']}"
    assert isinstance(data["budget_total_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert isinstance(data["reserve_cents"], int)
    assert isinstance(data["utilization_pct"], (int, float))
    assert isinstance(data["fiscal_year"], int)


def assert_offer(data: dict):
    _assert_common_fields(data, "Offer")
    assert data["status"] in OFFER_STATUSES, f"Unexpected offer status {data['status']}"
    assert data["channel"] in ["DEALER", "CONSUMER", "BOTH"]
    assert isinstance(data["max_rebate_cents_per_claim"], int)
    assert isinstance(data["active_claim_count"], int)
    assert isinstance(data["dealer_tier_enabled"], bool)


def assert_claimant(data: dict):
    _assert_common_fields(data, "Claimant")
    assert data["status"] in CLAIMANT_STATUSES
    assert data["type"] in ["DEALER", "CONSUMER"]
    assert isinstance(data["fraud_score"], int)
    assert 0 <= data["fraud_score"] <= 100, "fraud_score must be an integer between 0 and 100"
    assert isinstance(data["denied_claim_count"], int)
    assert isinstance(data["open_claim_count"], int)
    assert isinstance(data["duplicate_attempt_count"], int)


def assert_claim(data: dict):
    _assert_common_fields(data, "Claim")
    assert data["adjudication_status"] in ADJUDICATION_STATUSES
    assert data["payment_status"] in PAYMENT_STATUSES
    assert isinstance(data["provisional_rebate_cents"], int)
    assert isinstance(data["total_units"], int)
    assert isinstance(data["appeal_count"], int)


def assert_receipt(data: dict):
    _assert_common_fields(data, "Receipt")
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert data["line_count"] == len(data["lines"]), "line_count must equal the number of lines"
    assert data["units"] == sum(line["quantity"] for line in data["lines"])
    assert data["gross_amount_cents"] == sum(
        line["quantity"] * line["unit_price_cents"] for line in data["lines"]
    )
    assert isinstance(data["validated"], bool)


def assert_payout(data: dict):
    _assert_common_fields(data, "Payout")
    assert data["status"] in PAYOUT_STATUSES
    assert data["method"] in ["CHECK", "VIRTUAL_CARD"]
    assert data["net_cents"] == data["gross_cents"] - data["fee_cents"], (
        "net_cents must be gross_cents less fee_cents"
    )
    assert isinstance(data["reissue_count"], int)


def assert_virtual_card(data: dict):
    _assert_common_fields(data, "VirtualCard")
    assert data["status"] in CARD_STATUSES
    assert isinstance(data["initial_balance_cents"], int)
    assert isinstance(data["remaining_balance_cents"], int)
    assert 0 <= data["remaining_balance_cents"] <= data["initial_balance_cents"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["last_activity_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_fraud_case(data: dict):
    _assert_common_fields(data, "FraudCase")
    assert data["status"] in FRAUD_CASE_STATUSES
    assert data["opened_by"] in ["SYSTEM_AUTO", "ANALYST"]
    assert isinstance(data["heuristic_score_at_open"], int)
    assert isinstance(data["info_request_count"], int)


def assert_budget_entry(data: dict):
    _assert_append_only_fields(data, "BudgetEntry")
    assert data["entry_type"] in ENTRY_TYPES
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] > 0, "ledger amounts are always written as a positive number"
    assert isinstance(data["committed_after_cents"], int)


def assert_escheat_record(data: dict):
    _assert_append_only_fields(data, "EscheatRecord")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["dormancy_days"], int)
    assert isinstance(data["jurisdiction"], str) and data["jurisdiction"]
    assert is_iso8601_timestamp(data["swept_at"])


# --------------------------------------------------------------------------- #
# Domain invariants
# --------------------------------------------------------------------------- #

def assert_budget_position_consistent(program: dict):
    """available_cents is budget_total_cents less committed_cents less reserve_cents."""
    assert program["available_cents"] == (
        program["budget_total_cents"] - program["committed_cents"] - program["reserve_cents"]
    ), "available_cents must equal budget_total_cents - committed_cents - reserve_cents"


def entries_of_type(entries, entry_type: str):
    return [e for e in entries if e["entry_type"] == entry_type]
