"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

ALLERGEN_CLASSES = [
    "NONE", "GLUTEN", "MILK", "SOY", "EGG",
    "PEANUT", "TREE_NUT", "FISH", "SHELLFISH", "SESAME",
]
DOSAGE_FORMS = ["TABLET", "CAPSULE", "POWDER", "SOFTGEL", "LIQUID"]


def _assert_common(data: dict):
    """Common system-managed fields carried by every resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["brand_name"], str) and len(data["brand_name"]) > 0
    for field in (
        "committed_order_value_cents",
        "open_order_count",
        "lifetime_receipts_cents",
        "open_recall_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer-cent/count value"
        assert data[field] >= 0, f"{field} must be non-negative"


def assert_raw_material(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["allergen_class"] in ALLERGEN_CLASSES


def assert_material_lot(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "QUARANTINE", "IDENTITY_PASSED", "IDENTITY_FAILED",
        "RELEASED", "REJECTED", "RECALLED",
    ]
    assert isinstance(data["supplier_name"], str) and len(data["supplier_name"]) > 0
    assert isinstance(data["supplier_coa_ref"], str) and len(data["supplier_coa_ref"]) > 0
    assert data["qty_received"] > 0
    assert data["qty_remaining"] >= 0


def assert_identity_test(data: dict):
    _assert_common(data)
    assert data["result"] in ["PASS", "FAIL"]
    assert isinstance(data["coa_match"], bool)
    assert data["status"] in ["SUBMITTED", "COA_APPROVED", "COA_REJECTED"]
    assert isinstance(data["tested_by_id"], str) and len(data["tested_by_id"]) > 0


def assert_formula(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["dosage_form"] in DOSAGE_FORMS
    assert data["allergen_class"] in ALLERGEN_CLASSES
    assert data["status"] in ["DRAFT", "APPROVED", "SUPERSEDED"]
    assert data["min_order_qty"] >= 1
    assert data["batch_size_units"] >= 1
    assert data["shelf_life_months"] >= 1
    assert data["overage_basis"] in ["THEORETICAL", "LABEL_CLAIM"]
    assert isinstance(data["price_tiers"], list)


def assert_formula_line(data: dict):
    _assert_common(data)
    assert data["theoretical_qty_mg_per_unit"] > 0
    assert 0 <= data["overage_pct"] <= 25
    assert isinstance(data["is_label_claim_line"], bool)
    if data["is_label_claim_line"]:
        assert data.get("label_claim_mg_per_unit") is not None, (
            "label-claim line must carry label_claim_mg_per_unit"
        )


def assert_manufacturing_order(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "PLACED", "SCHEDULED", "IN_PRODUCTION", "COMPLETED", "CANCELLED",
    ]
    assert data["ordered_qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["total_price_cents"], int)
    assert data["total_price_cents"] == data["ordered_qty"] * data["unit_price_cents"], (
        "total_price_cents must equal ordered_qty * unit_price_cents (exact integer cents)"
    )
    assert isinstance(data["recall_flag"], bool)
    assert isinstance(data["formula_version_at_order"], int)


def assert_batch(data: dict):
    _assert_common(data)
    assert data["production_status"] in [
        "CREATED", "IN_PROCESS", "COMPLETED", "RECORD_REVIEWED", "CANCELLED",
    ]
    assert data["quality_status"] in [
        "PENDING_QC", "ASSAY_HOLD", "QC_READY", "RELEASED", "REJECTED", "RECALLED",
    ]
    assert data["theoretical_units"] >= 1
    if data.get("yield_variance_pct") is not None:
        assert isinstance(data["yield_variance_pct"], (int, float))


def assert_batch_consumption(data: dict):
    _assert_common(data)
    assert data["qty_consumed"] > 0
    assert data["status"] in ["ACTIVE", "VOIDED"]


def assert_production_line(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["cleaning_status"] in [
        "CLEAN_VALIDATED", "DIRTY", "CLEAN_PENDING_VALIDATION",
    ]
    assert data["current_allergen_class"] in ALLERGEN_CLASSES


def assert_cleaning_validation(data: dict):
    _assert_common(data)
    assert data["status"] in ["RECORDED", "SWAB_PASSED", "VALIDATED", "FAILED"]
    assert isinstance(data["recorded_by_id"], str) and len(data["recorded_by_id"]) > 0


def assert_assay_result(data: dict):
    _assert_common(data)
    assert data["assayed_mg_per_unit"] > 0
    assert data["label_claim_mg_per_unit"] > 0
    assert isinstance(data["pct_of_claim"], (int, float))
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "REJECTED"]
    assert isinstance(data["submitted_by_id"], str) and len(data["submitted_by_id"]) > 0


def assert_stability_study(data: dict):
    _assert_common(data)
    assert data["protocol"] in ["REAL_TIME", "ACCELERATED"]
    assert data["status"] in ["ENROLLED", "COMPLETED"]


def assert_stability_chamber(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["capacity_units"] >= 1
    assert isinstance(data["occupied_units"], int)
    assert 0 <= data["occupied_units"] <= data["capacity_units"], (
        "occupied_units must stay within capacity_units"
    )


def assert_recall_event(data: dict):
    _assert_common(data)
    assert data["scope_type"] in ["MATERIAL_LOT", "BATCH"]
    assert isinstance(data["scope_id"], str) and len(data["scope_id"]) > 0
    assert isinstance(data["reason"], str) and len(data["reason"]) > 0
    assert isinstance(data["affected_batch_count"], int) and data["affected_batch_count"] >= 0
    assert data["status"] in ["INITIATED", "TRACED", "CLOSED"]


def assert_lot_mass_invariant(lot: dict, active_consumption_total):
    """PRD §3.4: qty_remaining plus the ACTIVE consumption total equals qty_received."""
    assert lot["qty_remaining"] + active_consumption_total == lot["qty_received"], (
        f"lot mass invariant broken: {lot['qty_remaining']} + {active_consumption_total} "
        f"!= {lot['qty_received']}"
    )
