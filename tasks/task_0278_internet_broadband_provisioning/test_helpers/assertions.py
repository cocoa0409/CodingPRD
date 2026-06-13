"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version (version-bearing entities, PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an int >= 1, got {data.get('version')!r}"


def assert_lean_fields(data: dict):
    """id + created_at only (write-light records, PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "lean record must NOT carry version"
    assert "updated_at" not in data, "lean record must NOT carry updated_at"


def assert_account(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "DISCONNECTED", "TRANSFERRED"), \
        f"unexpected account status {data['status']!r}"
    assert data["service_state"] in ("PROVISIONING", "ONLINE", "THROTTLED", "OFFLINE"), \
        f"unexpected service_state {data['service_state']!r}"
    assert isinstance(data["credit_balance_cents"], int)


def assert_equipment_unit(data: dict):
    assert_common_fields(data)
    assert data["kind"] in ("MODEM", "ROUTER", "GATEWAY")
    assert data["status"] in ("IN_INVENTORY", "LEASED", "RETURN_PENDING", "RETURNED", "LOST")


def assert_service_order(data: dict):
    assert_common_fields(data)
    assert data["order_type"] in ("NEW_INSTALL", "TRANSFER_IN", "UPGRADE")
    assert data["install_mode"] in ("TECH_INSTALL", "SELF_INSTALL")
    assert data["status"] in ("DRAFT", "SCHEDULED", "KIT_SHIPPED", "ACTIVATED", "CANCELLED")


def assert_install_slot(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "FULL")
    assert isinstance(data["capacity"], int)
    assert isinstance(data["booked_count"], int)


def assert_install_appointment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED", "NO_SHOW")


def assert_billing_cycle(data: dict):
    assert_common_fields(data)
    assert data["billing_state"] in ("OPEN", "CLOSED", "FINALIZED")
    assert data["throttle_state"] in ("UNCAPPED", "THROTTLED")


def assert_outage_event(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "RESOLVED", "CREDITED", "DISMISSED")


def assert_transfer_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "COMPLETED", "REJECTED")


def assert_service_address(data: dict):
    assert_lean_fields(data)
    assert data["coverage_status"] in ("SERVICEABLE", "NOT_SERVICEABLE", "PRE_ORDER")
    assert data["technology"] in ("FIBER", "CABLE", "DSL", "FIXED_WIRELESS")


def assert_service_plan(data: dict):
    assert_lean_fields(data)
    assert data["overage_policy"] in ("BILL", "THROTTLE", "UNLIMITED")


def assert_usage_record(data: dict):
    assert_lean_fields(data)
    assert data["gb"] > 0


def assert_account_credit(data: dict):
    assert_lean_fields(data)
    assert data["source_type"] in ("OUTAGE", "LEASE_PRORATE", "GOODWILL", "TRANSFER_WAIVER")
    assert data["amount_cents"] > 0
    assert isinstance(data["applied"], bool)


def net_credit_amount(credits: list, source_type: str = None) -> int:
    """Sum amount_cents across a credit list, optionally filtered by source_type.

    A reversed LEASE_PRORATE is modeled per PRD §3.7 as the amount negated; this
    helper sums the raw amounts so a reversed pair nets to zero regardless of
    whether the implementer negates an existing row or appends an offsetting one.
    """
    total = 0
    for c in credits:
        if source_type is None or c.get("source_type") == source_type:
            total += c.get("amount_cents", 0)
    return total
