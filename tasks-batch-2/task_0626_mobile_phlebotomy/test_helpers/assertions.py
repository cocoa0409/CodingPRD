"""Entity assertions and domain invariant checkers for the Mobile Phlebotomy API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_PANEL_STATUSES = {"ACTIVE", "RETIRED"}
_PARTNER_STATUSES = {"ACTIVE", "SUSPENDED"}
_PHLEB_STATUSES = {"AVAILABLE", "SUSPENDED"}
_ROUTE_DAY_STATUSES = {"OPEN", "CLOSED"}
_ORDER_STATUSES = {"ORDERED", "SCHEDULED", "DRAW_COMPLETED", "REDRAW_REQUIRED", "RESULTED", "CANCELLED"}
_APPOINTMENT_STATUSES = {"SCHEDULED", "DISPATCHED", "ARRIVED", "DRAW_COMPLETED", "CANCELLED"}
_KIT_STATUSES = {"ASSIGNED", "CONSUMED"}
_SPECIMEN_STATUSES = {"COLLECTED", "MANIFESTED", "ACCESSIONED", "QNS_REJECTED"}
_MANIFEST_STATUSES = {"BUILDING", "IN_TRANSIT", "DELIVERED"}
_RESULT_STATUSES = {"PENDING_RELEASE", "RELEASED"}
_INVOICE_STATUSES = {"DRAFT", "ISSUED", "VOID"}
_CUSTODY_TYPES = {"COLLECTED", "MANIFESTED", "ACCESSIONED", "REJECTED_QNS"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version must begin at 1 and increment"


def assert_test_panel(data: dict):
    _assert_common(data)
    assert isinstance(data["panel_code"], str) and data["panel_code"]
    assert isinstance(data["name"], str)
    assert isinstance(data["required_tube_count"], int) and data["required_tube_count"] >= 1
    assert isinstance(data["base_lab_fee_cents"], int) and data["base_lab_fee_cents"] >= 0
    assert isinstance(data["fasting_required"], bool)
    assert data["status"] in _PANEL_STATUSES


def assert_lab_partner(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["courier_sla_hours"], int) and data["courier_sla_hours"] >= 1
    assert isinstance(data["accepted_panel_codes"], list)
    assert isinstance(data["stat_surcharge_cents"], int) and data["stat_surcharge_cents"] >= 0
    assert data["status"] in _PARTNER_STATUSES


def assert_phlebotomist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["territory_code"], str)
    assert isinstance(data["certification_active"], bool)
    assert isinstance(data["redraw_strike_count"], int) and data["redraw_strike_count"] >= 0
    assert data["status"] in _PHLEB_STATUSES


def assert_route_day(data: dict):
    _assert_common(data)
    assert isinstance(data["phlebotomist_id"], str)
    assert isinstance(data["territory_code"], str)
    assert isinstance(data["stop_capacity"], int) and data["stop_capacity"] >= 1
    assert isinstance(data["booked_stop_count"], int) and data["booked_stop_count"] >= 0
    assert data["status"] in _ROUTE_DAY_STATUSES


def assert_lab_order(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_full_name"], str)
    assert isinstance(data["patient_territory_code"], str)
    assert isinstance(data["panel_code"], str)
    assert isinstance(data["lab_partner_id"], str)
    assert data["priority"] in {"ROUTINE", "STAT"}
    assert data["billing_mode"] in {"INSURANCE", "SELF_PAY"}
    assert isinstance(data["specimens_required_count"], int) and data["specimens_required_count"] >= 1
    assert isinstance(data["specimens_accessioned_count"], int) and data["specimens_accessioned_count"] >= 0
    assert isinstance(data["redraw_count"], int) and data["redraw_count"] >= 0
    assert isinstance(data["total_due_cents"], int) and data["total_due_cents"] >= 0
    assert data["status"] in _ORDER_STATUSES


def assert_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_order_id"], str)
    assert isinstance(data["route_day_id"], str)
    assert isinstance(data["phlebotomist_id"], str)
    assert data["status"] in _APPOINTMENT_STATUSES


def assert_draw_kit(data: dict):
    _assert_common(data)
    assert isinstance(data["appointment_id"], str)
    assert isinstance(data["kit_lot_number"], str)
    assert isinstance(data["tube_count"], int) and data["tube_count"] >= 1
    assert data["status"] in _KIT_STATUSES


def assert_specimen(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_order_id"], str)
    assert isinstance(data["tube_label"], str)
    assert data["status"] in _SPECIMEN_STATUSES


def assert_custody_event(data: dict):
    """Append-only audit record (PRD §2.4 / §3.7): id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "custody event id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["event_type"] in _CUSTODY_TYPES
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 0


def assert_courier_manifest(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_partner_id"], str)
    assert isinstance(data["territory_code"], str)
    assert isinstance(data["specimen_count"], int) and data["specimen_count"] >= 0
    assert data["status"] in _MANIFEST_STATUSES


def assert_lab_result(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_order_id"], str)
    assert isinstance(data["lab_partner_id"], str)
    assert isinstance(data["released_to_provider"], bool)
    assert isinstance(data["released_to_portal"], bool)
    assert data["status"] in _RESULT_STATUSES


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["lab_order_id"], str)
    assert data["billing_mode"] in {"INSURANCE", "SELF_PAY"}
    assert isinstance(data["lab_fee_cents"], int) and data["lab_fee_cents"] >= 0
    assert isinstance(data["convenience_fee_cents"], int) and data["convenience_fee_cents"] >= 0
    assert isinstance(data["redraw_waiver_cents"], int) and data["redraw_waiver_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert data["status"] in _INVOICE_STATUSES
