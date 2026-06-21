"""Entity assertions and domain invariant checkers for the settlement API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _versioned(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 1, "version starts at 1"


def assert_settlement(data: dict):
    _versioned(data)
    assert isinstance(data["case_caption"], str) and len(data["case_caption"]) > 0
    assert isinstance(data["gross_fund_cents"], int)
    assert isinstance(data["attorney_fee_cents"], int)
    assert isinstance(data["admin_cost_cents"], int)
    assert data["distribution_method"] in ("PRO_RATA", "TIERED")
    assert data["status"] in (
        "DRAFT", "NOTICE_OPEN", "CLAIMS_OPEN", "CLAIMS_CLOSED",
        "DISTRIBUTING", "RECONCILED", "CLOSED",
    )
    assert isinstance(data["net_distributable_cents"], int)
    assert isinstance(data["allocated_cents"], int)
    assert isinstance(data["residual_cents"], int)


def assert_settlement_net_invariant(data: dict):
    """net_distributable_cents == gross - fee - admin (PRD §2.8)."""
    expected = data["gross_fund_cents"] - data["attorney_fee_cents"] - data["admin_cost_cents"]
    assert data["net_distributable_cents"] == expected, (
        f"net_distributable_cents should be {expected}, got {data['net_distributable_cents']}"
    )


def assert_class_member(data: dict):
    _versioned(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["claimant_tier"] in ("TIER_A", "TIER_B")
    assert isinstance(data["tin_on_file"], bool)
    assert data["status"] in ("NOTIFIED", "PARTICIPATING", "EXCLUDED")
    assert isinstance(data["notice_count"], int)


def assert_claim(data: dict):
    _versioned(data)
    assert isinstance(data["claimed_loss_cents"], int)
    assert isinstance(data["recognized_loss_cents"], int)
    assert data["status"] in (
        "SUBMITTED", "DEFICIENT", "CURED", "VALIDATED", "REJECTED", "PAID"
    )
    assert isinstance(data["open_deficiency_count"], int)
    assert isinstance(data["paid_amount_cents"], int)


def assert_deficiency(data: dict):
    _versioned(data)
    assert data["reason_code"] in (
        "MISSING_PROOF", "SIGNATURE_MISSING", "IDENTITY_UNVERIFIED", "DUPLICATE_SUSPECTED"
    )
    assert data["status"] in ("OPEN", "CURED", "EXPIRED")


def assert_opt_out(data: dict):
    _versioned(data)
    assert data["status"] in ("REQUESTED", "EFFECTIVE", "REVOKED")


def assert_objection(data: dict):
    _versioned(data)
    assert data["status"] in ("FILED", "SUSTAINED", "OVERRULED", "WITHDRAWN")


def assert_distribution_batch(data: dict):
    _versioned(data)
    assert isinstance(data["sequence_no"], int)
    assert data["status"] in ("DRAFT", "COMPUTED", "POSTED", "REVERSED", "VOID")
    assert isinstance(data["planned_total_cents"], int)
    assert isinstance(data["posted_total_cents"], int)
    assert isinstance(data["residual_after_cents"], int)


def assert_payment(data: dict):
    _versioned(data)
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["withholding_cents"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PLANNED", "COMMITTED", "REVERSED", "CANCELLED")
    # amount = gross - withholding (PRD §3.6).
    assert data["amount_cents"] == data["gross_amount_cents"] - data["withholding_cents"], (
        "amount_cents must equal gross_amount_cents - withholding_cents"
    )


def assert_tax_form(data: dict):
    _versioned(data)
    assert data["form_type"] in ("1099_MISC", "1099_NEC")
    assert isinstance(data["reportable_cents"], int)
    assert isinstance(data["withheld_cents"], int)
    assert data["status"] in ("ISSUED", "CORRECTED", "VOIDED")


def assert_cy_pres_designation(data: dict):
    _versioned(data)
    assert isinstance(data["recipient_name"], str) and len(data["recipient_name"]) > 0
    assert isinstance(data["share_bps"], int)
    assert data["status"] in ("PROPOSED", "APPROVED", "FUNDED", "REVOKED")
    assert isinstance(data["funded_cents"], int)


def assert_notice_record_is_append_only(data: dict):
    """A NoticeRecord carries only id + created_at — no version, no updated_at
    (PRD §2.4)."""
    _common(data)
    assert "version" not in data, "NoticeRecord must not carry a version field"
    assert "updated_at" not in data, "NoticeRecord must not carry an updated_at field"


def assert_ledger_entry(data: dict):
    """A LedgerEntry carries only id + created_at plus its content fields —
    no version, no updated_at (PRD §2.4)."""
    _common(data)
    assert data["entry_type"] in (
        "FUND_OPEN", "FEE_DEBIT", "ADMIN_DEBIT",
        "PAYMENT_DEBIT", "PAYMENT_REVERSAL_CREDIT", "CY_PRES_DEBIT",
    )
    assert isinstance(data["amount_cents"], int)
