"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally (is_valid_uuid,
is_iso8601_timestamp). Durable entities carry id/created_at/updated_at/version;
DunningNotice and CashForecast carry only id/created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CREDIT_STATUSES = ["GOOD", "WATCH", "HOLD"]
COLLECTION_STAGES = ["CURRENT", "DUNNING", "COLLECTIONS", "WRITEOFF"]
INVOICE_STATUSES = ["OPEN", "PARTIAL", "DISPUTED", "PAID", "WRITTEN_OFF"]
AGING_BUCKETS = ["CURRENT", "B1_30", "B31_60", "B61_90", "B91_PLUS"]
PAYMENT_STATUSES = ["UNAPPLIED", "PARTIALLY_APPLIED", "FULLY_APPLIED"]
DISPUTE_STATUSES = ["OPEN", "UNDER_REVIEW", "RESOLVED_CREDIT", "REJECTED", "WITHDRAWN"]
PROMISE_STATUSES = ["ACTIVE", "KEPT", "BROKEN", "CANCELLED"]
PAUSE_STATUSES = ["SCHEDULED", "ACTIVE", "EXPIRED"]
CURRENCIES = ["USD", "EUR", "GBP"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_light(data: dict):
    """Lighter records: only id + created_at, no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at ISO 8601"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["currency"] in CURRENCIES
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert data["credit_status"] in CREDIT_STATUSES
    assert data["collection_stage"] in COLLECTION_STAGES
    assert isinstance(data["exposure_cents"], int)
    assert isinstance(data["total_open_balance_cents"], int)
    assert isinstance(data["bad_debt_total_cents"], int) and data["bad_debt_total_cents"] >= 0
    assert isinstance(data["manual_hold"], bool)


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["face_amount_cents"], int) and data["face_amount_cents"] >= 1
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["disputed_amount_cents"], int)
    assert data["status"] in INVOICE_STATUSES
    assert data["aging_bucket"] in AGING_BUCKETS
    assert isinstance(data["dunning_stage_index"], int)


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["applied_cents"], int)
    assert isinstance(data["unapplied_cents"], int)
    assert data["status"] in PAYMENT_STATUSES
    # Conserved split: applied + unapplied == amount.
    assert data["applied_cents"] + data["unapplied_cents"] == data["amount_cents"], (
        "applied_cents + unapplied_cents must equal amount_cents"
    )


def assert_payment_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["payment_id"])
    assert is_valid_uuid(data["invoice_id"])
    assert isinstance(data["applied_cents"], int) and data["applied_cents"] >= 1
    assert isinstance(data["short_pay_cents"], int)
    assert isinstance(data["reversed"], bool)


def assert_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["invoice_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["reason_code"] in ["PRICING", "SHORTAGE", "DAMAGE", "DUPLICATE", "QUALITY"]
    assert data["status"] in DISPUTE_STATUSES
    assert isinstance(data["resolution_credit_cents"], int)
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0


def assert_promise(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["promised_amount_cents"], int) and data["promised_amount_cents"] >= 1
    assert data["status"] in PROMISE_STATUSES
    assert isinstance(data["applied_payment_cents"], int)


def assert_write_off(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["invoice_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["reason_code"] in ["UNCOLLECTIBLE", "SETTLEMENT", "BANKRUPTCY", "SMALL_BALANCE"]
    assert isinstance(data["approved"], bool)


def assert_dunning_sequence(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["active"], bool)
    assert isinstance(data["steps"], list) and len(data["steps"]) >= 1


def assert_dunning_pause(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["status"] in PAUSE_STATUSES


def assert_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["opening_balance_cents"], int)
    assert isinstance(data["new_charges_cents"], int)
    assert isinstance(data["finance_charge_cents"], int)
    assert isinstance(data["closing_balance_cents"], int)


def assert_dunning_notice(data: dict):
    _assert_light(data)
    assert is_valid_uuid(data["invoice_id"])
    assert is_valid_uuid(data["sequence_id"])
    assert isinstance(data["step_index"], int) and data["step_index"] >= 1
    assert isinstance(data["severity"], int)
    assert isinstance(data["priority_score"], (int, float))


def assert_cash_forecast(data: dict):
    assert isinstance(data["projected_cents"], (int, float))
    assert data["method"] in ["EXPECTED", "CONSERVATIVE"]


# --------------------------------------------------------------------------- #
# Domain invariants (PRD §2.6 ledger reconciliation)
# --------------------------------------------------------------------------- #
def assert_dunnable_plus_disputed(invoice: dict, expected_total: int):
    """Conserved identity (PRD §3.4): dunnable + disputed amount stays fixed
    across a dispute open/withdraw cycle."""
    dunnable = invoice["balance_cents"] - invoice["disputed_amount_cents"]
    assert dunnable + invoice["disputed_amount_cents"] == expected_total, (
        f"dunnable + disputed must equal {expected_total}, "
        f"got balance={invoice['balance_cents']} disputed={invoice['disputed_amount_cents']}"
    )
