"""Entity assertions and domain invariant checkers (PRD §2.5, §3).

Assertions stick to what the PRD guarantees: system-managed quartet on every
primary resource (id / created_at / updated_at / version), the append-only
shape of audit records, enum memberships, and integer-cent arithmetic.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """System-managed quartet present on every primary resource (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a server-minted UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_terminal(data: dict):
    assert_common_fields(data)
    assert isinstance(data["terminal_code"], str) and data["terminal_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["state_code"], str) and data["state_code"]
    assert isinstance(data["county_code"], str)
    assert isinstance(data["city_code"], str)
    assert data["rack_status"] in ("OPEN", "SHORTAGE", "FROZEN")
    assert isinstance(data["inventory_gallons"], int)
    assert isinstance(data["daily_allocation_pool_gallons"], int)


def assert_product(data: dict):
    assert_common_fields(data)
    assert isinstance(data["product_code"], str) and data["product_code"]
    assert data["product_family"] in ("GASOLINE", "DIESEL", "JET")
    assert isinstance(data["is_brandable"], bool)


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_code"], str) and data["customer_code"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["open_lifting_exposure_cents"], int)
    assert data["credit_status"] in ("GOOD", "HOLD")


def assert_price_schedule(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["terminal_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["posted_rack_cents_per_gal"], int)
    assert isinstance(data["branded_premium_cents_per_gal"], int)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED", "VOIDED")


def assert_lifting_right(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["terminal_id"])
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["daily_ratable_gallons"], int)
    assert isinstance(data["lifted_today_gallons"], int)
    assert isinstance(data["reserved_gallons"], int)
    assert isinstance(data["allocated_gallons"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")


def assert_supply_contract(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["volume_commitment_gallons"], int)
    assert isinstance(data["lifted_to_date_gallons"], int)
    assert data["pricing_tier"] in ("RACK", "RACK_MINUS_1", "RACK_MINUS_2")
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED", "DEFAULTED")


def assert_exchange_agreement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["delivering_terminal_id"])
    assert isinstance(data["receiving_supplier_code"], str)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["monthly_exchange_cap_gallons"], int)
    assert isinstance(data["delivered_this_month_gallons"], int)
    assert data["status"] in ("PROPOSED", "ACTIVE", "SUSPENDED", "TERMINATED")


def assert_allocation_notice(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["terminal_id"])
    assert isinstance(data["effective_date"], str)
    assert isinstance(data["total_pool_gallons"], int)
    assert data["allocation_method"] in ("PRO_RATA", "RATCHET")
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


def assert_lifting_ticket(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["lifting_right_id"])
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["terminal_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["requested_gallons"], int)
    assert isinstance(data["branded"], bool)
    assert isinstance(data["unit_price_cents_per_gal"], int)
    assert isinstance(data["additive_cost_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["gross_cents"], int)
    assert data["status"] in ("RESERVED", "BOL_ISSUED", "INVOICED", "CANCELLED")


def assert_tax_rule(data: dict):
    assert_common_fields(data)
    assert data["jurisdiction_level"] in ("FEDERAL", "STATE", "COUNTY", "CITY")
    assert isinstance(data["jurisdiction_code"], str) and data["jurisdiction_code"]
    assert data["product_family"] in ("GASOLINE", "DIESEL", "JET")
    assert isinstance(data["rate_cents_per_gal"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_bol_event(data: dict):
    """Append-only audit record: id + created_at + occurred_at, no version."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "BOL events carry no updated_at (PRD §2.5)"
    assert "version" not in data, "BOL events carry no version (PRD §2.5)"
    assert is_valid_uuid(data["lifting_ticket_id"])
    assert data["event_type"] in ("RESERVED", "POSTED", "REVERSED", "CANCELLED")
    assert isinstance(data["occurred_at"], str)


def assert_credit_hold_log(data: dict):
    """Append-only audit record: id + created_at + occurred_at, no version."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "credit hold log carries no updated_at (PRD §2.5)"
    assert "version" not in data, "credit hold log carries no version (PRD §2.5)"
    assert is_valid_uuid(data["customer_id"])
    assert data["event_type"] in ("PLACED", "RELEASED")
    assert isinstance(data["trigger_reason"], str)
    assert isinstance(data["open_exposure_cents_at_event"], int)
