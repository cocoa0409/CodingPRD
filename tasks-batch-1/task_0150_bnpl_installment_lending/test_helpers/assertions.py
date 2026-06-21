"""Entity assertions and domain invariant checkers for the BNPL PRD."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# --------------------------------------------------------------------------
# Per-entity field assertions
# --------------------------------------------------------------------------
def assert_merchant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "merchant id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["mdr_bps"], int) and 0 <= data["mdr_bps"] <= 1000
    assert isinstance(data["settlement_hold_days"], int) and 0 <= data["settlement_hold_days"] <= 30
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["gross_financed_cents"], int)
    assert isinstance(data["net_settled_cents"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_borrower(data: dict):
    assert is_valid_uuid(data.get("id", "")), "borrower id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0
    assert isinstance(data["soft_credit_score"], int) and 300 <= data["soft_credit_score"] <= 850
    assert isinstance(data["eligible_credit_limit_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int)
    assert isinstance(data["available_credit_cents"], int)
    assert data["version"] >= 1


def assert_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "application id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["borrower_id"])
    assert is_valid_uuid(data["merchant_id"])
    assert isinstance(data["cart_amount_cents"], int) and data["cart_amount_cents"] > 0
    assert data["plan_type"] in ("PAY_IN_4", "MONTHLY")
    assert isinstance(data["apr_bps"], int)
    assert isinstance(data["financed_principal_cents"], int)
    assert isinstance(data["finance_charge_cents"], int)
    assert isinstance(data["total_of_payments_cents"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "COUNTERED", "DECLINED", "ACTIVATED", "WITHDRAWN")
    assert data["version"] >= 1


def assert_disclosure_acceptance(data: dict):
    assert is_valid_uuid(data.get("id", "")), "disclosure id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["disclosed_apr_bps"], int)
    assert isinstance(data["disclosed_finance_charge_cents"], int)
    assert isinstance(data["disclosed_total_of_payments_cents"], int)
    assert isinstance(data["disclosed_installment_count"], int)
    assert isinstance(data["accepted"], bool)


def assert_disclosure_is_immutable(data: dict):
    """PRD §2.4: DisclosureAcceptance carries only id + created_at — no version,
    no updated_at."""
    assert "version" not in data, "DisclosureAcceptance must not carry a version field"
    assert "updated_at" not in data, "DisclosureAcceptance must not carry an updated_at field"


def assert_loan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "loan id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["borrower_id"])
    assert is_valid_uuid(data["merchant_id"])
    assert isinstance(data["financed_principal_cents"], int)
    assert isinstance(data["apr_bps"], int)
    assert isinstance(data["finance_charge_cents"], int)
    assert isinstance(data["remaining_principal_cents"], int) and data["remaining_principal_cents"] >= 0
    assert isinstance(data["total_paid_cents"], int)
    assert isinstance(data["late_fee_accrued_cents"], int)
    assert data["status"] in ("ACTIVE", "PAID_OFF", "DEFAULTED", "CANCELLED")
    assert data["delinquency_status"] in ("CURRENT", "LATE", "DELINQUENT")
    assert data["version"] >= 1


def assert_installment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "installment id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert is_iso8601_timestamp(data["due_date"]), "due_date must be ISO 8601"
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["principal_portion_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["late_fee_cents"], int)
    assert data["status"] in ("SCHEDULED", "LATE", "PAID", "WRITTEN_OFF", "CANCELLED")


def assert_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "payment id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["source"] in ("MANUAL", "AUTOPAY")
    assert isinstance(data["allocation"], list)
    assert isinstance(data["unapplied_cents"], int)


def assert_return(data: dict):
    assert is_valid_uuid(data.get("id", "")), "return id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["loan_id"])
    assert is_valid_uuid(data["merchant_id"])
    assert isinstance(data["return_amount_cents"], int) and data["return_amount_cents"] > 0
    assert isinstance(data["principal_reduction_cents"], int)
    assert isinstance(data["settlement_clawback_cents"], int)
    assert data["status"] == "POSTED"


def assert_autopay_mandate(data: dict):
    assert is_valid_uuid(data.get("id", "")), "mandate id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["loan_id"])
    assert is_valid_uuid(data["borrower_id"])
    assert data["status"] in ("ENABLED", "DISABLED")


def assert_merchant_settlement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "settlement id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["merchant_id"])
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["gross_financed_cents"], int)
    assert isinstance(data["mdr_fee_cents"], int)
    assert isinstance(data["net_settlement_cents"], int)
    assert isinstance(data["clawed_back_cents"], int)
    assert data["status"] in ("PENDING", "RELEASED", "CLAWED_BACK")


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_borrower_credit_conserved(data: dict):
    """PRD §2.5: available_credit_cents == eligible_credit_limit_cents -
    outstanding_principal_cents, never below zero."""
    expected = max(0, data["eligible_credit_limit_cents"] - data["outstanding_principal_cents"])
    assert data["available_credit_cents"] == expected, (
        f"available_credit_cents {data['available_credit_cents']} != "
        f"eligible {data['eligible_credit_limit_cents']} - outstanding "
        f"{data['outstanding_principal_cents']} (floored at 0)"
    )
    assert data["available_credit_cents"] >= 0


def installments_by_sequence(installments: list) -> list:
    """Return installments sorted by sequence_no ascending (PRD §2.3 listing order)."""
    return sorted(installments, key=lambda i: i["sequence_no"])


def find_installment(installments: list, sequence_no: int) -> dict:
    """Locate the installment with the given 1-based sequence_no."""
    for inst in installments:
        if inst["sequence_no"] == sequence_no:
            return inst
    raise AssertionError(f"No installment with sequence_no == {sequence_no}")
