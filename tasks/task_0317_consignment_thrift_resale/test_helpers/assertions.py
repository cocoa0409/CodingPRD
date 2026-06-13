"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD contract
using the framework's generic format checkers. Append-only ledger records are
checked to carry id + created_at only (no version / updated_at).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Common-field helpers ────────────────────────────────────────────────────

def _assert_mutable_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must NOT carry version"
    assert "updated_at" not in data, "append-only record must NOT carry updated_at"


# ─── Mutable entities ────────────────────────────────────────────────────────

def assert_consignor(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["store_credit_cents"], int)
    assert data["store_credit_cents"] >= 0, "store_credit_cents must be >= 0"
    assert isinstance(data["unsettled_payable_cents"], int)
    assert isinstance(data["lifetime_payout_cents"], int)
    assert data["lifetime_payout_cents"] >= 0, "lifetime_payout_cents must be >= 0"


def assert_markdown_schedule(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["base_floor_pct"], (int, float))
    assert 0 < data["base_floor_pct"] <= 1
    assert isinstance(data["tiers"], list) and len(data["tiers"]) > 0
    assert isinstance(data["is_archived"], bool)


def assert_agreement(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data["consignor_id"])
    assert is_valid_uuid(data["markdown_schedule_id"])
    assert 0 < data["split_pct"] < 1
    assert data["split_basis"] in ["GROSS", "NET"]
    assert data["unsold_disposition"] in ["RETURN_TO_CONSIGNOR", "DONATE", "STORE_KEEPS"]
    assert isinstance(data["return_window_days"], int) and data["return_window_days"] >= 1
    assert data["payout_method"] in ["CASH", "STORE_CREDIT"]
    assert data["status"] in ["ACTIVE", "TERMINATED"]


def assert_intake_batch(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data["agreement_id"])
    assert data["status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0


def assert_item(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data["batch_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["consignor_id"])
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["requires_authentication"], bool)
    assert data["grading_status"] in ["PENDING_GRADE", "ACCEPTED", "REJECTED"]
    assert data["listing_status"] in [
        "NOT_LISTED", "ON_FLOOR", "SOLD", "RETURNED", "DONATED", "PULLED"
    ]
    assert data["authentication_status"] in [
        "NOT_REQUIRED", "PENDING_AUTH", "AUTHENTIC", "COUNTERFEIT"
    ]


def assert_authentication_review(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data["item_id"])
    assert data["status"] in ["IN_REVIEW", "DISPUTED", "AUTHENTIC", "COUNTERFEIT"]
    assert isinstance(data["dispute_round"], int) and data["dispute_round"] >= 0


def assert_sale(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["business_date"], str) and len(data["business_date"]) == 10
    assert data["payment_method"] in ["CASH", "CARD", "STORE_CREDIT"]
    assert isinstance(data["gross_total_cents"], int) and data["gross_total_cents"] >= 0
    assert data["status"] in ["COMPLETED", "VOIDED"]


def assert_settlement(data: dict):
    _assert_mutable_common_fields(data)
    assert isinstance(data["business_date"], str) and len(data["business_date"]) == 10
    assert data["status"] in ["OPEN", "FINALIZED", "VOIDED"]
    assert isinstance(data["total_gross_cents"], int)
    assert isinstance(data["total_consignor_payable_cents"], int)
    assert isinstance(data["total_store_credit_issued_cents"], int)
    assert isinstance(data["total_store_share_cents"], int)
    assert isinstance(data["swept_sale_count"], int) and data["swept_sale_count"] >= 0


def assert_donation_record(data: dict):
    _assert_mutable_common_fields(data)
    assert is_valid_uuid(data["item_id"])
    assert is_valid_uuid(data["consignor_id"])
    assert data["disposition"] in ["RETURNED", "DONATED", "STORE_KEPT"]
    assert isinstance(data["tax_receipt_value_cents"], int)
    assert data["tax_receipt_value_cents"] >= 0


# ─── Append-only ledger records ──────────────────────────────────────────────

def assert_sale_line(data: dict):
    _assert_append_only_common_fields(data)
    assert is_valid_uuid(data["item_id"])
    assert isinstance(data["sold_price_cents"], int)
    assert isinstance(data["split_base_cents"], int)
    assert isinstance(data["consignor_proceeds_cents"], int)
    assert isinstance(data["store_share_cents"], int)


def assert_payout_ledger_entry(data: dict):
    _assert_append_only_common_fields(data)
    assert is_valid_uuid(data["consignor_id"])
    assert data["entry_type"] in ["SALE_PAYOUT", "REVERSAL"]
    assert isinstance(data["amount_cents"], int)


def assert_store_credit_transaction(data: dict):
    _assert_append_only_common_fields(data)
    assert is_valid_uuid(data["consignor_id"])
    assert data["txn_type"] in ["ISSUE", "REDEEM"]
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["POSTED", "VOID"]
