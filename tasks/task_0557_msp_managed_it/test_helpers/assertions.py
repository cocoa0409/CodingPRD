"""Entity assertions and domain invariant checkers for the MSP Managed IT API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Versioned, mutable record: id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 and increments"


def assert_immutable_row(data: dict):
    """Immutable audit row: id + created_at ONLY (PRD §2.5). Invoice and
    SeatAdjustment must NOT carry updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_client(data: dict):
    assert_common_fields(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["primary_contact_email"], str)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["credit_available_cents"], int)
    assert data["status"] in ("ACTIVE", "OFFBOARDED")


def assert_site(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["label"], str)
    assert isinstance(data["address"], str)


def assert_technician(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert data["skill_level"] in ("JUNIOR", "SENIOR")
    assert isinstance(data["hourly_rate_cents"], int)


def assert_contract(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_id"], str)
    assert data["service_tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["seat_count"], int)
    assert isinstance(data["per_seat_rate_cents"], int)
    assert isinstance(data["backup_addon"], bool)
    assert isinstance(data["security_addon"], bool)
    assert isinstance(data["seats_available"], int)
    assert isinstance(data["period_ticket_minutes"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "TERMINATED")


def assert_asset(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["site_id"], str)
    assert data["asset_type"] in ("LAPTOP", "DESKTOP", "PHONE", "SERVER")
    assert isinstance(data["hostname"], str)
    assert data["monitoring_status"] in ("UNMONITORED", "ACTIVE", "RETIRED")
    assert isinstance(data["patch_compliance_pct"], (int, float))


def assert_patch_job(data: dict):
    assert_common_fields(data)
    assert isinstance(data["asset_id"], str)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("SCHEDULED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED")


def assert_ticket(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["contract_id"], str)
    assert data["priority"] in ("P1", "P2", "P3", "P4")
    assert isinstance(data["subject"], str)
    assert data["status"] in ("NEW", "IN_PROGRESS", "RESOLVED", "CANCELLED")
    assert isinstance(data["sla_response_breached"], bool)
    assert isinstance(data["sla_resolve_breached"], bool)
    assert isinstance(data["billable_minutes"], int)


def assert_dispatch(data: dict):
    assert_common_fields(data)
    assert isinstance(data["ticket_id"], str)
    assert isinstance(data["technician_id"], str)
    assert data["mode"] in ("REMOTE", "ONSITE")
    assert data["status"] in ("SCHEDULED", "ON_SITE", "COMPLETED", "CANCELLED")
    assert isinstance(data["travel_buffer_minutes"], int)


def assert_quote(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_id"], str)
    assert data["quote_type"] in ("PROJECT", "PROCUREMENT")
    assert isinstance(data["line_items"], list)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("DRAFT", "SENT", "ACCEPTED", "EXPIRED")


def assert_procurement_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["line_items"], list)
    assert isinstance(data["total_cents"], int)
    assert data["status"] in ("DRAFT", "PLACED", "CANCELLED")


def assert_invoice(data: dict):
    """PRD §2.5: Invoice is an immutable snapshot — id + created_at only."""
    assert_immutable_row(data)
    assert isinstance(data["contract_id"], str)
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["base_seat_charge_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_seat_adjustment(data: dict):
    """PRD §2.5: SeatAdjustment is an immutable event — id + created_at only."""
    assert_immutable_row(data)
    assert isinstance(data["contract_id"], str)
    assert isinstance(data["delta"], int)
    assert isinstance(data["seat_count_after"], int)


# --- Domain invariant checkers ---

def assert_seat_conservation(contract: dict, seat_count: int):
    """PRD §3.3: seats_available = seat_count - ACTIVE assigned assets. Idle
    contract with no active assignments should have seats_available == seat_count."""
    assert contract["seats_available"] == seat_count, (
        f"seats_available {contract['seats_available']} != seat_count {seat_count}"
    )


def assert_credit_conservation(client: dict, credit_limit_cents: int):
    """PRD §3.1: credit_available_cents = credit_limit_cents - sum(PLACED order totals).
    When no orders are PLACED the two values must match."""
    assert client["credit_available_cents"] == credit_limit_cents, (
        f"credit_available_cents {client['credit_available_cents']} != "
        f"credit_limit_cents {credit_limit_cents}"
    )
