"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_producer(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int)
    assert data["status"] in ("PENDING_VERIFICATION", "REGISTERED", "SUSPENDED")
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["ytd_gross_sales_cents"], int)
    assert data["water_source"] in ("PUBLIC", "PRIVATE_WELL")


def assert_policy(data: dict):
    _common(data)
    # AllowedFoodPolicy is immutable configuration: no updated_at, no version.
    assert "updated_at" not in data, "AllowedFoodPolicy must not carry updated_at"
    assert "version" not in data, "AllowedFoodPolicy must not carry version"
    assert isinstance(data["is_cottage_allowed"], bool)
    assert isinstance(data["class_b_required"], bool)
    assert isinstance(data["requires_allergen_label"], bool)


def assert_product(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int)
    assert data["compliance_status"] in ("DECLARED", "APPROVED", "REJECTED", "RECALLED")
    assert data["label_status"] in ("LABEL_DRAFT", "LABEL_APPROVED", "LABEL_REJECTED")
    assert isinstance(data["unit_price_cents"], int)


def assert_permit(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int)
    assert data["permit_class"] in ("CLASS_A", "CLASS_B")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_INSPECTION", "ISSUED",
        "RENEWAL_PENDING", "SUSPENDED", "REVOKED",
    )
    assert isinstance(data["annual_cap_cents"], int)
    assert isinstance(data["renewal_count"], int)


def assert_inspection(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "PASSED", "FAILED")
    assert data["inspection_type"] in ("ROUTINE", "RENEWAL", "COMPLAINT")


def assert_complaint(data: dict):
    _common(data)
    assert data["status"] in ("RECEIVED", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED")
    assert data["category"] in ("LABELING", "ILLNESS", "UNAPPROVED_FOOD", "SALES_VENUE")


def assert_market(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "CLOSED")
    assert isinstance(data["max_vendors_per_day"], int)
    assert isinstance(data["allowed_classes"], list)


def assert_manifest(data: dict):
    _common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "CHECKED_IN",
        "REJECTED", "WITHDRAWN", "VOIDED",
    )
    assert isinstance(data["booth_fee_cents"], int)


def assert_sales_record(data: dict):
    _common(data)
    assert data["status"] in ("RECORDED", "VOIDED")
    assert isinstance(data["gross_amount_cents"], int)


def assert_recall(data: dict):
    _common(data)
    assert data["status"] in ("INITIATED", "RESOLVED")
    assert data["reason"] in ("ILLNESS_OUTBREAK", "MISLABEL", "CONTAMINATION")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["estimated_liability_cents"], int)
