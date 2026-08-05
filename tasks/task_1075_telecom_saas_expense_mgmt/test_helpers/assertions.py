"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["vendor_type"] in ("TELECOM", "SAAS")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("vendor_id", "")), "vendor_id must be UUID"
    assert data["status"] in ("DRAFT", "ACTIVE", "TERMINATED")
    for f in ("monthly_committed_cost_cents", "total_recovered_cents", "renewal_count",
              "renewal_notice_days", "renewal_term_months"):
        assert isinstance(data[f], int), f"{f} must be integer"
    assert isinstance(data["auto_renew"], bool)
    assert isinstance(data["volume_tier_enabled"], bool)


def assert_service(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be UUID"
    assert data["service_type"] in ("TELECOM_LINE", "SAAS_SUBSCRIPTION")
    assert data["license_type"] in ("PER_SEAT", "FLAT", "USAGE_BASED")
    assert data["status"] in ("ACTIVE", "RIGHTSIZED", "RETIRED")
    assert data["discovery_source"] in ("SANCTIONED", "SHADOW_IT")
    for f in ("unit_rate_cents", "contracted_quantity", "active_quantity"):
        assert isinstance(data[f], int), f"{f} must be integer"
    assert isinstance(data["utilization_pct"], (int, float))


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be UUID"
    assert data["status"] in ("RECEIVED", "UNDER_REVIEW", "DISPUTED", "APPROVED", "PAID")
    for f in ("billed_amount_cents", "expected_amount_cents", "variance_cents",
              "net_amount_cents", "balance_due_cents"):
        assert isinstance(data[f], int), f"{f} must be integer"


def assert_line_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("invoice_id", "")), "invoice_id must be UUID"
    assert is_valid_uuid(data.get("service_id", "")), "service_id must be UUID"
    assert data["status"] in ("BILLED", "DISPUTED", "CREDITED")
    for f in ("billed_quantity", "billed_amount_cents", "expected_amount_cents",
              "variance_cents", "credited_amount_cents", "net_amount_cents"):
        assert isinstance(data[f], int), f"{f} must be integer"


def assert_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("invoice_line_item_id", "")), "invoice_line_item_id must be UUID"
    assert data["status"] in ("SUBMITTED", "VENDOR_RESPONDED", "RESUBMITTED", "ACCEPTED", "WITHDRAWN")
    assert data["response_type"] in ("NONE", "FULL_ACCEPT", "PARTIAL", "REJECT")
    for f in ("disputed_amount_cents", "claimed_credit_cents", "offered_credit_cents",
              "recovered_credit_cents", "round_count"):
        assert isinstance(data[f], int), f"{f} must be integer"


def assert_credit(data: dict):
    """Credit is append-only: id + created_at only, NO updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data.get("dispute_id", "")), "dispute_id must be UUID"
    assert is_valid_uuid(data.get("invoice_line_item_id", "")), "invoice_line_item_id must be UUID"
    assert isinstance(data["amount_cents"], int), "amount_cents must be integer"
    assert data["status"] == "ISSUED"


def assert_cost_center(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["gl_account"], str) and len(data["gl_account"]) > 0
    assert isinstance(data["owner_user_id"], str) and len(data["owner_user_id"]) > 0
    assert data["status"] in ("ACTIVE", "FROZEN")


def assert_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("invoice_line_item_id", "")), "invoice_line_item_id must be UUID"
    assert is_valid_uuid(data.get("cost_center_id", "")), "cost_center_id must be UUID"
    assert data["status"] in ("DRAFT", "POSTED", "REVERSED")
    assert isinstance(data["amount_cents"], int), "amount_cents must be integer"
    assert isinstance(data["weight_pct"], (int, float))


def assert_recommendation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("service_id", "")), "service_id must be UUID"
    assert data["rec_type"] in ("DOWNGRADE_SEATS", "TERMINATE", "SANCTION")
    assert data["status"] in ("PROPOSED", "IMPLEMENTED", "REJECTED", "SUPERSEDED")
    for f in ("target_quantity", "projected_savings_cents", "realized_savings_cents"):
        assert isinstance(data[f], int), f"{f} must be integer"


def assert_allocation_sum_conserves_net(allocations: list, expected_net: int):
    """Chargeback invariant (PRD §2.7): Sigma(amount_cents) == line net_amount_cents."""
    total = sum(a["amount_cents"] for a in allocations)
    assert total == expected_net, f"allocation amounts sum to {total}, expected {expected_net}"
