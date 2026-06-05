"""Entity assertions and domain invariant checkers.

All entities carry the full system-managed quartet (id, created_at, updated_at, version)
per PRD §2.4; assertions validate that quartet plus entity-specific fields.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_grantor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["generation_level"], int)
    assert isinstance(data["gst_exemption_total_cents"], int) and data["gst_exemption_total_cents"] >= 0
    assert isinstance(data["gst_exemption_remaining_cents"], int)


def assert_trustee(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["is_corporate"], bool)


def assert_beneficiary(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_valid_uuid(data.get("grantor_id", "")), "grantor_id must be a valid UUID"
    assert isinstance(data["generation_level"], int) and data["generation_level"] >= 0
    assert isinstance(data["is_skip_person"], bool)


def assert_trust(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_valid_uuid(data.get("grantor_id", "")), "grantor_id must be a valid UUID"
    assert data["trust_type"] in ("REVOCABLE", "IRREVOCABLE")
    assert isinstance(data["is_grantor_trust"], bool)
    assert isinstance(data["capital_gains_to_income"], bool)
    assert data["status"] in (
        "DRAFT", "FUNDED", "ACTIVE", "AMENDMENT_PENDING",
        "TERMINATING", "TERMINATED", "REVOKED",
    )
    assert isinstance(data["principal_balance_cents"], int)
    assert isinstance(data["income_balance_cents"], int)
    assert isinstance(data["gst_exemption_allocated_cents"], int)
    assert isinstance(data["inclusion_ratio"], (int, float))
    assert 0.0 <= data["inclusion_ratio"] <= 1.0, "inclusion_ratio clamped to [0,1]"


def assert_trustee_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("trust_id", ""))
    assert is_valid_uuid(data.get("trustee_id", ""))
    assert data["status"] in ("ACTIVE", "RESIGNED")


def assert_trust_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("trust_id", ""))
    assert isinstance(data["tax_year"], int)
    assert data["status"] in ("OPEN", "CLOSED", "FILED")
    assert isinstance(data["dni_cents"], int) and data["dni_cents"] >= 0
    assert isinstance(data["dni_carried_out_cents"], int) and data["dni_carried_out_cents"] >= 0
    assert isinstance(data["taxable_income_cents"], int) and data["taxable_income_cents"] >= 0


def assert_receipt(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["receipt_kind"] in (
        "INTEREST", "DIVIDEND_ORDINARY", "DIVIDEND_QUALIFIED", "CAPITAL_GAIN", "CONTRIBUTION",
    )
    assert data["ledger_side"] in ("INCOME", "PRINCIPAL")


def assert_disbursement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["expense_kind"] in ("TRUSTEE_FEE", "INVESTMENT_FEE", "TAX_PAYMENT", "ADMINISTRATIVE")
    assert data["ledger_side"] in ("INCOME", "PRINCIPAL")
    assert isinstance(data["is_system_generated"], bool)


def assert_distribution(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("beneficiary_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["distribution_kind"] in ("MANDATORY", "DISCRETIONARY")
    assert is_valid_uuid(data.get("proposer_trustee_id", ""))
    assert data["status"] in ("PROPOSED", "APPROVED", "REJECTED", "PAID", "REVERSED")


def assert_k1(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("beneficiary_id", ""))
    assert isinstance(data["ordinary_income_cents"], int)
    assert isinstance(data["qualified_dividend_cents"], int)
    assert isinstance(data["capital_gain_cents"], int)
    assert isinstance(data["total_carried_cents"], int)


def assert_tax_filing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["taxable_income_snapshot_cents"], int)
    assert isinstance(data["tax_due_cents"], int) and data["tax_due_cents"] >= 0
    assert data["status"] in ("DRAFT", "FILED", "AMENDED", "SUPERSEDED")


def assert_gst_exemption_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("trust_id", ""))
    assert is_valid_uuid(data.get("grantor_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("ALLOCATED", "RELEASED")


def assert_gst_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("trust_id", ""))
    assert is_valid_uuid(data.get("beneficiary_id", ""))
    assert data["event_type"] in ("TAXABLE_DISTRIBUTION", "TAXABLE_TERMINATION")
    assert isinstance(data["taxable_amount_cents"], int)
    assert isinstance(data["gst_tax_cents"], int)
    assert isinstance(data["inclusion_ratio_snapshot"], (int, float))


# ─── Domain invariant checkers ───────────────────────────────

def assert_trust_balance_invariants(data: dict):
    """Two-ledger invariants that must hold after any operation (PRD §2.7, §2.8)."""
    assert isinstance(data["principal_balance_cents"], int), "principal balance is whole cents"
    assert isinstance(data["income_balance_cents"], int), "income balance is whole cents"
    assert 0.0 <= data["inclusion_ratio"] <= 1.0, "inclusion_ratio clamped to [0,1]"
