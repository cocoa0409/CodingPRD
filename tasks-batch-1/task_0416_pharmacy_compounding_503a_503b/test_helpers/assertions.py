"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response shape and field types against the
PRD contract. Invariant checkers guard derived-field reconciliation rules.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


REGISTRATION_TYPES = ["503A", "503B"]
DOSAGE_FORMS = [
    "ORAL_SOLID", "ORAL_LIQUID", "TOPICAL", "NONSTERILE_OTHER",
    "STERILE_AQUEOUS", "STERILE_NONAQUEOUS",
]
MFR_STATUSES = ["ACTIVE", "RETIRED"]
LOT_STATUSES = ["AVAILABLE", "QUARANTINED", "EXPIRED", "DISCARDED"]
PRESCRIPTION_STATUSES = ["ACTIVE", "FILLED", "CANCELLED", "EXPIRED"]
BATCH_STATUSES = [
    "DRAFT", "IN_PROCESS", "COMPILED", "QUARANTINED",
    "RELEASED", "REJECTED", "RECALLED",
]
QC_RESULTS = ["PENDING", "IN_PROGRESS", "PASSED", "FAILED"]
QC_STATUSES = ["AWAITING_QC", "QC_RELEASED", "QC_REJECTED"]
DISPENSE_STATUSES = ["IN_INVENTORY", "DISPENSED", "RECALLED"]
RECALL_STATUSES = ["INITIATED", "IN_PROGRESS", "RECONCILED", "CLOSED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["registration_type"] in REGISTRATION_TYPES
    assert isinstance(data["state_code"], str)
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be ISO 8601"


def assert_mfr(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["dosage_form"] in DOSAGE_FORMS
    assert isinstance(data["is_sterile"], bool)
    assert isinstance(data["default_bud_days_nonsterile"], int)
    assert isinstance(data["theoretical_yield_units"], int)
    assert isinstance(data["anticipatory_window_days"], int)
    assert isinstance(data["anticipatory_max_units"], int)
    assert data["status"] in MFR_STATUSES


def assert_ingredient_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["component_name"], str)
    assert isinstance(data["lot_number"], str)
    assert isinstance(data["labeled_potency_pct"], (int, float))
    assert isinstance(data["initial_grams"], (int, float))
    assert isinstance(data["remaining_grams"], (int, float))
    assert data["status"] in LOT_STATUSES


def assert_environmental_log(data: dict):
    # common_fields: false — only id + created_at, plus reading fields.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "EnvironmentalLog is immutable: must not carry version"
    assert "updated_at" not in data, "EnvironmentalLog is immutable: must not carry updated_at"
    assert is_valid_uuid(data["facility_id"])
    assert data["usp_chapter"] in ["USP_795", "USP_797"]
    assert isinstance(data["measured_value"], (int, float))
    assert isinstance(data["action_limit"], (int, float))
    assert isinstance(data["in_spec"], bool)
    assert is_iso8601_timestamp(data["reading_utc"])


def assert_prescription(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["master_formulation_record_id"])
    assert isinstance(data["patient_name"], str)
    assert isinstance(data["prescriber_npi"], str)
    assert isinstance(data["units_prescribed"], int)
    assert isinstance(data["units_dispensed"], int)
    assert data["status"] in PRESCRIPTION_STATUSES


def assert_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["master_formulation_record_id"])
    assert data["purpose"] in ["PRESCRIPTION", "OFFICE_USE"]
    assert isinstance(data["theoretical_yield_units"], int)
    assert data["status"] in BATCH_STATUSES


def assert_batch_ingredient_usage(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["compounding_batch_id"])
    assert is_valid_uuid(data["ingredient_lot_id"])
    assert isinstance(data["grams_used"], (int, float))
    assert isinstance(data["potency_adjusted_grams"], (int, float))


def assert_qc_test(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["compounding_batch_id"])
    assert data["test_type"] in ["POTENCY_ASSAY", "STERILITY", "ENDOTOXIN", "VISUAL_INSPECTION"]
    assert data["result"] in QC_RESULTS


def assert_finished_preparation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["compounding_batch_id"])
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["unit_serial"], str) and len(data["unit_serial"]) > 0
    assert isinstance(data["label_text"], str)
    assert is_iso8601_timestamp(data["beyond_use_utc"])
    assert data["qc_status"] in QC_STATUSES
    assert data["dispense_status"] in DISPENSE_STATUSES


def assert_dispense(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["finished_preparation_id"])
    assert is_iso8601_timestamp(data["dispensed_utc"])


def assert_anticipatory_ledger(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["master_formulation_record_id"])
    assert isinstance(data["consumed_units"], int)
    assert isinstance(data["remaining_units"], int)
    assert is_iso8601_timestamp(data["window_start_utc"])


def assert_recall(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["compounding_batch_id"])
    assert data["reason"] in [
        "STERILITY_FAILURE", "POTENCY_OOS", "ENDOTOXIN_OOS",
        "ENVIRONMENTAL_EXCURSION", "LABELING_ERROR",
    ]
    assert data["classification"] in ["CLASS_I", "CLASS_II", "CLASS_III"]
    assert isinstance(data["units_in_scope"], int)
    assert isinstance(data["units_reconciled"], int)
    assert data["status"] in RECALL_STATUSES


def assert_ledger_invariants(data: dict):
    """remaining_units = max(0, anticipatory_max - consumed); never negative."""
    assert data["consumed_units"] >= 0, "consumed_units must be non-negative"
    assert data["remaining_units"] >= 0, "remaining_units must be floored at 0"
