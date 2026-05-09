"""Entity assertions and domain invariant checkers for the Agri-Traceability API.

Each `assert_*` function validates an entity dict against the PRD's response
schema. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


# --------------------- Common-field block (PRD §2.4) ------------------------

def _assert_common_fields(data: dict) -> None:
    """PRD §2.4: id (UUID), created_at + updated_at (ISO 8601), version (int)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"version must be int, got {data.get('version')!r}"


def _assert_appendonly_fields(data: dict) -> None:
    """PRD §2.4: append-only entities carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


# --------------------- PesticideRegistry ------------------------------------

def assert_pesticide_registry(data: dict) -> None:
    _assert_appendonly_fields(data)
    assert isinstance(data.get("registration_no"), str)
    assert isinstance(data.get("product_name"), str)
    assert data.get("category") in ("PESTICIDE", "FERTILIZER")
    assert isinstance(data.get("withdrawal_period_days"), int)
    assert data["withdrawal_period_days"] >= 0
    assert isinstance(data.get("max_dosage_per_hectare_g"), (int, float))
    assert isinstance(data.get("prohibited"), bool)


# --------------------- PlantingBatch ----------------------------------------

VALID_BATCH_STATUSES = {
    "REGISTERED", "GROWING", "HARVESTED",
    "INSPECTED_PASS", "INSPECTED_FAIL",
    "IN_TRANSIT", "DELIVERED",
    "RECALLED", "DISPOSED",
}
VALID_BATCH_POSTURES = {"CLEAN", "FLAGGED", "BLOCKED"}
VALID_BATCH_RECALL_STATUS = {"NONE", "ACTIVE_RECALL", "COMPLETED"}


def assert_planting_batch(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("batch_code"), str) and data["batch_code"].startswith("PB-")
    assert isinstance(data.get("plot_area_hectares"), (int, float))
    assert data["plot_area_hectares"] > 0
    assert data.get("status") in VALID_BATCH_STATUSES, \
        f"status must be one of {VALID_BATCH_STATUSES}, got {data.get('status')!r}"
    assert data.get("posture") in VALID_BATCH_POSTURES
    assert data.get("recall_status") in VALID_BATCH_RECALL_STATUS
    assert isinstance(data.get("total_quantity_kg"), (int, float))
    assert data["total_quantity_kg"] >= 0
    assert isinstance(data.get("grower_id"), str) and len(data["grower_id"]) > 0


# --------------------- AgrochemicalApplication ------------------------------

def assert_agrochemical_application(data: dict) -> None:
    _assert_appendonly_fields(data)
    assert isinstance(data.get("planting_batch_id"), str)
    assert isinstance(data.get("registration_no"), str)
    assert is_iso8601_timestamp(data.get("application_date", ""))
    assert isinstance(data.get("dosage_g_per_hectare"), (int, float))
    assert data["dosage_g_per_hectare"] > 0


# --------------------- HarvestRecord ----------------------------------------

VALID_QUALITY_GRADES = {"A", "B", "C", "REJECT"}


def assert_harvest_record(data: dict) -> None:
    _assert_appendonly_fields(data)
    assert isinstance(data.get("planting_batch_id"), str)
    assert is_iso8601_timestamp(data.get("harvest_date", ""))
    assert isinstance(data.get("quantity_kg"), (int, float))
    assert data["quantity_kg"] > 0
    assert data.get("quality_grade") in VALID_QUALITY_GRADES
    assert isinstance(data.get("storage_bin_id"), str)


# --------------------- StorageBin -------------------------------------------

VALID_BIN_STATUSES = {"AVAILABLE", "FULL", "QUARANTINE"}


def assert_storage_bin(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("bin_code"), str) and data["bin_code"].startswith("WH-")
    assert isinstance(data.get("capacity_kg"), (int, float))
    assert data["capacity_kg"] > 0
    assert isinstance(data.get("occupied_kg"), (int, float))
    assert data["occupied_kg"] >= 0
    assert data.get("status") in VALID_BIN_STATUSES


# --------------------- LogisticsLeg -----------------------------------------

VALID_LEG_STATUSES = {"PLANNED", "IN_TRANSIT", "HANDED_OVER", "ABNORMAL"}


def assert_logistics_leg(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("planting_batch_id"), str)
    assert isinstance(data.get("leg_index"), int) and data["leg_index"] >= 1
    assert isinstance(data.get("from_party_id"), str)
    assert isinstance(data.get("to_party_id"), str)
    assert is_iso8601_timestamp(data.get("depart_at", ""))
    assert is_iso8601_timestamp(data.get("arrive_at", ""))
    assert data.get("status") in VALID_LEG_STATUSES
    assert isinstance(data.get("abnormal_segment_count"), int)
    assert data["abnormal_segment_count"] >= 0
    assert isinstance(data.get("handover_acknowledged"), bool)


# --------------------- SensorReading ----------------------------------------

def assert_sensor_reading(data: dict) -> None:
    _assert_appendonly_fields(data)
    assert isinstance(data.get("logistics_leg_id"), str)
    assert isinstance(data.get("idempotency_key"), str)
    assert is_iso8601_timestamp(data.get("reading_at", ""))
    assert isinstance(data.get("temperature_c"), (int, float))
    assert isinstance(data.get("out_of_range"), bool)


# --------------------- InspectionReport -------------------------------------

VALID_REPORT_STATUSES = {"DRAFT", "ISSUED", "REVOKED"}
VALID_REPORT_RESULTS = {"PASS", "FAIL", "PENDING"}
VALID_TEST_ITEMS = {"PESTICIDE_RESIDUE", "HEAVY_METALS", "MICROORGANISMS"}
VALID_SAMPLING_RULES = {"RANDOM_5PCT", "FIXED_3KG", "FULL_LOT"}


def assert_inspection_report(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("planting_batch_id"), str)
    assert data.get("sampling_rule") in VALID_SAMPLING_RULES
    items = data.get("test_items") or []
    assert isinstance(items, list) and len(items) > 0
    for item in items:
        assert item in VALID_TEST_ITEMS, f"unexpected test_item {item!r}"
    assert data.get("status") in VALID_REPORT_STATUSES
    assert data.get("result") in VALID_REPORT_RESULTS
    assert isinstance(data.get("inspector_id"), str)


# --------------------- QRCode -----------------------------------------------

def assert_qr_code(data: dict) -> None:
    _assert_appendonly_fields(data)
    assert isinstance(data.get("planting_batch_id"), str)
    assert isinstance(data.get("harvest_record_id"), str)
    qr = data.get("qr_code_value", "")
    assert isinstance(qr, str) and len(qr) == 32, \
        f"qr_code_value must be 32 hex chars, got len={len(qr)}"
    int(qr, 16)  # raises if not hex
    assert isinstance(data.get("scan_count"), int)
    assert data["scan_count"] >= 0
    assert isinstance(data.get("revoked"), bool)


# --------------------- Distributor ------------------------------------------

VALID_TIERS = {"WHOLESALE", "RETAIL"}


def assert_distributor(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("contact_email"), str)
    assert data.get("tier") in VALID_TIERS


# --------------------- RecallOrder ------------------------------------------

VALID_RECALL_STATUSES = {"INITIATED", "NOTIFIED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
VALID_RECALL_CLASSES = {"CLASS_I", "CLASS_II", "CLASS_III"}
VALID_RECALL_REASONS = {
    "INSPECTION_FAIL", "COLD_CHAIN_BREACH", "PROHIBITED_SUBSTANCE", "CONSUMER_COMPLAINT",
}


def assert_recall_order(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data.get("planting_batch_id"), str)
    assert data.get("recall_class") in VALID_RECALL_CLASSES
    assert data.get("reason_code") in VALID_RECALL_REASONS
    assert data.get("status") in VALID_RECALL_STATUSES
    assert isinstance(data.get("total_quantity_recalled_kg"), (int, float))
    assert isinstance(data.get("total_quantity_disposed_kg"), (int, float))
    assert isinstance(data.get("disposal_records"), list)


# --------------------- AuditLog ---------------------------------------------

VALID_AUDIT_ACTIONS = {
    "CREATE", "UPDATE", "STATE_TRANSITION",
    "RECALL_INITIATE", "RECALL_NOTIFY", "RECALL_DISPOSE", "RECALL_COMPLETE",
}


def assert_audit_log(data: dict) -> None:
    _assert_appendonly_fields(data)
    assert isinstance(data.get("entity_type"), str)
    assert isinstance(data.get("entity_id"), str)
    assert data.get("action") in VALID_AUDIT_ACTIONS, \
        f"action must be one of {VALID_AUDIT_ACTIONS}, got {data.get('action')!r}"


# --------------------- Domain invariants ------------------------------------

def assert_kg_precision(value) -> None:
    """PRD §2.7 — kilogram quantities stored at two decimal places (round half up)."""
    assert isinstance(value, (int, float))
    rounded = round(float(value) + 1e-9, 2)
    assert abs(rounded - float(value)) < 1e-6, \
        f"kg value {value!r} exceeds 2-decimal precision"


def assert_batch_invariants(data: dict) -> None:
    """Invariants that must hold on any returned PlantingBatch."""
    assert data.get("status") in VALID_BATCH_STATUSES
    assert data.get("posture") in VALID_BATCH_POSTURES
    assert data.get("recall_status") in VALID_BATCH_RECALL_STATUS
    assert data.get("total_quantity_kg", 0) >= 0
