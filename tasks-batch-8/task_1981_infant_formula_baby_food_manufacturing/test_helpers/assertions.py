"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    NutrientProfileStatus, SupplierStatus, AuditResult, RiskRating,
    LotQcStatus, FormulaStatus, BatchStatus, ValidationStatus, LabelStatus,
    ComplaintStatus, RecallStatus, RecallScopeStatus, PlanStatus, EntryStatus,
)


def _assert_common_fields(data: dict):
    """PRD §2.4: id, created_at, updated_at, version on every primary entity."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_system_user(data: dict):
    """PRD §2.4: SystemUser carries only id and created_at — no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "SystemUser must not carry updated_at"
    assert "version" not in data, "SystemUser must not carry version"
    assert isinstance(data["username"], str) and data["username"]
    assert data["role"] in [
        "ADMIN", "REGULATORY_AFFAIRS", "QA_MANAGER", "QUALITY_ANALYST",
        "PRODUCTION_SUPERVISOR", "SUPPLY_CHAIN_PLANNER", "COMPLAINT_HANDLER",
    ]


def assert_nutrient_profile(data: dict):
    _assert_common_fields(data)
    assert data["profile_code"] in [
        "INF-0-6M", "INF-6-12M", "TODDLER-12-36M", "CEREAL-6M", "PUREE-4M",
    ]
    assert isinstance(data["nutrient_specs"], list) and len(data["nutrient_specs"]) >= 1
    assert data["status"] in [s.value for s in NutrientProfileStatus]


def assert_supplier(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["supplier_code"], str) and data["supplier_code"]
    assert isinstance(data["ingredient_categories"], list) and data["ingredient_categories"]
    assert data["qualification_status"] in [s.value for s in SupplierStatus]
    assert data["risk_rating"] in [r.value for r in RiskRating]


def assert_audit_record(data: dict):
    _assert_common_fields(data)
    assert data["result"] in [r.value for r in AuditResult]
    assert isinstance(data["score"], (int, float))


def assert_ingredient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["ingredient_code"], str) and data["ingredient_code"]
    assert data["pathogen_risk_class"] in ["HIGH_RISK", "MEDIUM_RISK", "LOW_RISK"]


def assert_ingredient_lot(data: dict):
    _assert_common_fields(data)
    assert data["qc_status"] in [s.value for s in LotQcStatus]
    assert isinstance(data["quantity_kg"], (int, float))
    assert isinstance(data["remaining_kg"], (int, float))


def assert_formula(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["formula_code"], str) and data["formula_code"]
    assert data["status"] in [s.value for s in FormulaStatus]
    assert data["process_type"] in ["DRY_BLEND", "WET_PROCESS", "COMBINATION"]


def assert_production_batch(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in BatchStatus]
    assert isinstance(data["batch_number"], str) and data["batch_number"].startswith("B-")


def assert_process_validation(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ValidationStatus]
    assert data["validation_type"] in [
        "DRY_BLEND_HOMOGENEITY", "WET_PROCESS_THERMAL",
        "PATHOGEN_ENVIRONMENTAL", "COMBINATION_FULL",
    ]


def assert_label_submission(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in LabelStatus]


def assert_complaint(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in ComplaintStatus]
    assert isinstance(data["is_adverse_event"], bool)


def assert_recall_campaign(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in RecallStatus]
    assert data["recall_class"] in ["CLASS_I", "CLASS_II", "CLASS_III"]


def assert_recall_scope(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in RecallScopeStatus]
    assert isinstance(data["quantity_recovered_kg"], (int, float))


def assert_allocation_plan(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in PlanStatus]


def assert_allocation_entry(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [s.value for s in EntryStatus]
    assert isinstance(data["allocated_kg"], (int, float))
    assert isinstance(data["fulfilled_kg"], (int, float))
