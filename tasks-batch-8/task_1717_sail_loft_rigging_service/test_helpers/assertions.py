"""Entity assertions and domain invariant checkers (PRD §2.4 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

CUSTOMER_STATUSES = ["ACTIVE", "SUSPENDED", "CLOSED"]
BOAT_STATUSES = ["ACTIVE", "OUT_OF_SERVICE", "RETIRED"]
MAST_STATUSES = ["STEPPED", "UNSTEPPING_SCHEDULED", "UNSTEPPED", "TUNING_IN_PROGRESS"]
RACING_CLASSES = ["NONE", "J70", "J105", "TP52", "ORC", "PHRF"]
SHEET_STATUSES = ["DRAFT", "FROZEN", "SUPERSEDED"]
CLOTH_TIERS = ["CRUISE", "PERFORMANCE", "RACE", "GRAND_PRIX"]
DESIGN_STATUSES = ["DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "SUPERSEDED", "ARCHIVED"]
ORDER_KINDS = ["NEW_SAIL", "RIGGING_SERVICE", "MAST_SERVICE", "STORAGE_PROGRAM", "REPAIR"]
ORDER_STATUSES = [
    "OPEN", "DESIGN_LOCKED", "IN_PRODUCTION", "READY_FOR_FIT_CHECK",
    "DELIVERED", "WARRANTY_REVIEW", "WARRANTY_REPAIR", "CLOSED", "CANCELLED",
]
BAY_CODES = ["BAY_A", "BAY_B", "BAY_C"]
JOB_STATUSES = ["SCHEDULED", "CUTTING", "SEAMING", "FINISHING", "QC_PASSED", "QC_FAILED", "CANCELLED"]
RIGGING_SCOPES = ["STANDING", "RUNNING", "FULL"]
VERDICTS = ["PASS", "ADVISORY", "FAIL"]
INSPECTION_STATUSES = ["SCHEDULED", "REPORTED", "CLOSED"]
SERVICE_KINDS = ["UNSTEP", "STEP", "TUNE"]
MAST_EVENT_STATUSES = ["BOOKED", "IN_PROGRESS", "COMPLETED", "RIGGING_HOLD", "CANCELLED"]
CONTRACT_STATUSES = ["ENROLLED", "RECEIVED", "WASHED", "STORED", "OUT_FOR_DELIVERY", "RETURNED", "CANCELLED"]
CERT_STATUSES = ["ACTIVE", "REVOKED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in CUSTOMER_STATUSES


def assert_boat(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert isinstance(data["boat_name"], str) and data["boat_name"]
    assert isinstance(data["hull_length_m"], (int, float))
    assert data["racing_class"] in RACING_CLASSES
    assert data["mast_status"] in MAST_STATUSES
    assert isinstance(data["standing_rigging_install_date"], str)
    assert isinstance(data["running_rigging_hours_accumulated"], int)
    assert data["status"] in BOAT_STATUSES


def assert_measurement_sheet(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("boat_id", "")), "boat_id must be a UUID"
    for f in ("i_height_m", "j_base_m", "p_main_m", "e_main_m"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert data["sheet_status"] in SHEET_STATUSES
    if data["sheet_status"] == "DRAFT":
        assert data.get("frozen_at") is None, "frozen_at must be null while DRAFT"
    else:
        assert isinstance(data.get("measured_area_sqm"), (int, float))


def assert_sail_design(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("boat_id", "")), "boat_id must be a UUID"
    assert is_valid_uuid(data.get("measurement_sheet_id", "")), "measurement_sheet_id must be a UUID"
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert data["cloth_tier"] in CLOTH_TIERS
    assert isinstance(data["reinforcement_level"], int) and 1 <= data["reinforcement_level"] <= 5
    assert isinstance(data["option_codes"], list)
    assert data["design_status"] in DESIGN_STATUSES


def assert_work_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert is_valid_uuid(data.get("boat_id", "")), "boat_id must be a UUID"
    assert data["order_kind"] in ORDER_KINDS
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["invoiced_total_cents"], int)
    assert isinstance(data["warranty_flag"], bool)
    assert data["order_status"] in ORDER_STATUSES


def assert_production_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("work_order_id", "")), "work_order_id must be a UUID"
    assert data["bay_code"] in BAY_CODES
    assert isinstance(data["scheduled_start_date"], str)
    assert isinstance(data["scheduled_end_date"], str)
    assert isinstance(data["reserved_cloth_sqm"], (int, float))
    assert data["job_status"] in JOB_STATUSES


def assert_cloth_bolt(data: dict):
    _assert_common(data)
    assert isinstance(data["bolt_code"], str) and data["bolt_code"]
    assert data["cloth_tier"] in CLOTH_TIERS
    assert isinstance(data["total_sqm"], (int, float))
    assert isinstance(data["available_sqm"], (int, float))
    assert isinstance(data["price_per_sqm_cents"], int)


def assert_rigging_inspection(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("boat_id", "")), "boat_id must be a UUID"
    assert data["rigging_scope"] in RIGGING_SCOPES
    assert data["inspection_status"] in INSPECTION_STATUSES
    if data["inspection_status"] in ("REPORTED", "CLOSED"):
        assert data.get("verdict") in VERDICTS
        assert is_iso8601_timestamp(data.get("inspected_at", "")), "inspected_at must be ISO 8601"
        assert isinstance(data["standing_months_at_inspection"], int)
        assert isinstance(data["running_replacement_due_hours"], int)


def assert_mast_service_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("boat_id", "")), "boat_id must be a UUID"
    assert data["service_kind"] in SERVICE_KINDS
    assert is_iso8601_timestamp(data.get("slot_start_utc", "")), "slot_start_utc must be ISO 8601"
    assert is_iso8601_timestamp(data.get("slot_end_utc", "")), "slot_end_utc must be ISO 8601"
    assert data["event_status"] in MAST_EVENT_STATUSES


def assert_storage_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("boat_id", "")), "boat_id must be a UUID"
    assert isinstance(data["season_code"], str) and data["season_code"]
    assert isinstance(data["wash_item_codes"], list)
    assert isinstance(data["quoted_storage_fee_cents"], int)
    assert data["contract_status"] in CONTRACT_STATUSES


def assert_class_certificate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("boat_id", "")), "boat_id must be a UUID"
    assert is_valid_uuid(data.get("measurement_sheet_id", "")), "measurement_sheet_id must be a UUID"
    assert data["racing_class"] in [c for c in RACING_CLASSES if c != "NONE"]
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert data["cert_status"] in CERT_STATUSES


def assert_balance_invariants(customer: dict):
    """Domain invariant (PRD §2.8): the outstanding balance never goes below zero."""
    assert customer["outstanding_balance_cents"] >= 0, "outstanding_balance_cents floored at zero"


def assert_cloth_invariants(bolt: dict):
    """Domain invariant (PRD §2.9): available cloth never exceeds the bolt's total."""
    assert 0 <= bolt["available_sqm"] <= bolt["total_sqm"]
