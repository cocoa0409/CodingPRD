"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_fiscal_year(data: dict):
    """Validate a FiscalYear response against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["year_index"], int)
    assert isinstance(data["group_revenue_eur"], int)
    assert isinstance(data["cbc_required"], bool)
    assert data["status"] in ["OPEN", "CLOSING", "CLOSED"]
    assert isinstance(data["consolidated_intercompany_net_cents"], int)


def assert_legal_entity(data: dict):
    """Validate a LegalEntity response against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["country_code"], str)
    assert isinstance(data["functional_currency"], str)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_agreement(data: dict):
    """Validate an IntercompanyAgreement response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("provider_entity_id", ""))
    assert is_valid_uuid(data.get("recipient_entity_id", ""))
    assert data["transaction_type"] in [
        "GOODS", "SERVICES", "IP_ROYALTY", "FINANCING", "COST_SHARING"]
    assert data["pricing_method"] in ["COST_PLUS", "TNMM", "RESALE_MINUS",
                                      "CUP"]
    assert data["true_up_method"] in ["TO_MEDIAN", "TO_RANGE_EDGE"]
    assert data["status"] in ["DRAFT", "ACTIVE", "UNDER_AMENDMENT",
                              "TERMINATED"]
    assert isinstance(data["amendments_count"], int)
    assert isinstance(data["pricing_review_required"], bool)
    assert isinstance(data["apa_locked"], bool)


def assert_transaction(data: dict):
    """Validate an ICTransaction response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert is_valid_uuid(data.get("fiscal_year_id", ""))
    assert isinstance(data["cost_base_cents"], int)
    assert isinstance(data["provider_revenue_cents"], int)
    assert isinstance(data["recipient_cost_cents"], int)
    assert isinstance(data["is_true_up_adjustment"], bool)
    assert isinstance(data["provisional_al_price_cents"], int)
    assert isinstance(data["margin_bp"], int)
    assert data["elimination_status"] in ["UNMATCHED", "MATCHED", "ELIMINATED"]
    assert data["settlement_status"] in ["UNSETTLED", "NETTED", "SETTLED"]


def assert_true_up_run(data: dict):
    """Validate a TrueUpRun response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert is_valid_uuid(data.get("fiscal_year_id", ""))
    assert data["status"] in ["DRAFT", "COMPUTED", "APPROVED", "POSTED"]


def assert_benchmarking_study(data: dict):
    """Validate a BenchmarkingStudy response against the PRD contract."""
    _assert_common_fields(data)
    assert data["transaction_type"] in [
        "GOODS", "SERVICES", "IP_ROYALTY", "FINANCING", "COST_SHARING"]
    assert isinstance(data["region"], str)
    assert isinstance(data["vintage_year"], int)
    assert isinstance(data["comparables_bp"], list)
    assert data["status"] in ["DRAFT", "CURRENT", "STALE", "SUPERSEDED"]


def assert_doc_package(data: dict):
    """Validate a DocPackage response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fiscal_year_id", ""))
    assert data["doc_type"] in ["MASTER_FILE", "LOCAL_FILE", "CBC_REPORT"]
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "FILED"]


def assert_audit_case(data: dict):
    """Validate an AuditCase response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("entity_id", ""))
    assert data["case_type"] in ["AUDIT", "APA"]
    assert isinstance(data["authority_country"], str)
    assert isinstance(data["defense_doc_ids"], list)
    assert data["status"] in ["OPENED", "ACTIVE_PREP",
                              "SUBMITTED_TO_AUTHORITY", "CLOSED_RESOLVED",
                              "CLOSED_AGREED"]


def assert_cash_pool(data: dict):
    """Validate a CashPool response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("fiscal_year_id", ""))
    assert data["interest_method"] in ["AVERAGE_BALANCE", "CLOSING_BALANCE"]
    assert isinstance(data["admin_fee_cents"], int)
    assert data["status"] in ["OPEN", "NETTING", "SETTLED"]
    assert isinstance(data["positions"], list)
    for position in data["positions"]:
        assert_position(position)


def assert_position(position: dict):
    """Validate one cash-pool position object."""
    assert is_valid_uuid(position.get("entity_id", ""))
    assert isinstance(position["balance_cents"], int)
    assert isinstance(position["accrued_balance_day_cents"], int)
    assert isinstance(position["pending_cents"], int)
    assert isinstance(position["interest_cents"], int)
    assert isinstance(position["fee_cents"], int)


def find_position(pool_data: dict, entity_id: str) -> dict:
    """Return the position object for entity_id; fail if absent."""
    for position in pool_data.get("positions", []):
        if position.get("entity_id") == entity_id:
            return position
    raise AssertionError(
        f"No position for entity {entity_id} in pool {pool_data.get('id')}")


def assert_pool_zero_sum(pool_data: dict):
    """Domain invariant: positions are zero-sum in aggregate (PRD 3.8)."""
    total = sum(p["balance_cents"] for p in pool_data.get("positions", []))
    assert total == 0, f"pool positions must sum to 0, got {total}"
