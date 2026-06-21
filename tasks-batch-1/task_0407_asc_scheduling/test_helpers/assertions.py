"""Entity assertions and domain invariant checkers for the ASC Scheduling PRD."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (entities with common_fields: true)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["turnover_minutes"], int) and data["turnover_minutes"] >= 0
    assert isinstance(data["hp_validity_days"], int)
    assert isinstance(data["utilization_target_pct"], (int, float))
    assert is_iso8601_timestamp(data["current_utc"]), "current_utc must be ISO 8601"


def assert_operating_room(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["room_label"], str) and len(data["room_label"]) > 0
    assert isinstance(data["prime_time_start_min"], int)
    assert isinstance(data["prime_time_end_min"], int)
    assert data["prime_time_end_min"] > data["prime_time_start_min"]
    assert data["status"] in ("AVAILABLE", "OFFLINE")


def assert_recovery_bay(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["bay_label"], str) and len(data["bay_label"]) > 0
    assert isinstance(data["phase2_capable"], bool)
    assert data["status"] in ("AVAILABLE", "OFFLINE")


def assert_anesthesiologist(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["credential"] in ("MD", "DO", "CRNA")
    assert isinstance(data["active"], bool)


def assert_surgeon(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["npi"], str) and len(data["npi"]) == 10
    assert isinstance(data["active"], bool)


def assert_procedure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["cpt_code"], str) and len(data["cpt_code"]) == 5
    assert isinstance(data["scheduled_minutes"], int) and data["scheduled_minutes"] > 0
    assert data["anesthesia_class"] in ("LOCAL", "MAC", "REGIONAL", "GENERAL")
    assert data["cms_payment_indicator"] in (
        "COVERED_ASC", "DEVICE_INTENSIVE", "OFFICE_BASED", "EXCLUDED",
    )
    assert isinstance(data["cms_base_rate_cents"], int) and data["cms_base_rate_cents"] >= 0


def assert_supply_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0


def assert_patient(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["mrn"], str) and len(data["mrn"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0


def assert_surgical_day(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["service_date"], str) and len(data["service_date"]) == 10
    assert data["posture"] in ("OPEN", "LOCKED", "CLOSED")
    assert isinstance(data["booked_minutes"], int) and data["booked_minutes"] >= 0
    assert isinstance(data["utilization_pct"], (int, float)) and data["utilization_pct"] >= 0


def assert_surgeon_block(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["surgical_day_id"])
    assert is_valid_uuid(data["surgeon_id"])
    assert is_valid_uuid(data["operating_room_id"])
    assert isinstance(data["start_min"], int)
    assert isinstance(data["end_min"], int) and data["end_min"] > data["start_min"]
    assert data["allocated_minutes"] == data["end_min"] - data["start_min"]
    assert isinstance(data["committed_minutes"], int) and data["committed_minutes"] >= 0
    assert data["status"] in ("HELD", "CONFIRMED", "RELEASED")


def assert_surgical_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["surgical_day_id"])
    assert is_valid_uuid(data["surgeon_block_id"])
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["procedure_id"])
    assert is_valid_uuid(data["operating_room_id"])
    assert isinstance(data["start_min"], int)
    assert isinstance(data["scheduled_minutes"], int) and data["scheduled_minutes"] > 0
    assert data["end_min"] == data["start_min"] + data["scheduled_minutes"]
    assert isinstance(data["is_add_on"], bool)
    assert isinstance(data["estimated_cost_cents"], int) and data["estimated_cost_cents"] >= 0
    assert data["case_status"] in ("SCHEDULED", "IN_OR", "IN_RECOVERY", "COMPLETED", "CANCELLED")
    assert data["clearance_status"] in ("PENDING_CLEARANCE", "ON_HOLD", "CLEARED")


def assert_case_implant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["surgical_case_id"])
    assert is_valid_uuid(data["supply_item_id"])
    assert isinstance(data["planned_qty"], int) and data["planned_qty"] > 0
    assert data["status"] in ("RESERVED", "CONSUMED", "RELEASED")


def assert_clearance_check(data: dict):
    """ClearanceCheck is append-only: id + created_at ONLY (no updated_at / version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["surgical_case_id"])
    assert data["check_type"] in ("HP_REVIEW", "LABS", "ANESTHESIA_ASSESSMENT", "CARDIAC_CONSULT")
    assert data["outcome"] in ("PASS", "FAIL", "DEFER")


# ---------------------------------------------------------------------------
# Conservation invariants (PRD 2.9)
# ---------------------------------------------------------------------------
def assert_block_minutes_nonneg(block: dict):
    """committed_minutes is an accounting quantity that must stay non-negative."""
    assert block["committed_minutes"] >= 0, "committed_minutes must never go negative"
    assert block["committed_minutes"] <= block["allocated_minutes"], (
        "committed_minutes must never exceed allocated_minutes"
    )


def assert_supply_reservation_nonneg(item: dict):
    """reserved_qty is an accounting quantity that must stay non-negative."""
    assert item["reserved_qty"] >= 0, "reserved_qty must never go negative"
    assert item["reserved_qty"] <= item["on_hand_qty"], (
        "reserved_qty must never exceed on_hand_qty"
    )
