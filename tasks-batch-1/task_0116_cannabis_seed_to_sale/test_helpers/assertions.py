"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) validates the shape and field invariants of one
returned resource. Principal resources carry id/created_at/updated_at/version;
append-only and child records carry only id/created_at.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)

LICENSE_TYPES = {"CULTIVATION", "MANUFACTURING", "RETAIL", "TESTING", "DISTRIBUTION"}
LICENSE_STATUSES = {"ACTIVE", "SUSPENDED", "REVOKED"}
PLANT_BATCH_STATUSES = {"IMMATURE", "VEGETATIVE", "FLOWERING", "HARVESTED", "DESTROYED"}
HARVEST_STATUSES = {"DRYING", "CURED", "FINISHED"}
PACKAGE_STATUSES = {
    "TESTING", "PASSED", "FAILED", "ON_HOLD", "ACTIVE",
    "IN_TRANSIT", "DEPLETED", "DESTROYED",
}
PRODUCT_CATEGORIES = {"FLOWER", "CONCENTRATE", "EDIBLE"}
MANIFEST_STATUSES = {"DRAFT", "IN_TRANSIT", "RECEIVED", "REJECTED", "VOIDED"}
SALE_STATUSES = {"OPEN", "FINALIZED", "VOIDED"}
RECON_OUTCOMES = {"MATCH", "DISCREPANCY"}
LAB_OUTCOMES = {"PASS", "FAIL"}
WASTE_SOURCE_TYPES = {"PLANT_BATCH", "PACKAGE"}
WASTE_REASONS = {"MOLD", "PEST", "FAILED_TEST", "EXPIRED", "OTHER"}


def _assert_common(data: dict):
    """id (non-prefixed UUID) + created_at (ISO 8601) — every resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a non-prefixed UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    """updated_at + version — principal resources only."""
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be int >= 1"


def assert_no_version_fields(data: dict):
    """Append-only / child records carry neither updated_at nor version."""
    assert "version" not in data, "append-only record must NOT expose a version field"
    assert "updated_at" not in data, "append-only record must NOT expose an updated_at field"


def assert_license(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["license_number"], str) and len(data["license_number"]) > 0
    assert data["license_type"] in LICENSE_TYPES, f"bad license_type {data.get('license_type')!r}"
    assert data["status"] in LICENSE_STATUSES, f"bad status {data.get('status')!r}"
    assert isinstance(data["daily_purchase_limit_grams"], (int, float))
    assert data["daily_purchase_limit_grams"] >= 0


def assert_plant_batch(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["lot_tag"], str) and len(data["lot_tag"]) > 0
    assert data["status"] in PLANT_BATCH_STATUSES, f"bad status {data.get('status')!r}"
    assert isinstance(data["plant_count"], int)
    assert isinstance(data["live_plant_count"], int)
    assert data["live_plant_count"] >= 0
    assert data["live_plant_count"] <= data["plant_count"]


def assert_harvest(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["status"] in HARVEST_STATUSES, f"bad status {data.get('status')!r}"
    assert isinstance(data["wet_weight_grams"], (int, float)) and data["wet_weight_grams"] > 0


def assert_package(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["package_tag"], str) and len(data["package_tag"]) > 0
    assert data["product_category"] in PRODUCT_CATEGORIES, f"bad category {data.get('product_category')!r}"
    assert data["status"] in PACKAGE_STATUSES, f"bad status {data.get('status')!r}"
    assert isinstance(data["remaining_grams"], (int, float))
    assert data["remaining_grams"] >= 0
    assert isinstance(data["lab_hold"], bool)


def assert_lab_result(data: dict):
    _assert_common(data)
    assert_no_version_fields(data)
    assert data["overall_result"] in LAB_OUTCOMES, f"bad overall_result {data.get('overall_result')!r}"
    assert isinstance(data["pesticide_pass"], bool)


def assert_manifest(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["status"] in MANIFEST_STATUSES, f"bad status {data.get('status')!r}"
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    assert isinstance(data["total_grams"], (int, float)) and data["total_grams"] >= 0


def assert_manifest_line(data: dict):
    _assert_common(data)
    assert_no_version_fields(data)
    assert isinstance(data["grams"], (int, float)) and data["grams"] > 0


def assert_customer(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert isinstance(data["is_medical"], bool)


def assert_sale(data: dict):
    _assert_common(data)
    _assert_versioned(data)
    assert data["status"] in SALE_STATUSES, f"bad status {data.get('status')!r}"
    assert isinstance(data["flower_equiv_grams"], (int, float)) and data["flower_equiv_grams"] >= 0


def assert_sale_line(data: dict):
    _assert_common(data)
    assert_no_version_fields(data)
    assert isinstance(data["grams"], (int, float)) and data["grams"] > 0
    assert isinstance(data["flower_equiv_grams"], (int, float)) and data["flower_equiv_grams"] >= 0


def assert_reconciliation_count(data: dict):
    _assert_common(data)
    assert_no_version_fields(data)
    assert data["outcome"] in RECON_OUTCOMES, f"bad outcome {data.get('outcome')!r}"
    assert isinstance(data["variance_grams"], (int, float))


def assert_waste_event(data: dict):
    _assert_common(data)
    assert_no_version_fields(data)
    assert data["source_type"] in WASTE_SOURCE_TYPES, f"bad source_type {data.get('source_type')!r}"
    assert data["reason"] in WASTE_REASONS, f"bad reason {data.get('reason')!r}"
