"""Entity assertions and domain invariant checkers.

Each assert_* validates the common system-managed fields (PRD "Common
Resource Properties") plus the entity's own field shapes and enum domains.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_allergen(data: dict):
    _assert_common_fields(data, "Allergen")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["display_name"], str)
    assert data["regulatory_class"] in ["MAJOR_9", "SESAME", "SULFITE", "OTHER"]
    assert isinstance(data["is_active"], bool)


def assert_production_line(data: dict):
    _assert_common_fields(data, "ProductionLine")
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert data["sanitation_class"] in ["WET_WASH", "DRY_CLEAN", "ALLERGEN_DEDICATED"]
    assert data["posture"] in ["OPEN", "RESTRICTED", "HOLD"]
    assert "last_validated_changeover_id" in data


def assert_product(data: dict):
    _assert_common_fields(data, "Product")
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["allergen_set"], list)
    assert data["rework_class"] in [
        "SAME_INTO_SAME", "SAME_ALLERGEN_PROFILE", "RESTRICTED_REWORK", "NO_REWORK",
    ]
    assert isinstance(data["label_revision"], int)
    assert isinstance(data["is_active"], bool)


def assert_matrix_entry(data: dict):
    _assert_common_fields(data, "LineAllergenMatrixEntry")
    assert is_valid_uuid(data.get("line_id", ""))
    assert is_valid_uuid(data.get("allergen_id", ""))
    assert data["handling"] in ["ALLOWED", "REQUIRES_CHANGEOVER", "PROHIBITED"]
    assert isinstance(data["changeover_minutes"], int)


def assert_production_run(data: dict):
    _assert_common_fields(data, "ProductionRun")
    assert is_valid_uuid(data.get("line_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert data["status"] in [
        "DRAFT", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "REJECTED", "CANCELLED",
    ]
    assert isinstance(data["introduced_allergens"], list)
    assert isinstance(data["changeover_required"], bool)
    assert isinstance(data["scheduled_changeover_minutes"], int)
    assert isinstance(data["label_revision_snapshot"], int)


def assert_changeover(data: dict):
    _assert_common_fields(data, "Changeover")
    assert data["status"] in [
        "PLANNED", "IN_EXECUTION", "SWAB_PENDING", "VALIDATED",
        "FAILED", "REWORK_REQUIRED", "CANCELLED",
    ]
    assert isinstance(data["scheduled_minutes"], int)


def assert_changeover_procedure(data: dict):
    _assert_common_fields(data, "ChangeoverProcedure")
    assert isinstance(data["procedure_code"], str) and data["procedure_code"]
    assert data["method"] in ["FULL_WET_WASH", "DRY_SCRAPE", "PURGE", "VACUUM_ONLY"]
    assert isinstance(data["min_swab_zones"], int)
    assert isinstance(data["atp_action_level_rlu"], int)
    assert isinstance(data["allergen_action_level_ppm"], (int, float))
    assert isinstance(data["version_seq"], int)
    assert isinstance(data["is_current"], bool)
    assert data["status"] in ["DRAFT", "APPROVED", "SUPERSEDED", "RETIRED"]


def assert_swab_result(data: dict):
    _assert_common_fields(data, "SwabResult")
    assert is_valid_uuid(data.get("changeover_id", ""))
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert data["swab_type"] in ["ATP", "ALLERGEN_PROTEIN", "ALLERGEN_ELISA"]
    assert isinstance(data["measured_value"], (int, float))
    assert isinstance(data["action_level_used"], (int, float))
    assert data["outcome"] in ["PASS", "FAIL", "INVALIDATED"]
    assert is_valid_uuid(data.get("recorded_by_id", ""))


def assert_qa_technician(data: dict):
    _assert_common_fields(data, "QaTechnician")
    assert isinstance(data["tech_code"], str) and data["tech_code"]
    assert isinstance(data["certified_allergen_ids"], list)
    assert isinstance(data["training_score"], int)
    assert 0 <= data["training_score"] <= 100
    assert data["status"] in ["ACTIVE", "SUSPENDED", "SEPARATED"]


def assert_label_reconciliation(data: dict):
    _assert_common_fields(data, "LabelReconciliation")
    assert is_valid_uuid(data.get("run_id", ""))
    assert isinstance(data["expected_label_revision"], int)
    assert isinstance(data["printed_label_revision"], int)
    assert isinstance(data["declared_allergens_on_label"], list)
    assert isinstance(data["missing_allergens"], list)
    assert isinstance(data["extra_allergens"], list)
    assert data["verdict"] in ["MATCH", "REVISION_MISMATCH", "UNDECLARED_ALLERGEN", "OVER_DECLARED"]
    assert data["status"] in ["OPEN", "RESOLVED", "ESCALATED"]


def assert_rework_batch(data: dict):
    _assert_common_fields(data, "ReworkBatch")
    assert isinstance(data["quantity_kg"], (int, float))
    assert isinstance(data["remaining_kg"], (int, float))
    assert isinstance(data["rework_allergen_set"], list)
    assert data["status"] in ["AVAILABLE", "COMMITTED", "CONSUMED", "SCRAPPED"]


def assert_incident(data: dict):
    _assert_common_fields(data, "Incident")
    assert data["incident_type"] in [
        "UNDECLARED_ALLERGEN", "LABEL_MISMATCH", "SWAB_FAILURE_CLUSTER",
        "SUPPLIER_ALLERGEN_CHANGE", "REWORK_RULE_BREACH",
    ]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["status"] in ["OPEN", "INVESTIGATING", "CONTAINED", "CLOSED", "VOID"]


def assert_audit_finding(data: dict):
    _assert_common_fields(data, "AuditFinding")
    assert is_valid_uuid(data.get("technician_id", ""))
    assert is_valid_uuid(data.get("auditor_id", ""))
    assert data["finding_type"] in [
        "PROCEDURE_DEVIATION", "DOCUMENTATION_GAP", "TRAINING_DEFICIENCY",
        "SWAB_TECHNIQUE", "LABEL_CONTROL",
    ]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert isinstance(data["points_deducted"], int)
    assert data["status"] in ["OPEN", "RESOLVED", "OVERDUE", "WAIVED"]


def assert_rework_mass_conservation(batch: dict, committed_kg: float):
    """Invariant: remaining_kg + committed_kg == quantity_kg for a live batch.

    Scrapped batches zero remaining_kg; the scrapped remainder still satisfies
    remaining + committed + scrapped_remainder == quantity_kg.
    """
    assert batch["remaining_kg"] >= 0
    assert batch["remaining_kg"] <= batch["quantity_kg"]
    if batch["status"] in ("AVAILABLE", "COMMITTED"):
        assert batch["remaining_kg"] + committed_kg == batch["quantity_kg"]
