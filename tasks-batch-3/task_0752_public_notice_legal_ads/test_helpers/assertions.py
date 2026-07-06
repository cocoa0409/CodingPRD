"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_newspaper(data: dict):
    assert is_valid_uuid(data.get("id", "")), "newspaper id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["county"], str) and len(data["county"]) > 0
    assert isinstance(data["circulation_qualified"], bool)
    assert data["pricing_basis"] in ("PER_LINE", "PER_WORD")
    assert isinstance(data["chars_per_line"], int) and data["chars_per_line"] >= 1
    assert isinstance(data["publication_weekday"], int) and 0 <= data["publication_weekday"] <= 6
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "account id must be a valid UUID"
    assert data["account_type"] in ("LAW_FIRM", "GOVERNMENT", "INDIVIDUAL")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_notice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "notice id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["notice_type"] in ("FORECLOSURE", "PROBATE", "BID")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "PROOF_APPROVED", "SCHEDULED", "RUNNING",
        "PUBLISHED", "AFFIDAVIT_ISSUED", "ARCHIVED",
    )
    assert data["compliance_status"] in ("PENDING", "COMPLIANT", "NON_COMPLIANT")
    assert isinstance(data["word_count"], int) and data["word_count"] >= 0
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    assert isinstance(data["required_insertions"], int) and data["required_insertions"] >= 1
    assert isinstance(data["insertions_published"], int) and data["insertions_published"] >= 0
    assert isinstance(data["paid_insertion_count"], int) and data["paid_insertion_count"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_insertion(data: dict):
    assert is_valid_uuid(data.get("id", "")), "insertion id must be a valid UUID"
    assert data["status"] in ("SCHEDULED", "PUBLISHED", "SKIPPED", "CANCELLED")
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert isinstance(data["is_make_good"], bool)
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0


def assert_proof(data: dict):
    assert is_valid_uuid(data.get("id", "")), "proof id must be a valid UUID"
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_affidavit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "affidavit id must be a valid UUID"
    assert data["status"] in ("PENDING", "ISSUED", "VOID")


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "invoice id must be a valid UUID"
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)


def assert_invoice_line_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "line item id must be a valid UUID"
    assert isinstance(data["amount_cents"], int)
    # Append-only ledger record: no version / updated_at.
    assert "version" not in data or data.get("version") is None
    assert "updated_at" not in data or data.get("updated_at") is None


def assert_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "payment id must be a valid UUID"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert "version" not in data or data.get("version") is None
    assert "updated_at" not in data or data.get("updated_at") is None


def assert_invoice_total_consistent(data: dict):
    """PRD §3.6: total_cents is subtotal_cents plus affidavit_fee_cents."""
    assert data["total_cents"] == data["subtotal_cents"] + data["affidavit_fee_cents"], (
        f"total {data['total_cents']} != subtotal {data['subtotal_cents']} "
        f"+ fee {data['affidavit_fee_cents']}"
    )
