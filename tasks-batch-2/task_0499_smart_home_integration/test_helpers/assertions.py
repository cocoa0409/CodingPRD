"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """Common fields every entity carries: id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["billing_tier"] in ("RESIDENTIAL", "COMMERCIAL")


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["site_address"], str)
    assert data["region_code"] in ("NORTH", "SOUTH", "EAST", "WEST")
    assert data["status"] in (
        "DRAFT", "PROPOSED", "ACCEPTED", "PROVISIONING", "SCHEDULED",
        "INSTALLING", "COMMISSIONED", "ACTIVE", "CANCELLED",
    )
    assert isinstance(data["provisioned_device_count"], int)
    assert isinstance(data["open_change_order_count"], int)
    assert isinstance(data["contract_balance_cents"], int)


def assert_proposal(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ("DRAFT", "SENT", "ACCEPTED", "REJECTED", "SUPERSEDED")
    for f in ("equipment_subtotal_cents", "discount_cents", "labor_cost_cents",
              "tax_cents", "grand_total_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_line_item(data: dict):
    _assert_common(data)
    assert isinstance(data["proposal_id"], str)
    assert isinstance(data["sku"], str)
    assert data["category"] in ("CONTROLLER", "AUDIO", "VIDEO", "NETWORK", "LIGHTING", "ACCESSORY")
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["removed"], bool)


def assert_rack(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["rack_units_total"], int)
    assert isinstance(data["rack_units_used"], int) and data["rack_units_used"] >= 0
    assert isinstance(data["subnet_cidr"], str)
    assert isinstance(data["ip_pool_size"], int)


def assert_device(data: dict):
    _assert_common(data)
    assert isinstance(data["rack_id"], str)
    assert isinstance(data["sku"], str)
    assert data["category"] in ("CONTROLLER", "AUDIO", "VIDEO", "NETWORK", "LIGHTING", "ACCESSORY")
    assert isinstance(data["rack_units"], int) and data["rack_units"] >= 0
    assert data["status"] in ("REGISTERED", "PROVISIONED", "ONLINE", "FAULTED", "RETIRED")
    assert isinstance(data["is_controller"], bool)


def assert_scene(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["device_ids"], list)
    assert data["status"] in ("DRAFT", "VALIDATED", "DEPLOYED", "ARCHIVED")
    assert isinstance(data["action_count"], int)


def assert_visit(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["region_code"] in ("NORTH", "SOUTH", "EAST", "WEST")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["visit_kind"] in ("INSTALL", "COMMISSION", "SERVICE")
    assert data["status"] in (
        "PLANNED", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_SHOW",
    )
    assert isinstance(data["crew_size_required"], int) and data["crew_size_required"] >= 1
    assert isinstance(data["assigned_crew_count"], int) and data["assigned_crew_count"] >= 0


def assert_crew_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert data["region_code"] in ("NORTH", "SOUTH", "EAST", "WEST")
    assert data["cert_level"] in ("APPRENTICE", "JOURNEYMAN", "MASTER")
    assert isinstance(data["daily_visit_cap"], int)
    assert isinstance(data["active"], bool)


def assert_visit_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["visit_id"], str)
    assert isinstance(data["crew_member_id"], str)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["plan"] in ("BASIC", "PLUS", "PREMIER")
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "CANCELLED")
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0


def assert_firmware_update(data: dict):
    _assert_common(data)
    assert isinstance(data["device_id"], str)
    assert isinstance(data["target_version"], str)
    assert data["status"] in ("STAGED", "APPLIED", "ROLLED_BACK", "FAILED")


def assert_rma_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["device_id"], str)
    assert isinstance(data["contract_id"], str)
    assert data["fault_code"] in ("HARDWARE", "FIRMWARE", "NETWORK", "POWER")
    assert data["resolution"] in ("RETURN_REPAIR", "ADVANCE_REPLACE")
    assert data["status"] in ("OPENED", "AUTHORIZED", "SHIPPED", "CLOSED", "DENIED")


def assert_change_order(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["delta_cents"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "APPLIED", "REJECTED")
