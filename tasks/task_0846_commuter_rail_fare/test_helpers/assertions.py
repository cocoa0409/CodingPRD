"""Entity assertions and domain invariant checkers (PRD-derived)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common_immutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _common_mutable(data: dict):
    _common_immutable(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_passenger(data: dict):
    _common_mutable(data)
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["evasion_count"], int) and data["evasion_count"] >= 0
    assert data["reduced_fare_category"] in ("NONE", "SENIOR", "STUDENT", "DISABILITY")


def assert_fare_product(data: dict):
    _common_immutable(data)
    assert 1 <= data["origin_zone"] <= 6
    assert 1 <= data["destination_zone"] <= 6
    assert data["ticket_type"] in ("SINGLE", "MONTHLY")
    assert data["apportionment_method"] in ("ZONE_COUNT", "DISTANCE")


def assert_ticket(data: dict):
    _common_mutable(data)
    assert data["status"] in ("PURCHASED", "ACTIVATED", "VALIDATED", "REFUNDED", "EXCHANGED")
    assert isinstance(data["purchase_price_cents"], int)
    assert isinstance(data["revenue_allocations"], list)


def assert_inspection(data: dict):
    _common_immutable(data)
    assert data["result"] in ("VALID", "UPGRADE_REQUIRED", "EVASION")
    assert isinstance(data["fare_shortfall_cents"], int)


def assert_citation(data: dict):
    _common_mutable(data)
    assert data["status"] in ("ISSUED", "PAID", "CONTESTED", "UPHELD", "DISMISSED")
    assert isinstance(data["total_penalty_cents"], int)


def assert_service_credit(data: dict):
    _common_mutable(data)
    assert data["status"] in ("ISSUED", "VOIDED")
    assert isinstance(data["credit_amount_cents"], int)


def allocation_for_code(ticket: dict, agency_code: str) -> dict:
    """Return the revenue_allocations entry for a given agency_code, or None."""
    for entry in ticket.get("revenue_allocations", []):
        if entry.get("agency_code") == agency_code:
            return entry
    return None


def sum_allocations(ticket: dict) -> int:
    return sum(entry.get("amount_cents", 0) for entry in ticket.get("revenue_allocations", []))
