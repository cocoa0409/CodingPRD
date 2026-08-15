"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_2dp(actual, expected, label="value"):
    """Compare a 2dp-rounded numeric field against its expected decimal value."""
    assert actual is not None, f"{label} must not be null"
    assert abs(float(actual) - float(expected)) < 1e-6, (
        f"Expected {label} == {expected}, got {actual}"
    )


def assert_supplier(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["qualification_status"] in ("PROVISIONAL", "APPROVED", "SUSPENDED")
    assert isinstance(data["allergens_handled"], list)


def assert_ingredient(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in ("PROTEIN", "SWEETENER", "BINDER", "FAT", "FLAVOR", "ADDITIVE")
    assert isinstance(data["allergen_tags"], list)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_ingredient_lot(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["ingredient_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert data["received_qty_kg"] > 0
    assert data["status"] in ("QUARANTINE", "RELEASED", "REJECTED", "DEPLETED")


def assert_lot_mass_invariant(lot: dict):
    """PRD §2.8: available == received - reserved - consumed at every step."""
    total = round(lot["reserved_qty_kg"] + lot["consumed_qty_kg"] + lot["available_qty_kg"], 2)
    assert abs(total - round(float(lot["received_qty_kg"]), 2)) < 1e-6, (
        f"lot mass not conserved: {lot['available_qty_kg']} + {lot['reserved_qty_kg']}"
        f" + {lot['consumed_qty_kg']} != {lot['received_qty_kg']}"
    )


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_agreement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["pricing_mode"] in ("MARGINAL", "AVERAGE")
    assert data["moq_cases_per_run"] > 0
    assert data["committed_cases_per_quarter"] > 0
    assert isinstance(data["tier_breaks"], list) and data["tier_breaks"]
    assert data["status"] in ("NEGOTIATION", "ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data["produced_cases_current_quarter"], int)
    assert isinstance(data["shortfall_cases"], int)
    assert data["shortfall_cases"] >= 0


def assert_formula(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["bar_weight_g"] > 0
    assert data["serving_count_per_bar"] >= 1
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert "approved_revision_id" in data


def assert_revision(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["formula_id"])
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    assert isinstance(data["ingredient_lines"], list) and data["ingredient_lines"]
    assert data["batch_size_kg"] > 0
    assert isinstance(data["allergen_profile"], list)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "NUTRITION_VERIFIED", "CLAIM_REVIEW", "APPROVED", "SUPERSEDED",
    )


def assert_line(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["capacity_kg_per_hour"] > 0
    assert data["slab_weight_kg"] > 0
    assert isinstance(data["current_allergen_profile"], list)


def assert_slot(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["line_id"])
    assert is_valid_uuid(data["run_id"])
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert data["buffer_minutes"] in (0, 30, 60, 90)
    assert data["status"] in ("CONFIRMED", "COMPLETED", "RELEASED")


def assert_production_run(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["revision_id"])
    assert is_valid_uuid(data["agreement_id"])
    assert is_valid_uuid(data["line_id"])
    assert data["planned_cases"] > 0
    assert isinstance(data["batch_code"], str) and data["batch_code"].startswith("BATCH-")
    assert isinstance(data["reserved_lot_allocations"], list)
    assert data["ingredient_readiness"] in ("READY", "BLOCKED")
    assert data["status"] in (
        "PLANNED", "SCHEDULED", "PRE_RUN_VERIFIED", "IN_PRODUCTION", "COMPLETED", "CANCELLED",
    )
    assert data["release_status"] in (
        "NOT_READY", "PENDING_QC", "RELEASED", "HOLD_REWORK", "SCRAPPED",
    )


def assert_changeover(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["line_id"])
    assert is_valid_uuid(data["to_run_id"])
    assert data["required_level"] in ("NONE", "DRY_CLEAN", "WET_CLEAN", "SWAB_VALIDATE")
    assert data["status"] in (
        "PENDING", "CLEANING_LOGGED", "SWAB_RECORDED", "VALIDATED", "FAILED", "CANCELLED",
    )


def assert_study(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["revision_id"])
    assert isinstance(data["chamber_id"], str) and data["chamber_id"]
    assert isinstance(data["shelf_position"], str) and data["shelf_position"]
    assert data["hardness_limit_n"] > 0
    assert data["pull_interval_days"] >= 1
    assert data["status"] in ("ACTIVE", "COMPLETED", "FAILED", "TERMINATED")


def assert_pull(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["study_id"])
    assert isinstance(data["pull_index"], int) and data["pull_index"] >= 0
    assert is_iso8601_timestamp(data["due_utc"])
    assert is_iso8601_timestamp(data["recorded_utc"])
    assert data["hardness_n"] > 0
    assert data["status"] in ("RECORDED", "MISSED")


def assert_lot_release(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["run_id"])
    assert isinstance(data["expected_cases"], int) and data["expected_cases"] >= 0
    assert data["qc_disposition"] in ("PENDING", "PASSED", "FAILED")
    assert data["decision"] in ("PENDING", "RELEASED", "HOLD_REWORK", "SCRAPPED")
    assert isinstance(data["retain_cases_stored"], int)


def assert_retain_sample(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["run_id"])
    assert isinstance(data["bin_id"], str) and data["bin_id"]
    assert data["cases_count"] > 0
    assert data["status"] == "STORED"


def assert_claim_review(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["revision_id"])
    assert data["claim_tag"] in (
        "HIGH_PROTEIN", "GOOD_SOURCE_PROTEIN", "LOW_SUGAR", "GLUTEN_FREE",
    )
    assert data["claim_type"] in ("NUTRIENT_CONTENT", "STRUCTURE_FUNCTION")
    assert isinstance(data["substantiation_ok"], bool)
    assert data["status"] in ("SUBMITTED", "IN_REVIEW", "APPROVED", "REVISION_REQUESTED")


def assert_day_availability_invariant(data: dict):
    """PRD §3.6: occupied + buffered + free == 1440 for a line-day."""
    total = data["occupied_minutes"] + data["buffered_minutes"] + data["free_minutes"]
    assert total == 1440, (
        f"line-day must total 1440 minutes, got occupied={data['occupied_minutes']}"
        f" buffered={data['buffered_minutes']} free={data['free_minutes']}"
    )
    assert data["free_minutes"] >= 0, "free_minutes must never be negative"
