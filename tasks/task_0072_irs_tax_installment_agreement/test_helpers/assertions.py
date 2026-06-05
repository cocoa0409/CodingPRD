"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_tax_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["taxpayer_name"], str) and len(data["taxpayer_name"]) > 0
    assert data["filing_status"] in ("INDIVIDUAL", "BUSINESS")
    assert data["collection_status"] in (
        "ACTIVE_COLLECTION", "IN_AGREEMENT", "CNC", "OIC_PENDING", "RESOLVED")
    assert isinstance(data["total_balance_cents"], int) and data["total_balance_cents"] >= 0
    assert isinstance(data["csed_protection_count"], int) and data["csed_protection_count"] >= 0
    assert isinstance(data["version"], int)


def assert_tax_period(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["period_status"] in (
        "ASSESSED", "IN_COLLECTION", "SATISFIED", "WRITTEN_OFF", "ABATED")
    assert isinstance(data["balance_due_cents"], int) and data["balance_due_cents"] >= 0
    assert isinstance(data["assessed_tax_cents"], int) and data["assessed_tax_cents"] > 0
    assert is_iso8601_timestamp(data.get("csed_date", "")), "csed_date must be ISO 8601"


def assert_csed_suspension(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["days_counted"], int) and data["days_counted"] >= 0


def assert_agreement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in (
        "PROPOSED", "APPROVED", "REJECTED", "DEFAULTED", "REINSTATED", "CLOSED")
    assert data["agreement_type"] in ("SHORT_TERM", "LONG_TERM", "PPIA")
    assert data["payment_method"] in ("DIRECT_DEBIT", "MANUAL")
    assert isinstance(data["setup_fee_cents"], int) and data["setup_fee_cents"] >= 0
    assert isinstance(data["missed_debit_count"], int) and data["missed_debit_count"] >= 0


def assert_offer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("SUBMITTED", "EVALUATING", "ACCEPTED", "REJECTED", "DEFAULTED")
    assert isinstance(data["offer_amount_cents"], int) and data["offer_amount_cents"] > 0


def assert_lien(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("FILED", "RELEASE_PENDING", "RELEASED", "WITHDRAWN")
    assert isinstance(data["filed_amount_cents"], int) and data["filed_amount_cents"] > 0


def assert_cnc(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("ACTIVE", "REVOKED")
    assert data["hardship_reason"] in ("NO_DISPOSABLE_INCOME", "HARDSHIP", "UNABLE_TO_LOCATE")


def assert_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["payment_source"] in ("DDIA_DEBIT", "MANUAL", "OIC_LUMP_SUM")
