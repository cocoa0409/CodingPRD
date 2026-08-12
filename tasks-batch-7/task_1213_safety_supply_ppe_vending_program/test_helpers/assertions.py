"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_cost_center(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("cost_center_code"), str)
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("ytd_charged_cents"), int)
    assert isinstance(data.get("version"), int)


def assert_job_role(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("role_name"), str)
    assert isinstance(data.get("description"), str)
    assert isinstance(data.get("version"), int)


def assert_item(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("sku"), str)
    assert isinstance(data.get("name"), str)
    assert data.get("category") in ("GENERAL", "RESPIRATOR", "FALL_PROTECTION")
    assert isinstance(data.get("requires_fit_test"), bool)
    assert isinstance(data.get("serialized_tracking"), bool)
    assert isinstance(data.get("base_list_price_cents"), int)
    assert data.get("status") in ("ACTIVE", "DISCONTINUED")
    assert isinstance(data.get("version"), int)


def assert_contract_price(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("item_id"), str)
    assert isinstance(data.get("min_period_qty"), int)
    assert isinstance(data.get("unit_price_cents"), int)
    assert isinstance(data.get("effective_from"), str)
    assert isinstance(data.get("effective_to"), str)
    assert isinstance(data.get("version"), int)


def assert_employee(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("employee_code"), str)
    assert isinstance(data.get("full_name"), str)
    assert isinstance(data.get("job_role_id"), str)
    assert isinstance(data.get("home_cost_center_id"), str)
    assert isinstance(data.get("is_manager"), bool)
    assert isinstance(data.get("fit_tests"), list)
    assert data.get("status") in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert isinstance(data.get("version"), int)


def assert_machine(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("location_code"), str)
    assert isinstance(data.get("site_name"), str)
    assert isinstance(data.get("model"), str)
    assert data.get("status") in (
        "COMMISSIONING", "ACTIVE", "OFFLINE", "IN_SERVICE", "DECOMMISSIONED"
    )
    assert isinstance(data.get("version"), int)


def assert_slot(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("machine_id"), str)
    assert isinstance(data.get("slot_code"), str)
    assert isinstance(data.get("item_id"), str)
    assert isinstance(data.get("capacity"), int)
    assert isinstance(data.get("par_level"), int)
    assert isinstance(data.get("on_hand_qty"), int)
    assert isinstance(data.get("version"), int)


def assert_serialized_unit(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("item_id"), str)
    assert isinstance(data.get("serial_number"), str)
    assert isinstance(data.get("slot_id"), str)
    assert isinstance(data.get("inspection_log"), list)
    assert data.get("status") in ("IN_STOCK", "ISSUED", "INSPECTION_DUE", "QUARANTINED")
    assert isinstance(data.get("version"), int)


def assert_manager_override(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("employee_id"), str)
    assert isinstance(data.get("item_id"), str)
    assert isinstance(data.get("approved_qty"), int)
    assert isinstance(data.get("consumed_qty"), int)
    assert isinstance(data.get("remaining_qty"), int)
    assert isinstance(data.get("valid_from"), str)
    assert isinstance(data.get("valid_until"), str)
    assert data.get("reason_code") in ("MEDICAL", "NEW_HIRE", "INCIDENT", "PROJECT", "OTHER")
    assert data.get("status") in ("ACTIVE", "CONSUMED", "EXPIRED", "REVOKED")
    assert isinstance(data.get("version"), int)


def assert_issuance(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("employee_id"), str)
    assert isinstance(data.get("machine_id"), str)
    assert isinstance(data.get("slot_id"), str)
    assert isinstance(data.get("item_id"), str)
    assert isinstance(data.get("qty"), int)
    assert isinstance(data.get("unit_price_cents"), int)
    assert isinstance(data.get("line_total_cents"), int)
    assert isinstance(data.get("cost_center_id"), str)
    assert isinstance(data.get("override_drawn_qty"), int)
    assert isinstance(data.get("idempotency_key"), str)
    assert data.get("status") in ("POSTED", "REVERSED")
    assert isinstance(data.get("version"), int)


def assert_restock_order(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("machine_id"), str)
    assert isinstance(data.get("slot_id"), str)
    assert isinstance(data.get("item_id"), str)
    assert isinstance(data.get("qty"), int)
    assert isinstance(data.get("suggested_qty"), int)
    assert data.get("source") in ("AUTO_PAR", "MANUAL")
    assert data.get("status") in ("SUGGESTED", "PICKED", "LOADED", "CANCELLED")
    assert isinstance(data.get("version"), int)


def assert_service_ticket(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("machine_id"), str)
    assert data.get("issue_code") in (
        "JAM", "DOOR_FAULT", "NETWORK", "DISPLAY", "PLANOGRAM_CHANGE", "PREVENTIVE"
    )
    assert isinstance(data.get("window_start"), str)
    assert isinstance(data.get("window_end"), str)
    assert data.get("status") in ("OPEN", "IN_PROGRESS", "RESOLVED")
    assert isinstance(data.get("version"), int)


def assert_chargeback_batch(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("cost_center_id"), str)
    assert isinstance(data.get("period_start"), str)
    assert isinstance(data.get("period_end"), str)
    assert isinstance(data.get("line_count"), int)
    assert isinstance(data.get("snapshot_total_cents"), int)
    assert isinstance(data.get("rerated_total_cents"), int)
    assert isinstance(data.get("adjustment_cents"), int)
    assert isinstance(data.get("admin_fee_cents"), int)
    assert isinstance(data.get("total_cents"), int)
    assert data.get("status") in ("OPEN", "CLOSED", "DISPUTED", "SETTLED")
    assert isinstance(data.get("version"), int)


def assert_compliance_audit(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data.get("scope") in ("OVERRIDE_USAGE", "INSPECTION_COMPLIANCE")
    assert isinstance(data.get("period_start"), str)
    assert isinstance(data.get("period_end"), str)
    assert isinstance(data.get("exceptions_count"), int)
    assert isinstance(data.get("findings_detail"), list)
    assert data.get("status") in ("DRAFT", "FIELDWORK", "FINDINGS_FILED", "CLOSED")
    assert isinstance(data.get("version"), int)
