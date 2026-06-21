"""Entity assertions and domain invariant checkers.

Built on the framework's generic validators (is_valid_uuid, is_iso8601_timestamp).
Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_BERTH_WINDOW_STATES = {"SCHEDULED", "BERTHED", "DEPARTED", "CANCELLED"}
_CUSTOMS_STATES = {"PENDING", "HELD", "CLEARED"}
_HANDLING_STATES = {"ON_VESSEL", "GROUNDED", "GATED_OUT"}
_SLOT_STATES = {"EMPTY", "OCCUPIED"}
_APPT_STATES = {"BOOKED", "ARRIVED", "FULFILLED", "NO_SHOW", "CANCELLED"}
_HOLD_STATES = {"ACTIVE", "RELEASED"}
_INVOICE_STATES = {"ISSUED", "PAID", "WAIVED"}
_DIRECTIONS = {"GATE_IN", "GATE_OUT"}
_CONDITIONS = {"SOUND", "DAMAGED"}


def _assert_common(data: dict):
    """id + created_at + updated_at + version for full-lifecycle entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """Append-only audit records carry ONLY id + created_at: no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry a version field"
    assert "updated_at" not in data, "append-only record must not carry an updated_at field"


def assert_berth(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["length_m"], int)
    assert isinstance(data["draft_m"], (int, float))
    assert data["status"] in {"AVAILABLE", "CLOSED"}


def assert_vessel(data: dict):
    _assert_common(data)
    assert isinstance(data["imo_number"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["loa_m"], int)
    assert isinstance(data["draft_m"], (int, float))
    assert isinstance(data["free_time_days"], int)


def assert_berth_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["berth_id"])
    assert is_valid_uuid(data["vessel_id"])
    assert is_iso8601_timestamp(data["eta"])
    assert is_iso8601_timestamp(data["etd"])
    assert data["status"] in _BERTH_WINDOW_STATES


def assert_container(data: dict):
    _assert_common(data)
    assert isinstance(data["container_number"], str) and len(data["container_number"]) > 0
    assert is_valid_uuid(data["vessel_id"])
    assert is_valid_uuid(data["berth_window_id"])
    assert isinstance(data["is_reefer"], bool)
    assert data["customs_status"] in _CUSTOMS_STATES
    assert data["handling_status"] in _HANDLING_STATES
    assert isinstance(data["demurrage_due_cents"], int)


def assert_yard_slot(data: dict):
    _assert_common(data)
    assert isinstance(data["block"], str) and len(data["block"]) > 0
    assert isinstance(data["bay"], int) and data["bay"] >= 1
    assert isinstance(data["row"], int) and data["row"] >= 1
    assert isinstance(data["tier"], int) and data["tier"] >= 1
    assert isinstance(data["is_reefer_rack"], bool)
    assert data["status"] in _SLOT_STATES


def assert_gate_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["container_id"])
    assert isinstance(data["truck_plate"], str) and len(data["truck_plate"]) > 0
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in _APPT_STATES
    assert isinstance(data["no_show_count"], int)


def assert_customs_hold(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["container_id"])
    assert data["reason"] in {"INSPECTION", "DOCUMENTATION", "DUTY_UNPAID"}
    assert data["status"] in _HOLD_STATES


def assert_demurrage_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["container_id"])
    assert isinstance(data["chargeable_days"], int)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in _INVOICE_STATES


def assert_reefer_reading(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["container_id"])
    assert is_iso8601_timestamp(data["recorded_at"])
    assert isinstance(data["temperature_c"], (int, float))
    assert isinstance(data["is_excursion"], bool)


def assert_eir(data: dict):
    _assert_append_only(data)
    assert is_valid_uuid(data["container_id"])
    assert data["direction"] in _DIRECTIONS
    assert data["condition"] in _CONDITIONS
