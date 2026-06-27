"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Append-only entities (Verification, LedgerEntry) are validated
WITHOUT updated_at / version, which the PRD says they do not carry.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (common_fields: true)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """id + created_at only (common_fields: false). No updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["currency"], str)


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "SUSPENDED", "CLOSED")
    assert isinstance(data["reserve_balance_cents"], int)
    assert isinstance(data["funded_advance_outstanding_cents"], int)


def assert_debtor(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED", "INSOLVENT")
    assert data["credit_rating"] in ("AAA", "A", "BBB", "BB", "C")
    assert isinstance(data["outstanding_face_cents"], int)


def assert_relationship(data: dict):
    _assert_common(data)
    assert data["recourse_type"] in ("RECOURSE", "NON_RECOURSE")
    assert data["notice_status"] in ("PENDING", "NOTICED", "SUSPENDED")
    assert data["status"] == "ACTIVE"


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["invoice_number"], str) and len(data["invoice_number"]) > 0
    assert isinstance(data["face_amount_cents"], int)
    assert data["status"] in (
        "SUBMITTED", "VERIFIED", "FUNDED", "OUTSTANDING", "SHORT_PAID",
        "SETTLED", "BOUGHT_BACK", "WRITTEN_OFF", "REJECTED",
    )
    assert data["aging_bucket"] in (
        "CURRENT", "DPD_1_30", "DPD_31_60", "DPD_61_90", "DPD_90_PLUS",
    )


def assert_batch(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FUNDED", "FAILED")
    assert isinstance(data["invoice_ids"], list)


def assert_verification(data: dict):
    _assert_append_only(data)
    assert data["method"] in ("PHONE", "EMAIL", "PORTAL", "WAIVED")


def assert_posting(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("POSTED", "REVERSED")


def assert_adjustment(data: dict):
    _assert_common(data)
    assert data["type"] in ("DILUTION", "CREDIT_MEMO", "CHARGEBACK_FEE")
    assert isinstance(data["amount_cents"], int)


def assert_buyback(data: dict):
    _assert_common(data)
    assert data["status"] == "COMPLETED"
    assert isinstance(data["buyback_amount_cents"], int)


def assert_settlement(data: dict):
    _assert_common(data)
    assert isinstance(data["principal_applied_cents"], int)
    assert isinstance(data["fee_applied_cents"], int)
    assert isinstance(data["rebate_cents"], int)


def assert_ledger_entry(data: dict):
    _assert_append_only(data)
    assert data["entry_type"] in (
        "ADVANCE_DISBURSED", "RESERVE_HELD", "FEE_ACCRUED", "COLLECTION_POSTED",
        "REBATE_PAID", "RESERVE_RELEASED", "BUYBACK_RECEIVED", "WRITE_OFF",
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["reserve_balance_after_cents"], int)


def assert_face_equals_advance_plus_reserve(invoice: dict):
    """PRD §2.7 invariant: face = advance + reserve, no rounding drift."""
    assert (
        invoice["face_amount_cents"]
        == invoice["advance_amount_cents"] + invoice["reserve_held_cents"]
    ), "face_amount_cents must equal advance_amount_cents + reserve_held_cents"
