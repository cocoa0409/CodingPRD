"""Entity assertions and domain invariant checkers.

Every resource carries id / created_at / updated_at / version per the PRD's
common resource properties; created_at and updated_at are ISO 8601 UTC with
three fractional digits.
"""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_TS_3FRAC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

_NUTRIENT_FIELDS = [
    "kcal_per_100g", "fat_g_per_100g", "satfat_g_per_100g", "chol_mg_per_100g",
    "sodium_mg_per_100g", "carb_g_per_100g", "fiber_g_per_100g",
    "sugar_g_per_100g", "protein_g_per_100g",
]

_ALLERGEN_TAGS = [
    "MILK", "EGGS", "FISH", "SHELLFISH", "TREE_NUTS", "PEANUTS", "WHEAT",
    "SOYBEAN", "SESAME",
]


def assert_iso8601_three_fractional(value: str, field: str = "timestamp"):
    """PRD: timestamps are ISO 8601 UTC with three fractional digits."""
    assert is_iso8601_timestamp(value), f"{field} must be ISO 8601 UTC, got {value!r}"
    assert _TS_3FRAC_RE.match(value), (
        f"{field} must carry exactly three fractional digits, got {value!r}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert_iso8601_three_fractional(data.get("created_at", ""), "created_at")
    assert_iso8601_three_fractional(data.get("updated_at", ""), "updated_at")
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["home_market_code"] in ("US_FDA", "CA_CFIA")


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["product_category"] in (
        "BAKED_GOOD", "BEVERAGE", "CEREAL", "SNACK", "DAIRY", "SAUCE",
        "CONFECTION", "FROZEN_DESSERT",
    )
    assert isinstance(data["net_weight_g"], (int, float)) and data["net_weight_g"] > 0
    assert isinstance(data["total_surface_area_sq_in"], (int, float))
    assert data["total_surface_area_sq_in"] > 0
    assert isinstance(data["pdp_area_sq_in"], (int, float)) and data["pdp_area_sq_in"] > 0
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"


def assert_ingredient(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["allergen_tags"], list)
    for tag in data["allergen_tags"]:
        assert tag in _ALLERGEN_TAGS, f"unknown allergen tag {tag!r}"
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"


def assert_recipe(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["status"] in ("DRAFT", "LOCKED", "SUPERSEDED")
    assert isinstance(data["yield_factor"], (int, float))
    assert 0 < data["yield_factor"] <= 1.2
    assert isinstance(data["lines"], list)
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"


def assert_lab_analysis(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_report_ref"], str)
    assert data["status"] in ("SUBMITTED", "VALIDATED", "REJECTED", "SUPERSEDED")
    for field in _NUTRIENT_FIELDS:
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert is_valid_uuid(data.get("recipe_id", "")), "recipe_id must be a UUID"


def assert_nutrient_panel(data: dict):
    _assert_common(data)
    assert data["method"] in ("DATABASE", "LAB")
    assert data["status"] in ("CURRENT", "STALE")
    for field in _NUTRIENT_FIELDS:
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert is_valid_uuid(data.get("recipe_id", "")), "recipe_id must be a UUID"


def assert_racc_assignment(data: dict):
    _assert_common(data)
    assert data["market_code"] in ("US_FDA", "CA_CFIA")
    assert data["label_mode"] in ("SINGLE_SERVING", "DUAL_COLUMN", "STANDARD")
    assert isinstance(data["racc_g"], (int, float)) and data["racc_g"] > 0
    assert isinstance(data["serving_size_g"], (int, float)) and data["serving_size_g"] > 0
    assert isinstance(data["serving_household_units"], (int, float))
    assert data["serving_household_units"] > 0
    assert isinstance(data["servings_per_container"], (int, float))
    assert data["servings_per_container"] > 0
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"


def assert_label_version(data: dict):
    _assert_common(data)
    assert data["market_code"] in ("US_FDA", "CA_CFIA")
    assert data["nutrient_basis"] in ("DATABASE", "LAB")
    assert data["declared_format"] in (
        "STANDARD_VERTICAL", "SIMPLIFIED", "TABULAR", "LINEAR",
    )
    assert isinstance(data["declared_type_size_in"], (int, float))
    assert data["declared_type_size_in"] > 0
    assert isinstance(data["ingredient_statement_text"], str)
    assert isinstance(data["contains_text"], str)
    assert data["review_status"] in ("DRAFT", "IN_REVIEW", "APPROVED", "WITHDRAWN")
    assert data["release_status"] in (
        "NOT_RELEASED", "RELEASED", "WITHDRAWN", "SUPERSEDED",
    )
    assert data["content_status"] in ("READY", "NEEDS_REVISION")
    assert isinstance(data["review_round"], int)
    assert isinstance(data["prepared_by"], str) and len(data["prepared_by"]) > 0
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert is_valid_uuid(data.get("racc_assignment_id", "")), (
        "racc_assignment_id must be a UUID"
    )


def assert_claim_assessment(data: dict):
    _assert_common(data)
    assert data["claim_type"] in (
        "LOW_FAT", "FAT_FREE", "LOW_SODIUM", "HIGH_FIBER", "SUGAR_FREE",
        "LOW_CALORIE",
    )
    assert data["status"] in (
        "PENDING", "ELIGIBLE", "INELIGIBLE", "NOT_REQUIRED", "SUSPENDED",
    )
    assert is_valid_uuid(data.get("label_version_id", "")), (
        "label_version_id must be a UUID"
    )


def assert_market_variant(data: dict):
    _assert_common(data)
    assert data["market_code"] in ("US_FDA", "CA_CFIA")
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert isinstance(data["effective_start"], str)
    assert is_valid_uuid(data.get("label_version_id", "")), (
        "label_version_id must be a UUID"
    )


def assert_format_check(data: dict):
    _assert_common(data)
    assert data["result"] in ("PASS", "FAIL")
    assert isinstance(data["violations"], list)
    for violation in data["violations"]:
        assert violation in (
            "FORMAT_NOT_ALLOWED_FOR_PACKAGE", "TYPE_SIZE_BELOW_MIN",
        )
    assert isinstance(data["allowed_formats"], list)
    for fmt in data["allowed_formats"]:
        assert fmt in ("STANDARD_VERTICAL", "SIMPLIFIED", "TABULAR", "LINEAR")
    assert isinstance(data["min_type_size_in"], (int, float))
    assert data["min_type_size_in"] > 0
    assert is_valid_uuid(data.get("label_version_id", "")), (
        "label_version_id must be a UUID"
    )


def assert_artwork_audit(data: dict):
    _assert_common(data)
    assert data["scoring_method"] in ("BINARY", "WEIGHTED")
    assert data["status"] in ("SCHEDULED", "FINDINGS_LOGGED", "CLOSED")
    assert isinstance(data["facility_code"], str) and len(data["facility_code"]) > 0
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["scheduled_end"], str)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert is_valid_uuid(data.get("label_version_id", "")), (
        "label_version_id must be a UUID"
    )


def assert_audit_finding(data: dict):
    _assert_common(data)
    assert data["severity"] in ("CRITICAL", "MAJOR", "MINOR")
    assert data["field_ref"] in (
        "INGREDIENT_LIST", "CONTAINS_STATEMENT", "NUTRITION_VALUES",
        "SERVING_SIZE", "CLAIM_TEXT", "FORMAT",
    )
    assert isinstance(data["on_pack_text"], str)
    assert isinstance(data["approved_text"], str)
    assert is_valid_uuid(data.get("audit_id", "")), "audit_id must be a UUID"
