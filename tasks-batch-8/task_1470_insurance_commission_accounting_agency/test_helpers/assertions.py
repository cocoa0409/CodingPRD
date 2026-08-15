"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_producer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["tier"] in ("STANDARD", "GOLD", "PLATINUM")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["commission_balance_cents"], int)
    assert isinstance(data["pending_chargebacks_cents"], int)
    assert isinstance(data["tax_form_on_file"], bool)


def assert_carrier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["carrier_code"], str) and data["carrier_code"]
    assert isinstance(data["trust_balance_cents"], int)
    assert isinstance(data["total_remitted_cents"], int)


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["line_of_business"] in ("LIFE", "ANNUITY", "HEALTH", "PROPERTY_CASUALTY")


def assert_commission_schedule(data: dict):
    _assert_common_fields(data)
    assert data["tier"] in ("STANDARD", "GOLD", "PLATINUM")
    assert isinstance(data["commission_rate_bps"], int)
    assert isinstance(data["override_rate_bps"], int)
    assert isinstance(data["advance_months"], int)
    assert 1 <= data["advance_months"] <= 12
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert data["billing_type"] in ("AGENCY_BILL", "DIRECT_BILL")
    assert isinstance(data["premium_annual_cents"], int)
    assert data["status"] in (
        "QUOTED",
        "ACTIVE",
        "GRACE",
        "CANCELLED_VOLUNTARY",
        "CANCELLED_NONPAY",
    )


def assert_premium_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["paid_total_cents"], int)
    assert data["status"] in ("OPEN", "DELINQUENT", "PAID")


def assert_carrier_statement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("RECEIVED", "RECONCILING", "DISPUTED", "RECONCILED")
    assert isinstance(data["lines"], list)
    assert isinstance(data["total_reported_cents"], int)


def assert_commission_entry(data: dict):
    _assert_common_fields(data)
    assert data["entry_type"] in (
        "BASE",
        "OVERRIDE",
        "EARNED_ADJUSTMENT",
        "VARIANCE_ADJUSTMENT",
    )
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("EXPECTED", "MATCHED", "VARIANCE", "CHARGED_BACK")


def assert_chargeback(data: dict):
    _assert_common_fields(data)
    assert data["reason"] in (
        "CANCELLATION_UNEARNED",
        "NONPAY_LAPSE",
        "OVERPAYMENT_VARIANCE",
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["recovered_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert data["status"] in ("PENDING", "RECOVERED", "WRITTEN_OFF")


def assert_producer_disclosure(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["projected_comp_cents"], int)
    assert data["status"] in ("GENERATED", "DELIVERED", "ACKNOWLEDGED")


def assert_producer_payout(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("INITIATED", "PAID")


def assert_tax_form_1099(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["cash_basis_total_cents"], int)
    assert isinstance(data["accrual_basis_total_cents"], int)
    assert data["status"] in ("DRAFT", "FINALIZED")


def find_line(statement: dict, line_ref: str) -> dict:
    """Return the statement line with the given line_ref."""
    for line in statement.get("lines", []):
        if line.get("line_ref") == line_ref:
            return line
    raise AssertionError(
        f"line_ref {line_ref!r} not found in statement lines: {statement.get('lines')!r}"
    )
