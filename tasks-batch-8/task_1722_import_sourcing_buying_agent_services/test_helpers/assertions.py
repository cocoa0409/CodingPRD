"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """Fields every persisted entity carries (PRD common-resource section)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_buyer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["ytd_gmv_cents"], int)
    assert data["status"] == "ACTIVE"


def assert_agent(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert isinstance(data["commission_ytd_cents"], int)


def assert_factory(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert isinstance(data["monthly_capacity_units"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["compliance_posture"] in ("COMPLIANT", "NON_COMPLIANT")
    assert isinstance(data["debit_balance_cents"], int)
    assert data["latest_audit_grade"] in ("A", "B", "C", "D", "NONE")
    assert isinstance(data["audit_score"], int)


def assert_inspector(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]


def assert_factory_audit(data: dict):
    assert_common_fields(data)
    assert data["audit_type"] in ("SCREENING", "ONSITE")
    for field in (
        "quality_system_score",
        "social_compliance_score",
        "production_capability_score",
        "financial_stability_score",
        "critical_findings",
        "score",
    ):
        assert isinstance(data[field], int), f"{field} must be int"
    assert data["grade"] in ("A", "B", "C", "D")
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED")


def assert_compliance_document(data: dict):
    assert_common_fields(data)
    assert data["doc_type"] in ("SOCIAL_AUDIT", "PRODUCT_TEST", "LAB_TEST", "FIRE_SAFETY")
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED", "EXPIRED")


def assert_sourcing_request(data: dict):
    assert_common_fields(data)
    assert data["product_category"] in ("APPAREL", "ELECTRONICS", "TOYS", "FURNITURE")
    assert data["commission_mode"] in ("FOB", "CIF")
    assert isinstance(data["target_price_cents"], int)
    assert isinstance(data["quantity"], int)
    assert data["status"] in ("OPEN", "IN_PROGRESS", "PO_PLACED", "COMPLETED", "CANCELLED")


def assert_sample(data: dict):
    assert_common_fields(data)
    assert isinstance(data["revision_count"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REVISION_REQUESTED", "REJECTED")


def assert_quotation(data: dict):
    assert_common_fields(data)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["moq"], int)
    assert isinstance(data["round_count"], int)
    assert data["last_actor_role"] in ("FACTORY", "BUYER")
    assert data["status"] in ("OPEN", "COUNTERED", "ACCEPTED", "REJECTED", "EXPIRED")


def assert_purchase_order(data: dict):
    assert_common_fields(data)
    for field in (
        "ordered_qty",
        "unit_price_cents",
        "total_cents",
        "shipped_qty",
        "cancelled_qty",
        "open_qty",
        "progress_pct",
        "commission_rate_bp",
        "remaining_payable_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be int"
    assert isinstance(data["milestone_plan_locked"], bool)
    assert isinstance(data["ship_blocked"], bool)
    assert data["status"] in ("ACTIVE", "PARTIALLY_SHIPPED", "SHIPPED", "CLOSED", "CANCELLED")
    assert data["production_status"] in ("PLACED", "IN_PRODUCTION", "PRODUCTION_COMPLETE")
    assert data["latest_psi_result"] in ("NONE", "PASSED", "FAILED")
    assert data["document_status"] in ("PENDING", "HANDED_OVER")


def assert_production_milestone(data: dict):
    assert_common_fields(data)
    assert isinstance(data["weight_pct"], int)
    assert data["status"] in ("PLANNED", "SUBMITTED", "VERIFIED", "REJECTED")


def assert_inspection(data: dict):
    assert_common_fields(data)
    assert data["inspection_type"] in ("DUPRO", "PSI")
    assert isinstance(data["duration_days"], int)
    assert isinstance(data["lot_size"], int)
    assert isinstance(data["sample_size"], int)
    assert data["result"] in ("NONE", "PASSED", "FAILED")
    assert data["status"] in ("BOOKED", "RESULT_RECORDED", "CANCELLED")


def assert_shipment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["shipped_qty"], int)
    assert data["status"] in ("BOOKED", "DOCS_HANDED_OVER", "DELIVERED", "CANCELLED")


def assert_quality_claim(data: dict):
    assert_common_fields(data)
    assert isinstance(data["base_amount_cents"], int)
    assert isinstance(data["defective_qty"], int)
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["total_chargeback_cents"], int)
    assert data["status"] in ("FILED", "APPROVED", "REJECTED")


def assert_po_unit_conservation(po: dict):
    """PRD: the invariant `ordered == shipped + cancelled + open` holds
    throughout the lifecycle."""
    ordered = po["ordered_qty"]
    shipped = po["shipped_qty"]
    cancelled = po["cancelled_qty"]
    open_qty = po["open_qty"]
    assert ordered == shipped + cancelled + open_qty, (
        f"unit conservation violated: ordered {ordered} != shipped {shipped} "
        f"+ cancelled {cancelled} + open {open_qty}"
    )
    assert open_qty == ordered - shipped - cancelled


def assert_chargeback_zero_sum(factory: dict, buyer: dict, expected_total: int):
    """PRD: the buyer's credit_balance_cents increases by the same amount as
    the factory's debit_balance_cents — the zero-sum counterpart."""
    assert factory["debit_balance_cents"] == expected_total, (
        f"factory debit {factory['debit_balance_cents']} != expected {expected_total}"
    )
    assert buyer["credit_balance_cents"] == expected_total, (
        f"buyer credit {buyer['credit_balance_cents']} != expected {expected_total}"
    )
    assert factory["debit_balance_cents"] - buyer["credit_balance_cents"] == 0
