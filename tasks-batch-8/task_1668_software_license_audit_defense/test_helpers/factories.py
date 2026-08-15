"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "VENDOR_NAME": "Vendor A",
    "VENDOR_CODE": "VND-A",
    "DEFAULT_LICENSE_METRIC": "PER_INSTALL",
    "PRODUCT_NAME": "Prod",
    "UNIT_LIST_PRICE_CENTS": 10000,
    "SUPPORT_RATE_PCT": 0.22,
    "PURCHASE_ORDER_NUMBER": "PO-1",
    "QUANTITY": 100,
    "COVERAGE_CLASS": "PRODUCTION",
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "ENTITLEMENT_SOURCE": "MANUAL_IMPORT",
    "MEASURED_QUANTITY": 10,
    "ENVIRONMENT": "PRODUCTION",
    "MEASUREMENT_METHOD": "SCAN",
    "MEASURED_ON": "2026-07-15T00:00:00Z",
    "AUDIT_FIRM_NAME": "AuditCo LLP",
    "NOTICE_RECEIVED_ON": "2026-08-01T00:00:00Z",
    "INCLUSION_RATIONALE": "Vendor believes the product is deployed enterprise-wide",
    "SUBMISSION_LABEL": "Usage extract",
    "SUPPRESSION_REASON": "True-up purchase order already submitted",
    "RETURN_REASON": "Contains internal legal memo; redact before release",
    "DISPUTE_RATIONALE": "Retired product line, contract excludes it",
}


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VENDOR_NAME"],
        "vendor_code": DEFAULTS["VENDOR_CODE"],
        "default_license_metric": DEFAULTS["DEFAULT_LICENSE_METRIC"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(vendor_id: str, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "name": DEFAULTS["PRODUCT_NAME"],
        "license_metric": DEFAULTS["DEFAULT_LICENSE_METRIC"],
        "unit_list_price_cents": DEFAULTS["UNIT_LIST_PRICE_CENTS"],
        "support_rate_pct": DEFAULTS["SUPPORT_RATE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_entitlement_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "purchase_order_number": DEFAULTS["PURCHASE_ORDER_NUMBER"],
        "quantity": DEFAULTS["QUANTITY"],
        "coverage_class": DEFAULTS["COVERAGE_CLASS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "source": DEFAULTS["ENTITLEMENT_SOURCE"],
    }
    defaults.update(overrides)
    return defaults


def create_deployment_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "measured_quantity": DEFAULTS["MEASURED_QUANTITY"],
        "environment": DEFAULTS["ENVIRONMENT"],
        "measurement_method": DEFAULTS["MEASUREMENT_METHOD"],
        "measured_on": DEFAULTS["MEASURED_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_case_payload(vendor_id: str, **overrides) -> dict:
    defaults = {
        "vendor_id": vendor_id,
        "audit_firm_name": DEFAULTS["AUDIT_FIRM_NAME"],
        "notice_received_on": DEFAULTS["NOTICE_RECEIVED_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_scope_item_payload(audit_case_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "audit_case_id": audit_case_id,
        "product_id": product_id,
        "inclusion_rationale": DEFAULTS["INCLUSION_RATIONALE"],
    }
    defaults.update(overrides)
    return defaults


def create_data_submission_payload(audit_case_id: str, covered_scope_item_ids, **overrides) -> dict:
    defaults = {
        "audit_case_id": audit_case_id,
        "submission_label": DEFAULTS["SUBMISSION_LABEL"],
        "covered_scope_item_ids": list(covered_scope_item_ids),
    }
    defaults.update(overrides)
    return defaults


def create_settlement_offer_payload(audit_case_id: str, offered_by: str, amount_cents: int,
                                    expected_audit_case_version: int, **overrides) -> dict:
    defaults = {
        "audit_case_id": audit_case_id,
        "offered_by": offered_by,
        "amount_cents": amount_cents,
        "expected_audit_case_version": expected_audit_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_remediation_payload(product_id: str, action_type: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "action_type": action_type,
    }
    defaults.update(overrides)
    return defaults
