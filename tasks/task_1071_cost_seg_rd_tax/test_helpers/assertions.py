"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CLIENT_STATUSES = ["ONBOARDING", "ACTIVE"]
STUDY_STATUSES = ["DRAFT", "SCOPING", "ENGINEERING", "IN_REVIEW",
                  "FINALIZED", "DELIVERED", "CANCELLED"]
ASSET_COMPONENT_STATUSES = ["PROPOSED", "ALLOCATED", "EXCLUDED"]
QRE_STATUSES = ["DRAFT", "QUALIFIED"]
REPORT_STATUSES = ["DRAFT", "REVISION_REQUESTED", "ISSUED", "SUPERSEDED"]
AUDIT_STATUSES = ["OPEN", "RESOLVED"]
AMENDED_STATUSES = ["DRAFT", "FILED"]
FEE_INVOICE_STATUSES = ["ISSUED", "PAID", "VOID"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_mutable_common(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be a positive int"


def assert_client(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["entity_type"] in ["C_CORP", "S_CORP", "PARTNERSHIP", "INDIVIDUAL"]
    assert 0 <= data["marginal_tax_rate"] <= 1
    assert data["status"] in CLIENT_STATUSES
    assert isinstance(data["outstanding_fee_cents"], int)


def assert_property(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["client_id"], str)
    assert data["building_type"] in ["COMMERCIAL", "RESIDENTIAL_RENTAL", "INDUSTRIAL"]
    assert data["purchase_price_cents"] > 0
    assert 0 <= data["land_value_cents"] < data["purchase_price_cents"]
    assert data["depreciable_basis_cents"] == data["purchase_price_cents"] - data["land_value_cents"]


def assert_engineer(data: dict):
    # Engineer is append-only: id + created_at only, NO updated_at / version.
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert "updated_at" not in data, "Engineer is immutable and must not carry updated_at"
    assert "version" not in data, "Engineer is immutable and must not carry version"


def assert_study(data: dict):
    _assert_mutable_common(data)
    assert data["study_type"] in ["COST_SEGREGATION", "RD_CREDIT"]
    assert data["status"] in STUDY_STATUSES
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["is_look_back"], bool)


def assert_asset_component(data: dict):
    _assert_mutable_common(data)
    assert data["asset_class"] in ["FIVE_YEAR", "SEVEN_YEAR", "FIFTEEN_YEAR", "THIRTY_NINE_YEAR"]
    assert data["allocated_cost_cents"] > 0
    assert data["status"] in ASSET_COMPONENT_STATUSES


def assert_qre_line_item(data: dict):
    _assert_mutable_common(data)
    assert data["qre_category"] in ["WAGES", "SUPPLIES", "CONTRACT_RESEARCH"]
    assert data["gross_amount_cents"] > 0
    assert data["status"] in QRE_STATUSES


def assert_report(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in REPORT_STATUSES
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_fee_invoice(data: dict):
    _assert_mutable_common(data)
    assert data["fee_basis"] in ["FIXED", "PERCENT"]
    assert data["status"] in FEE_INVOICE_STATUSES
    assert isinstance(data["amount_cents"], int)


def assert_amended_return(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in AMENDED_STATUSES


def assert_audit_case(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in AUDIT_STATUSES
