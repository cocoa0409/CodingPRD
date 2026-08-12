"""Entity assertions and domain invariant checkers (PRD §2.4, §2.11, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity_label: str):
    """Standard resource envelope per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer >= 1"
    )


def _assert_append_only_fields(data: dict, entity_label: str):
    """Append-only records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity_label} is append-only; updated_at must be absent"
    assert "version" not in data, f"{entity_label} is append-only; version must be absent"


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["external_ref"], str) and data["external_ref"]


def assert_contract(data: dict):
    _assert_common_fields(data, "Contract")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["contract_ref"], str) and data["contract_ref"]
    assert isinstance(data["signed_date"], str) and data["signed_date"]
    assert data["risk_tier"] in ("STANDARD", "ELEVATED", "HIGH")
    assert isinstance(data["package_negotiated_flag"], bool)
    assert isinstance(data["fixed_consideration_cents"], int)
    assert isinstance(data["vc_estimate_cents"], int)
    assert isinstance(data["transaction_price_cents"], int)
    assert data["status"] in (
        "DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "ACTIVE",
        "ON_HOLD", "COMPLETED", "CANCELLED", "ABSORBED",
    )


def assert_pob(data: dict):
    _assert_common_fields(data, "PerformanceObligation")
    assert is_valid_uuid(data.get("contract_id", ""))
    assert isinstance(data["pob_ref"], str) and data["pob_ref"]
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["region"], str) and data["region"]
    assert data["recognition_pattern"] in (
        "POINT_IN_TIME", "OVER_TIME_INPUT_COST", "OVER_TIME_STRAIGHT_LINE"
    )
    assert isinstance(data["ssp_cents"], int)
    assert isinstance(data["allocated_amount_cents"], int)
    assert isinstance(data["recognized_revenue_cents"], int)
    assert isinstance(data["costs_incurred_to_date_cents"], int)
    assert data["status"] in ("PENDING", "IN_PROGRESS", "SATISFIED", "CANCELLED")


def assert_ssp_price(data: dict):
    _assert_common_fields(data, "SspPrice")
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["ssp_cents"], int) and data["ssp_cents"] > 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_vc_estimate(data: dict):
    _assert_common_fields(data, "VariableConsiderationEstimate")
    assert data["method"] in ("EXPECTED_VALUE", "MOST_LIKELY")
    assert isinstance(data["unconstrained_amount_cents"], int)
    assert isinstance(data["constrained_amount_cents"], int)
    assert data["status"] in ("PROPOSED", "APPROVED", "REJECTED", "SUPERSEDED")
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]


def assert_modification(data: dict):
    _assert_common_fields(data, "ContractModification")
    assert data["mod_type"] in ("CUMULATIVE_CATCH_UP", "PROSPECTIVE", "SEPARATE_CONTRACT")
    assert isinstance(data["delta_fixed_consideration_cents"], int)
    assert data["delta_fixed_consideration_cents"] != 0
    assert data["status"] in ("PROPOSED", "APPROVED", "REJECTED")
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"]


def assert_clause(data: dict):
    _assert_common_fields(data, "ContractClause")
    assert isinstance(data["clause_code"], str) and data["clause_code"]
    assert data["clause_type"] in (
        "TERMINATION_FOR_CONVENIENCE", "EXTENDED_PAYMENT_TERMS", "PENALTY",
        "RIGHT_OF_RETURN", "ACCEPTANCE_CLAUSE", "MOST_FAVORED_CUSTOMER",
    )
    assert isinstance(data["is_non_standard"], bool)
    assert data["status"] in ("PENDING_REVIEW", "APPROVED", "REJECTED")


def assert_review_task(data: dict):
    _assert_common_fields(data, "ReviewTask")
    assert data["status"] in ("ASSIGNED", "IN_REVIEW", "RECOMMENDED", "DECIDED")


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert isinstance(data["invoice_ref"], str) and data["invoice_ref"]
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("ISSUED", "VOIDED")


def assert_accounting_period(data: dict):
    _assert_common_fields(data, "AccountingPeriod")
    assert isinstance(data["period_code"], str) and data["period_code"]
    assert isinstance(data["start_date"], str) and data["start_date"]
    assert isinstance(data["end_date"], str) and data["end_date"]
    assert data["status"] in ("OPEN", "CLOSED", "REOPENED")
    assert isinstance(data["reopened_once"], bool)
    assert isinstance(data["recognized_total_cents"], int)


def assert_revenue_entry(data: dict):
    _assert_append_only_fields(data, "RevenueEntry")
    assert data["entry_type"] in ("RECOGNITION", "CATCH_UP_ADJUSTMENT", "REVERSAL")
    assert isinstance(data["amount_cents"], int)
    assert data["origin"] in (
        "COST_ENTRY", "RECOGNIZE", "SATISFY", "MODIFICATION", "ESTIMATE", "REVERSAL"
    )
    assert data["status"] in ("POSTED", "LOCKED")
    assert isinstance(data["posting_date"], str) and data["posting_date"]


def assert_cost_entry(data: dict):
    _assert_append_only_fields(data, "CostEntry")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["incurred_date"], str) and data["incurred_date"]


def assert_disclosure_pack(data: dict):
    _assert_common_fields(data, "DisclosurePack")
    assert data["status"] in ("DRAFT", "ASSEMBLED", "FINALIZED", "SUPERSEDED")


def assert_contract_ledger_identity(data: dict):
    """PRD §2.11: billed - recognized == deferred - contract asset, floored at 0."""
    billed = data["billed_to_date_cents"]
    recognized = data["recognized_to_date_cents"]
    deferred = data["deferred_revenue_balance_cents"]
    asset = data["contract_asset_balance_cents"]
    assert deferred >= 0 and asset >= 0, "balances may never be negative (PRD §2.11)"
    assert not (deferred > 0 and asset > 0), (
        "both balances can never be positive at once (PRD §2.11)"
    )
    assert billed - recognized == deferred - asset, (
        f"ledger identity broken: {billed} - {recognized} != {deferred} - {asset}"
    )
    assert deferred == max(0, billed - recognized)
    assert asset == max(0, recognized - billed)
