"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) validates the shape and field domains of a returned
resource per the PRD. Full-lifecycle resources carry id/created_at/updated_at/version;
RateCard and PayoutLedgerEntry carry only id/created_at.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

PROJECT_STATES = ["DRAFT", "QUOTED", "APPROVED", "IN_PRODUCTION",
                  "DELIVERED", "INVOICED", "CANCELLED"]
JOB_STATES = ["PENDING", "TRANSLATING", "IN_QA", "REVISION",
              "QA_PASSED", "DELIVERED", "CANCELLED"]
ASSIGNMENT_STATES = ["OFFERED", "ACCEPTED", "IN_PROGRESS", "DELIVERED",
                     "DECLINED", "SUPERSEDED", "CANCELLED"]
INVOICE_STATES = ["DRAFT", "ISSUED", "PAID", "VOIDED"]


def _assert_full_lifecycle_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_lean_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_client(data: dict):
    _assert_full_lifecycle_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["billing_email"], str) and len(data["billing_email"]) > 0
    assert isinstance(data["ar_balance_cents"], int), "ar_balance_cents must be int"
    assert data["status"] in ["ACTIVE", "SUSPENDED"], f"bad client status {data['status']}"


def assert_linguist(data: dict):
    _assert_full_lifecycle_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["native_locale"], str)
    assert isinstance(data["qualified_pairs"], list)
    assert isinstance(data["can_review"], bool)
    assert isinstance(data["daily_throughput_words"], int)
    assert isinstance(data["committed_payout_cents"], int)
    assert data["status"] in ["ACTIVE", "INACTIVE"], f"bad linguist status {data['status']}"


def assert_rate_card(data: dict):
    _assert_lean_common(data)
    assert "updated_at" not in data, "RateCard is immutable; must not carry updated_at"
    assert "version" not in data, "RateCard is immutable; must not carry version"
    assert isinstance(data["source_locale"], str)
    assert isinstance(data["target_locale"], str)
    assert isinstance(data["base_rate_cents_per_word"], int)
    assert isinstance(data["linguist_rate_cents_per_word"], int)


def assert_project(data: dict):
    _assert_full_lifecycle_common(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["rate_card_id"], str)
    assert isinstance(data["name"], str)
    assert data["rush_tier"] in ["STANDARD", "EXPRESS", "SAME_DAY"]
    assert data["certification_mode"] in ["NONE", "CERTIFIED", "NOTARIZED"]
    assert isinstance(data["pinned_base_rate_cents_per_word"], int)
    assert isinstance(data["pinned_linguist_rate_cents_per_word"], int)
    assert data["quoted_total_cents"] is None or isinstance(data["quoted_total_cents"], int)
    assert data["status"] in PROJECT_STATES, f"bad project status {data['status']}"


def assert_project_job(data: dict):
    _assert_full_lifecycle_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["filename"], str)
    assert isinstance(data["revision_rounds"], int)
    assert data["status"] in JOB_STATES, f"bad job status {data['status']}"


def assert_assignment(data: dict):
    _assert_full_lifecycle_common(data)
    assert isinstance(data["job_id"], str)
    assert isinstance(data["linguist_id"], str)
    assert data["role"] in ["TRANSLATOR", "REVIEWER"]
    assert isinstance(data["payout_cents"], int)
    assert isinstance(data["payout_finalized"], bool)
    assert data["status"] in ASSIGNMENT_STATES, f"bad assignment status {data['status']}"


def assert_qa_report(data: dict):
    _assert_full_lifecycle_common(data)
    assert isinstance(data["job_id"], str)
    assert isinstance(data["reviewer_assignment_id"], str)
    assert isinstance(data["scored_word_count"], int)
    assert isinstance(data["score"], (int, float))
    assert data["outcome"] in ["PASS", "FAIL"], f"bad outcome {data['outcome']}"


def assert_invoice(data: dict):
    _assert_full_lifecycle_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["client_id"], str)
    assert data["status"] in INVOICE_STATES, f"bad invoice status {data['status']}"


def assert_delivery_certificate(data: dict):
    _assert_full_lifecycle_common(data)
    assert isinstance(data["job_id"], str)
    assert data["certification_mode"] in ["CERTIFIED", "NOTARIZED"], (
        "certificate certification_mode must be CERTIFIED or NOTARIZED, never NONE"
    )
    assert isinstance(data["page_count"], int)
    assert isinstance(data["certificate_number"], int)


def assert_payout_ledger_entry(data: dict):
    _assert_lean_common(data)
    assert "updated_at" not in data, "PayoutLedgerEntry is append-only; no updated_at"
    assert "version" not in data, "PayoutLedgerEntry is append-only; no version"
    assert isinstance(data["linguist_id"], str)
    assert isinstance(data["assignment_id"], str)
    assert data["entry_type"] in ["COMMIT", "REVERSAL", "FINAL_ADJUST"]
    assert isinstance(data["amount_cents"], int)
