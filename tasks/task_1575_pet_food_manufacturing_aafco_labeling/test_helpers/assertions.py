"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert isinstance(data, dict), f"Expected object payload, got {type(data)}"
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_brand_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["fein"], str) and data["fein"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["open_recall_count"], int) and data["open_recall_count"] >= 0
    assert isinstance(data["complaint_score"], (int, float))


def assert_supplier(data: dict):
    _assert_common(data)
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert isinstance(data["fsma_facility_id"], str) and data["fsma_facility_id"]
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert data["approval_state"] in ["PROVISIONAL", "APPROVED", "SUSPENDED", "DISQUALIFIED"]
    assert data["risk_tier"] in ["LOW", "MEDIUM", "HIGH"]
    assert isinstance(data["approved_ingredient_count"], int)
    assert data["approved_ingredient_count"] >= 0


def assert_ingredient(data: dict):
    _assert_common(data)
    assert isinstance(data["aafco_name"], str) and data["aafco_name"]
    assert isinstance(data["ingredient_code"], str) and data["ingredient_code"]
    assert isinstance(data["nutrient_matrix"], dict)
    assert data["allergen_class"] in [
        "NONE", "POULTRY", "BEEF", "FISH", "DAIRY", "GRAIN", "OTHER",
    ]
    assert isinstance(data["requires_coa"], bool)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_pairing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("supplier_id", ""))
    assert is_valid_uuid(data.get("ingredient_id", ""))
    assert data["approval_state"] in ["PENDING_REVIEW", "APPROVED", "REJECTED", "REVOKED"]


def assert_formula(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("brand_owner_id", ""))
    assert isinstance(data["formula_code"], str) and data["formula_code"]
    assert isinstance(data["product_name"], str) and data["product_name"]
    assert data["species"] in ["DOG", "CAT"]
    assert data["life_stage"] in [
        "GROWTH", "ADULT_MAINTENANCE", "ALL_LIFE_STAGES", "GESTATION_LACTATION",
    ]
    assert data["adequacy_basis"] in ["FORMULATION", "FEEDING_TRIAL"]
    assert data["status"] in [
        "DRAFT", "NUTRIENT_REVIEW", "SUBSTANTIATED", "LOCKED", "SUPERSEDED", "WITHDRAWN",
    ]
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["total_batch_count"], int) and data["total_batch_count"] >= 0
    assert isinstance(data["open_recall_flag"], bool)


def assert_formula_ingredient(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert is_valid_uuid(data.get("ingredient_id", ""))
    assert 0 < data["inclusion_pct"] <= 100


def assert_nutrient_profile(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert data["profile_basis"] in ["FORMULATION_CALC", "LAB_ANALYSIS"]
    assert isinstance(data["metabolizable_energy_kcal_per_kg"], (int, float))
    assert data["aafco_compliance"] in ["PENDING", "COMPLIANT", "DEFICIENT"]


def assert_trial_protocol(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert isinstance(data["protocol_code"], str) and data["protocol_code"]
    assert data["status"] in [
        "PLANNED", "ENROLLING", "RUNNING", "ANALYSIS", "PASSED", "FAILED", "ABORTED",
    ]
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["completed_count"], int) and data["completed_count"] >= 0


def assert_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert isinstance(data["line_id"], str) and data["line_id"]
    assert data["status"] in [
        "SCHEDULED", "RELEASED_FOR_PRODUCTION", "IN_PROCESS", "ON_HOLD",
        "COMPLETED", "REJECTED", "RECALLED",
    ]


def assert_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("batch_id", ""))
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["packaged_units"], int) and data["packaged_units"] >= 0
    assert data["status"] in ["ACTIVE", "QUARANTINED", "RELEASED", "RECALLED"]


def assert_lab_sample(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("batch_id", ""))
    assert data["sample_type"] in ["FIRST", "MIDDLE", "LAST", "COMPOSITE"]
    assert data["verdict"] in ["PENDING", "WITHIN_LABEL", "LABEL_VIOLATION"]


def assert_ga_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("batch_id", ""))
    for field in (
        "composite_protein_pct",
        "composite_fat_pct",
        "composite_fiber_pct",
        "composite_moisture_pct",
    ):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
    assert data["label_compliance"] in ["PENDING", "COMPLIANT", "MISBRANDED"]
    assert isinstance(data["deviation_index"], (int, float))


def assert_state_registration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["label_revision_ref"], int)
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "EXPIRED", "REVOKED",
    ]
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_complaint_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("brand_owner_id", ""))
    assert is_valid_uuid(data.get("formula_id", ""))
    assert data["severity"] in ["MINOR", "SERIOUS", "LIFE_THREATENING", "DEATH"]
    assert data["category"] in [
        "PALATABILITY", "FOREIGN_MATERIAL", "ILLNESS", "LABEL_DEFECT", "PACKAGING",
    ]
    assert data["status"] in [
        "INTAKE", "TRIAGED", "INVESTIGATING", "RESOLVED", "ESCALATED_RECALL",
        "CLOSED_NO_ACTION",
    ]
    assert isinstance(data["triage_score"], (int, float))


def assert_recall_action(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("formula_id", ""))
    assert isinstance(data["scope_batch_ids"], list)
    assert data["recall_class"] in ["CLASS_I", "CLASS_II", "CLASS_III"]
    assert isinstance(data["reason"], str)
    assert data["status"] in [
        "INITIATED", "EFFECTIVENESS_CHECK", "COMPLETED", "CLOSED", "TERMINATED",
    ]
    assert isinstance(data["affected_lot_count"], int) and data["affected_lot_count"] >= 0
