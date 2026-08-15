"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """Common resource properties per PRD §2.5."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer counter"


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["vendor_code"], str) and data["vendor_code"]
    assert data["default_license_metric"] in ("PER_INSTALL", "PER_USER", "PER_CORE")
    assert isinstance(data["notice_response_deadline_days"], int)
    assert data["notice_response_deadline_days"] > 0


def assert_product(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["vendor_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["license_metric"] in ("PER_INSTALL", "PER_USER", "PER_CORE")
    assert isinstance(data["unit_list_price_cents"], int) and data["unit_list_price_cents"] > 0
    assert isinstance(data["support_rate_pct"], (int, float))
    assert 0 <= data["support_rate_pct"] <= 1
    assert isinstance(data["mission_critical"], bool)
    assert isinstance(data["counts_non_production"], bool)


def assert_entitlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["purchase_order_number"], str) and data["purchase_order_number"]
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["coverage_class"] in ("PRODUCTION", "NON_PRODUCTION", "DISASTER_RECOVERY")
    assert is_iso8601_timestamp(data["effective_from"])
    if data.get("effective_to") is not None:
        assert is_iso8601_timestamp(data["effective_to"])
    assert data["source"] in ("MANUAL_IMPORT", "CONTRACT_EXTRACT", "AUTO_TRUE_UP")
    assert data["status"] in ("SCHEDULED", "ACTIVE", "EXPIRED", "VOID")


def assert_deployment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["measured_quantity"], int) and data["measured_quantity"] > 0
    assert data["environment"] in ("PRODUCTION", "NON_PRODUCTION")
    assert data["measurement_method"] in ("SCAN", "MANUAL_DECLARATION")
    assert is_iso8601_timestamp(data["measured_on"])
    assert data["status"] in ("REPORTED", "CONFIRMED", "REJECTED", "EXCLUDED")
    if data.get("excluded_by_remediation_id") is not None:
        assert is_valid_uuid(data["excluded_by_remediation_id"])


def assert_license_position(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["entitled_quantity"], int)
    assert isinstance(data["deployed_quantity"], int)
    assert isinstance(data["gap_quantity"], int)
    assert data["gap_quantity"] == data["deployed_quantity"] - data["entitled_quantity"], \
        "gap_quantity must equal deployed_quantity - entitled_quantity"
    assert data["gap_severity"] in ("COMPLIANT", "MINOR", "MATERIAL", "CRITICAL")
    assert isinstance(data["self_audit_exposure_cents"], int)
    assert isinstance(data["vendor_list_exposure_cents"], int)
    assert data["position_basis"] in ("SELF_AUDIT", "VENDOR_MEASURED", "AGREED")


def assert_audit_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["vendor_id"])
    assert isinstance(data["audit_firm_name"], str) and data["audit_firm_name"]
    assert is_iso8601_timestamp(data["notice_received_on"])
    assert is_iso8601_timestamp(data["response_deadline_on"])
    assert data["status"] in (
        "NOTICE_RECEIVED", "SCOPE_NEGOTIATION", "EVIDENCE_COLLECTION", "FINDINGS_REVIEW",
        "SETTLEMENT_NEGOTIATION", "CLOSED_SETTLED", "CLOSED_NO_ACTION", "WITHDRAWN",
    )
    assert isinstance(data["provisional_case_exposure_cents"], int)
    assert isinstance(data["worst_case_exposure_cents"], int)
    if data.get("settled_amount_cents") is not None:
        assert isinstance(data["settled_amount_cents"], int)
    if data.get("accepted_future_discount_pct") is not None:
        assert isinstance(data["accepted_future_discount_pct"], (int, float))
    if data.get("last_tendered_offer_id") is not None:
        assert is_valid_uuid(data["last_tendered_offer_id"])


def assert_scope_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["audit_case_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["proposed_by"] in ("VENDOR", "CUSTOMER")
    assert isinstance(data["inclusion_rationale"], str)
    if data.get("dispute_rationale") is not None:
        assert isinstance(data["dispute_rationale"], str)
    assert data["scope_status"] in ("PROPOSED", "CONFIRMED", "DISPUTED", "EXCLUDED")
    if data.get("vendor_finding_amount_cents") is not None:
        assert isinstance(data["vendor_finding_amount_cents"], int)


def assert_submission(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["audit_case_id"])
    assert isinstance(data["submission_label"], str) and data["submission_label"]
    assert isinstance(data["covered_scope_item_ids"], list)
    assert len(data["covered_scope_item_ids"]) > 0
    assert isinstance(data["contains_privileged"], bool)
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    assert data["status"] in ("DRAFT", "PRIVILEGE_REVIEW", "APPROVED", "RELEASED")
    if data.get("released_on") is not None:
        assert is_iso8601_timestamp(data["released_on"])
    if data.get("released_exposure_cents") is not None:
        assert isinstance(data["released_exposure_cents"], int)


def assert_offer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["audit_case_id"])
    assert data["offered_by"] in ("CUSTOMER", "VENDOR")
    assert isinstance(data["tendered_by_user_id"], str) and data["tendered_by_user_id"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["future_license_discount_pct"], (int, float))
    assert 0 <= data["future_license_discount_pct"] <= 0.5
    assert data["status"] in ("TENDERED", "ACCEPTED", "WITHDRAWN", "SUPERSEDED")
    if data.get("supersedes_offer_id") is not None:
        assert is_valid_uuid(data["supersedes_offer_id"])


def assert_remediation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert data["action_type"] in ("UNINSTALL", "PURCHASE_TRUE_UP")
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["status"] in ("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    if data.get("generated_entitlement_id") is not None:
        assert is_valid_uuid(data["generated_entitlement_id"])


def assert_alert(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert data["alert_type"] in ("OVER_DEPLOYMENT", "ENTITLEMENT_EXPIRING")
    assert data["severity"] in ("INFO", "WARNING", "CRITICAL")
    assert data["status"] in ("OPEN", "SUPPRESSED", "RESOLVED")
    assert isinstance(data["triggered_value"], (int, float))
    assert isinstance(data["threshold_value"], (int, float))
    if data.get("suppressed_value") is not None:
        assert isinstance(data["suppressed_value"], (int, float))
