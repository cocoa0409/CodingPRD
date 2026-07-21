"""Entity assertions and domain invariant checkers for the property-tax appeal API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_analyst(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["license_number"], str)
    assert isinstance(data["active"], bool)


def assert_client(data: dict):
    _assert_common(data)
    assert data["entity_type"] in ("INDIVIDUAL", "BUSINESS")
    assert isinstance(data["portal_enabled"], bool)
    assert isinstance(data["lifetime_fees_billed_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_jurisdiction(data: dict):
    _assert_common(data)
    assert isinstance(data["filing_window_days"], int) and data["filing_window_days"] >= 1
    assert 0 < data["equalization_ratio"] <= 1


def assert_fee_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE")
    assert isinstance(data["minimum_fee_cents"], int)


def assert_parcel(data: dict):
    _assert_common(data)
    assert data["property_class"] in ("RESIDENTIAL", "COMMERCIAL", "INDUSTRIAL", "LAND")


def assert_assessment(data: dict):
    _assert_common(data)
    assert data["status"] in ("NOTICED", "UNDER_APPEAL", "FINALIZED")
    assert isinstance(data["original_assessed_value_cents"], int)
    assert isinstance(data["assessed_value_cents"], int)
    assert isinstance(data["projected_annual_tax_cents"], int)
    assert data["projected_annual_tax_cents"] >= 0, "projected annual tax floored at 0"


def assert_exemption_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "DENIED")
    assert data["exemption_type"] in ("HOMESTEAD", "SENIOR", "VETERAN", "AGRICULTURAL", "DISABLED")


def assert_appeal(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FILED", "INFORMAL_REVIEW", "HEARING_SCHEDULED",
                              "DECIDED", "SETTLED", "WITHDRAWN")
    assert data["valuation_method"] in ("SALES_COMPARISON", "ASSESSMENT_EQUITY")


def assert_evidence(data: dict):
    _assert_common(data)
    assert isinstance(data["adjusted_sale_value_cents"], int)
    assert isinstance(data["included"], bool)


def assert_hearing(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "HELD", "CANCELLED")


def assert_settlement_offer(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "COUNTERED", "ACCEPTED", "REJECTED")
    assert data["proposed_by"] in ("FIRM", "JURISDICTION")
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")
    assert isinstance(data["gross_savings_cents"], int)
    assert isinstance(data["fee_amount_cents"], int)


def assert_payment_shape(data: dict):
    """Payment is an immutable audit fact: id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "payment id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Payment must not carry a version"
    assert "updated_at" not in data, "Payment must not carry an updated_at"
