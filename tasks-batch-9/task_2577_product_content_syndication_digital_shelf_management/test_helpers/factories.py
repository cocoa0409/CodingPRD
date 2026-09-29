"""Payload factories — one per entity, author-supplied input fields only."""

DEFAULTS = {
    "RETAILER_NAME": "MegaMart",
    "RETAILER_CODE": "MEGA",
    "SKU": "SKU-A-1",
    "GTIN": "00012345678905",
    "CATEGORY_CODE": "SMALL_APPLIANCE",
    "BRAND_CODE": "BRHM",
    "SOURCE_URI": "https://brand.example.com/assets/hero-1.jpg",
    "RATIONALE": "certify the new revision for this retailer",
}


def create_retailer_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["RETAILER_NAME"],
        "retailer_code": DEFAULTS["RETAILER_CODE"],
    }
    payload.update(overrides)
    return payload


def patch_retailer_payload(expected_retailer_version: int, **overrides) -> dict:
    payload = {"expected_retailer_version": expected_retailer_version}
    payload.update(overrides)
    return payload


def create_attribute_definition_payload(**overrides) -> dict:
    payload = {
        "attribute_key": "title",
        "data_type": "STRING",
        "taxonomy_group": "CORE",
        "max_chars": 200,
        "base_weight": 40.00,
    }
    payload.update(overrides)
    return payload


def create_requirement_payload(**overrides) -> dict:
    payload = {
        "attribute_key": "title",
        "requirement_level": "REQUIRED",
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    payload = {
        "sku": DEFAULTS["SKU"],
        "gtin": DEFAULTS["GTIN"],
        "category_code": DEFAULTS["CATEGORY_CODE"],
        "brand_code": DEFAULTS["BRAND_CODE"],
    }
    payload.update(overrides)
    return payload


def create_content_version_payload(product_id: str, **overrides) -> dict:
    payload = {"product_id": product_id}
    payload.update(overrides)
    return payload


def create_attribute_value_payload(attribute_key: str, value: str, **overrides) -> dict:
    payload = {"attribute_key": attribute_key, "value": value}
    payload.update(overrides)
    return payload


def create_media_asset_payload(product_id: str, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "asset_role": "HERO_IMAGE",
        "source_uri": DEFAULTS["SOURCE_URI"],
    }
    payload.update(overrides)
    return payload


def media_decision_payload(decision: str = "APPROVE", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_retailer_listing_payload(product_id: str, retailer_id: str, **overrides) -> dict:
    payload = {"product_id": product_id, "retailer_id": retailer_id}
    payload.update(overrides)
    return payload


def create_observation_payload(**overrides) -> dict:
    payload = {
        "observed_at": "2026-08-11T00:00:00Z",
        "in_stock": True,
        "content_accuracy_pct": 95.00,
        "rating_avg": 4.00,
        "rating_count": 50,
        "unauthorized_seller_count": 0,
        "conversion_rate_pct": 2.00,
        "units_sold": 10,
    }
    payload.update(overrides)
    return payload


def shelf_status_payload(shelf_state: str, **overrides) -> dict:
    payload = {"shelf_state": shelf_state}
    payload.update(overrides)
    return payload


def create_change_request_payload(
    product_id: str, retailer_id: str, target_content_version_id: str, **overrides
) -> dict:
    payload = {
        "product_id": product_id,
        "retailer_id": retailer_id,
        "target_content_version_id": target_content_version_id,
        "rationale": DEFAULTS["RATIONALE"],
    }
    payload.update(overrides)
    return payload


def review_payload(track: str, decision: str, expected_product_version: int, **overrides) -> dict:
    payload = {
        "track": track,
        "decision": decision,
        "expected_product_version": expected_product_version,
    }
    payload.update(overrides)
    return payload


def create_syndication_job_payload(
    retailer_listing_id: str,
    content_version_id: str,
    slot_count: int,
    window_start: str,
    window_end: str,
    expected_retailer_version: int,
    **overrides,
) -> dict:
    payload = {
        "retailer_listing_id": retailer_listing_id,
        "content_version_id": content_version_id,
        "slot_count": slot_count,
        "window_start": window_start,
        "window_end": window_end,
        "expected_retailer_version": expected_retailer_version,
    }
    payload.update(overrides)
    return payload


def retailer_response_payload(outcome: str, errors=None, **overrides) -> dict:
    payload = {"outcome": outcome}
    if errors is not None:
        payload["errors"] = errors
    payload.update(overrides)
    return payload


def rejection_error_row(
    retailer_error_code: str, severity: str, message: str, attribute_key=None
) -> dict:
    row = {
        "retailer_error_code": retailer_error_code,
        "severity": severity,
        "message": message,
    }
    if attribute_key is not None:
        row["attribute_key"] = attribute_key
    return row


def resolve_rejection_error_payload(
    resolution_mode: str, resolution_note: str, **overrides
) -> dict:
    payload = {"resolution_mode": resolution_mode, "resolution_note": resolution_note}
    payload.update(overrides)
    return payload


def requeue_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def create_deployment_payload(
    retailer_listing_id: str,
    change_request_id: str,
    media_asset_id: str,
    module_kind: str,
    window_start: str,
    window_end: str,
    expected_retailer_listing_version: int,
    **overrides,
) -> dict:
    payload = {
        "retailer_listing_id": retailer_listing_id,
        "change_request_id": change_request_id,
        "media_asset_id": media_asset_id,
        "module_kind": module_kind,
        "window_start": window_start,
        "window_end": window_end,
        "expected_retailer_listing_version": expected_retailer_listing_version,
    }
    payload.update(overrides)
    return payload


def deployment_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def withdraw_payload(withdrawn_reason=None) -> dict:
    payload = {}
    if withdrawn_reason is not None:
        payload["withdrawn_reason"] = withdrawn_reason
    return payload


def resolve_alert_payload(resolution_note: str) -> dict:
    return {"resolution_note": resolution_note}


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
