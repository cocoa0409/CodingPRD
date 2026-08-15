"""Entity assertions and domain invariant checkers (PRD §2.4 shapes)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

SUPPLIER_STATUSES = ["ACTIVE", "SUSPENDED"]
LOT_STATUSES = ["REGISTERED", "GRADED", "LAB_SUBMITTED", "ON_HOLD",
                "RELEASED", "REJECTED", "DEPLETED"]
LEAF_TYPES = ["BLACK", "GREEN", "WHITE", "OOLONG", "HERBAL"]
LOT_GRADES = ["NONE", "A", "B", "C", "REJECT"]
ASSESSMENT_GRADES = ["A", "B", "C", "REJECT"]
RESIDUE_VERDICTS = ["NONE", "PASS", "FAIL_SOFT", "FAIL_HARD"]
FLAVORING_STATUSES = ["ACTIVE", "RETIRED"]
RECIPE_STATUSES = ["DRAFT", "ACTIVE", "RETIRED"]
BATCH_STATUSES = ["DRAFT", "RECIPE_LOCKED", "ALLOCATED", "BLENDED",
                  "FLAVORED", "QC_REVIEW", "ON_HOLD", "RELEASED",
                  "RECALLED", "CANCELLED"]
ALLOCATION_STATUSES = ["ACTIVE", "RELEASED"]
LINE_STATUSES = ["ACTIVE", "MAINTENANCE"]
LINE_TYPES = ["TEA_BAG", "LOOSE_PACK"]
RUN_STATUSES = ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
CONTRACT_STATUSES = ["DRAFT", "ACTIVE", "FULFILLED", "CANCELLED"]
CERT_TYPES = ["ORGANIC", "FAIR_TRADE"]
CERT_STATUSES = ["ACTIVE", "SUSPENDED", "EXPIRED"]
CERTIFICATION_TARGETS = ["CONVENTIONAL", "ORGANIC", "FAIR_TRADE"]
ALLERGEN_TAGS = ["TREE_NUT", "SOY", "GLUTEN", "LACTOSE"]


def _assert_primary_shape(data, statuses):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data.get("status") in statuses, \
        f"status {data.get('status')} not in {statuses}"


def _assert_record_shape(data):
    """Record-type resources: only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, "record resources must omit updated_at"
    assert "version" not in data, "record resources must omit version"


def assert_supplier(data: dict):
    _assert_primary_shape(data, SUPPLIER_STATUSES)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["origin_region"], str)


def assert_leaf_lot(data: dict):
    _assert_primary_shape(data, LOT_STATUSES)
    assert data["leaf_type"] in LEAF_TYPES
    assert data["weight_kg"] > 0
    assert isinstance(data["cost_per_kg_cents"], int)
    assert 0 < data["moisture_pct"] <= 100
    assert data["remaining_weight_kg"] >= 0
    assert data["composite_grade"] in LOT_GRADES
    assert data["latest_residue_verdict"] in RESIDUE_VERDICTS


def assert_grade_assessment(data: dict):
    _assert_record_shape(data)
    assert data["composite_grade"] in ASSESSMENT_GRADES
    for key in ("aroma_score", "briskness_score", "appearance_score"):
        assert isinstance(data[key], int), f"{key} must be int"
        assert 0 <= data[key] <= 100, f"{key} must be within 0..100"
    assert isinstance(data["composite_score"], (int, float))


def assert_residue_test(data: dict):
    _assert_record_shape(data)
    assert data["verdict"] in ["PASS", "FAIL_SOFT", "FAIL_HARD"]
    assert data["measured_residue_ppm"] >= 0
    assert isinstance(data["test_round"], int) and data["test_round"] >= 1


def assert_flavoring(data: dict):
    _assert_primary_shape(data, FLAVORING_STATUSES)
    assert isinstance(data["allergen_tags"], list)
    for tag in data["allergen_tags"]:
        assert tag in ALLERGEN_TAGS
    assert isinstance(data["natural_certified"], bool)
    assert isinstance(data["cost_per_kg_cents"], int)


def assert_blend_recipe(data: dict):
    _assert_primary_shape(data, RECIPE_STATUSES)
    assert data["certification_target"] in CERTIFICATION_TARGETS
    assert data["pack_format"] in LINE_TYPES
    assert isinstance(data["components"], list) and len(data["components"]) > 0
    for comp in data["components"]:
        assert comp["leaf_type"] in LEAF_TYPES
        assert comp["min_grade"] in ["A", "B", "C"]
        assert comp["pct"] > 0


def assert_blend_batch(data: dict):
    _assert_primary_shape(data, BATCH_STATUSES)
    assert data["pack_format"] in LINE_TYPES
    assert data["target_weight_kg"] > 0
    assert isinstance(data["allergen_tags"], list)
    assert isinstance(data["cert_charges"], list)


def assert_batch_lot_allocation(data: dict):
    _assert_primary_shape(data, ALLOCATION_STATUSES)
    assert data["allocated_kg"] > 0
    assert isinstance(data["line_cost_cents"], int)


def assert_flavoring_application(data: dict):
    _assert_record_shape(data)
    assert data["applied_kg"] > 0
    assert isinstance(data["flavoring_cost_cents"], int)


def assert_packaging_line(data: dict):
    _assert_primary_shape(data, LINE_STATUSES)
    assert data["line_type"] in LINE_TYPES


def assert_production_run(data: dict):
    _assert_primary_shape(data, RUN_STATUSES)
    assert data["planned_units"] >= 1
    assert isinstance(data["provisional_shelf_life_days"], int)


def assert_private_label_contract(data: dict):
    _assert_primary_shape(data, CONTRACT_STATUSES)
    assert data["minimum_units_per_run"] >= 1
    assert data["contracted_total_units"] >= data["minimum_units_per_run"]
    assert isinstance(data["fulfilled_units"], int)
    assert data["fulfilled_units"] >= 0


def assert_certificate_grant(data: dict):
    _assert_primary_shape(data, CERT_STATUSES)
    assert data["cert_type"] in CERT_TYPES
    assert data["total_volume_kg"] > 0
    assert data["consumed_volume_kg"] >= 0
    assert data["valid_until"] > data["valid_from"]
