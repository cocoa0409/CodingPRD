"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Assertions check only
fields the PRD promises on a resource (PRD 2.4 common fields, plus each
entity's own fields).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, append_only: bool = False):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if not append_only:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["tax_rate_bps"], int)
    assert isinstance(data["interest_rate_monthly_bps"], int)
    assert isinstance(data["refund_interest_monthly_bps"], int)
    assert isinstance(data["lien_threshold_cents"], int)
    assert isinstance(data["exemption_min_stay_nights"], int)


def assert_operator(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["filing_frequency"] in ("MONTHLY", "QUARTERLY")
    assert data["status"] in ("PENDING", "ACTIVE", "DELINQUENT", "SUSPENDED", "REVOKED", "CLOSED")
    assert isinstance(data["account_balance_cents"], int)


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["operator_id"], str)
    assert isinstance(data["active"], bool)


def assert_ota_platform(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["registered"], bool)


def assert_ota_agreement(data: dict):
    _assert_common(data)
    assert data["collection_method"] in ("GROSS", "NET")
    assert data["status"] in ("PROPOSED", "ACTIVE", "TERMINATED")


def assert_tax_return(data: dict):
    _assert_common(data)
    assert data["filing_status"] in ("DRAFT", "FILED", "AMENDED", "SUPERSEDED")
    assert data["settlement_status"] in ("UNPAID", "PARTIAL", "PAID")
    for f in ("gross_receipts_cents", "exempt_receipts_cents", "taxable_receipts_cents",
              "tax_due_cents", "penalty_cents", "interest_cents", "total_due_cents",
              "amount_paid_cents"):
        assert isinstance(data[f], int), f"{f} must be an int"


def assert_exemption_claim(data: dict):
    _assert_common(data)
    assert data["exemption_type"] in ("LONG_TERM_30DAY", "GOVERNMENT", "NONPROFIT")
    assert data["status"] in ("CLAIMED", "VERIFIED", "REJECTED")
    assert isinstance(data["amount_cents"], int)


def assert_remittance(data: dict):
    _assert_common(data)
    assert data["remitter"] in ("OPERATOR", "OTA")
    assert data["status"] in ("RECEIVED", "CLEARED", "REVERSED")
    assert isinstance(data["amount_cents"], int)


def assert_audit(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPENED", "FIELDWORK", "PROPOSED", "RESPONSE", "ISSUED", "CLOSED_NO_CHANGE")
    assert data["classification"] in ("NONE", "NEGLIGENCE", "FRAUD")


def assert_assessment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "ISSUED", "APPEALED", "FINAL", "ABATED", "SETTLED")
    for f in ("assessed_tax_cents", "self_reported_tax_cents", "deficiency_cents",
              "penalty_cents", "interest_cents", "total_assessed_cents"):
        assert isinstance(data[f], int), f"{f} must be an int"


def assert_appeal(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED", "DECIDED")
    assert isinstance(data["round_count"], int)


def assert_lien(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECORDED", "RELEASED")
    assert isinstance(data["amount_cents"], int)


def assert_refund_claim(data: dict):
    _assert_common(data)
    assert data["reason"] in ("OVERPAYMENT", "AUDIT_ADJUSTMENT")
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "PAID")
    assert isinstance(data["principal_cents"], int)


def assert_ledger_entry(data: dict):
    _assert_common(data, append_only=True)
    assert "updated_at" not in data, "ledger entry is append-only: no updated_at"
    assert "version" not in data, "ledger entry is append-only: no version"
    assert data["entry_type"] in (
        "TAX_DUE", "PENALTY", "INTEREST", "REMITTANCE", "REMITTANCE_REVERSAL",
        "ASSESSMENT", "ABATEMENT", "REFUND", "ADJUSTMENT",
    )
    assert isinstance(data["amount_signed_cents"], int)


def assert_balance_equals_ledger(operator: dict, ledger_entries: list):
    """PRD 2.6 invariant: account_balance_cents == sum of all ledger amounts."""
    total = sum(e["amount_signed_cents"] for e in ledger_entries)
    assert operator["account_balance_cents"] == total, (
        f"balance {operator['account_balance_cents']} != ledger sum {total}"
    )


def assert_receipts_partition(ret: dict):
    """PRD 3.4 invariant: gross == taxable + exempt."""
    assert ret["gross_receipts_cents"] == ret["taxable_receipts_cents"] + ret["exempt_receipts_cents"], (
        f"partition broken: gross={ret['gross_receipts_cents']} "
        f"taxable={ret['taxable_receipts_cents']} exempt={ret['exempt_receipts_cents']}"
    )
