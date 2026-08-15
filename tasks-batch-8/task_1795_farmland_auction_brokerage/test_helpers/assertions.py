"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant; accepts optional fractional seconds."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 UTC timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def assert_instant_equal(actual: str, expected_iso: str, label: str = "instant"):
    """Compare two instants semantically (formatting tolerance, same instant)."""
    actual_dt = _parse_instant(actual)
    expected_dt = _parse_instant(expected_iso)
    assert actual_dt == expected_dt, (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def assert_money(actual, expected: float, label: str = "amount"):
    """Money is rounded half-up to 2 decimals (PRD §2.6); compare to the cent."""
    assert isinstance(actual, (int, float)), f"{label} must be numeric, got {actual!r}"
    assert actual == pytest.approx(expected, abs=0.005), (
        f"{label}: expected {expected}, got {actual}"
    )


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601 UTC"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            "updated_at must be ISO 8601 UTC"
        )
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_seller(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_broker_agent(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]


def assert_buyer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["proof_of_funds_amount"], (int, float))
    assert data["qualification_status"] in (
        "UNVERIFIED",
        "QUALIFIED",
        "EXPIRED",
        "DISQUALIFIED",
    )


def assert_listing(data: dict):
    _assert_common(data)
    for field in ("seller_id", "agent_id"):
        assert is_valid_uuid(data.get(field, "")), f"{field} must be a UUID"
    assert isinstance(data["title"], str)
    assert isinstance(data["county"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["total_gross_acres"], (int, float))
    assert data["packaging_strategy"] in ("WHOLE", "SPLIT", "COMBINATION")
    assert isinstance(data["reserve_price_total"], (int, float))
    assert data["status"] in (
        "DRAFT",
        "PACKAGED",
        "MARKETED",
        "AUCTION_SCHEDULED",
        "UNDER_CONTRACT",
        "CLOSED",
        "WITHDRAWN",
    )


def assert_tract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert isinstance(data["tract_number"], int)
    assert data["gross_acres"] > 0
    assert 0 <= data["tillable_acres"] <= data["gross_acres"]
    assert 0 < data["soil_productivity_index"] <= 100
    assert data["min_price"] >= 0
    assert data["status"] in ("REGISTERED", "OFFERED", "SOLD", "UNSOLD", "WITHDRAWN")


def assert_comparable_sale(data: dict):
    """ComparableSale is immutable: only id + created_at among common fields."""
    _assert_common(data, with_version=False)
    assert "version" not in data, "immutable record must not carry version"
    assert "updated_at" not in data, "immutable record must not carry updated_at"
    assert isinstance(data["county"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert is_iso8601_timestamp(data["sale_date"])
    assert data["sale_price_total"] > 0
    assert data["gross_acres"] > 0
    assert data["soil_productivity_index"] > 0


def assert_auction(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert data["method"] in ("LIVE", "ONLINE", "SEALED_BID")
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert is_iso8601_timestamp(data["effective_end"])
    assert isinstance(data["extension_count"], int) and data["extension_count"] >= 0
    assert data["awarded_total"] is None or isinstance(
        data["awarded_total"], (int, float)
    )
    assert data["status"] in (
        "SCHEDULED",
        "OPEN",
        "EXTENDED",
        "CLOSED_PENDING_AWARD",
        "AWARDED",
        "NO_SALE",
        "CANCELLED",
    )


def assert_bid(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("auction_id", "")), "auction_id must be a UUID"
    assert is_valid_uuid(data.get("buyer_id", "")), "buyer_id must be a UUID"
    assert data["amount"] is None or data["amount"] > 0, (
        "amount is null while SEALED, otherwise positive"
    )
    assert isinstance(data["tract_ids"], list) and len(data["tract_ids"]) >= 1
    assert data["status"] in (
        "PLACED",
        "SEALED",
        "REVEALED",
        "OUTBID",
        "LOST",
        "CONFIRMED_WINNER",
        "VOIDED",
    )


def assert_deposit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("bid_id", "")), "bid_id must be a UUID"
    assert is_valid_uuid(data.get("buyer_id", "")), "buyer_id must be a UUID"
    for field in (
        "amount_due",
        "amount_received",
        "amount_refunded",
        "amount_forfeited",
        "amount_applied",
    ):
        assert isinstance(data[field], (int, float)) and data[field] >= 0
        assert_cost_precision(data[field])
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in (
        "PENDING",
        "RECEIVED",
        "LATE",
        "VERIFIED",
        "FORFEITED",
        "REFUNDED",
        "APPLIED_TO_CLOSING",
    )


def assert_disclosure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("tract_id", "")), "tract_id must be a UUID"
    assert isinstance(data["tenant_name"], str)
    assert is_iso8601_timestamp(data["lease_start_date"])
    assert is_iso8601_timestamp(data["lease_end_date"])
    assert data["annual_rent"] > 0
    assert data["acknowledged_by_buyer_id"] is None or is_valid_uuid(
        data["acknowledged_by_buyer_id"]
    )
    assert data["status"] in ("DISCLOSED", "ACKNOWLEDGED", "POSSESSION_TRANSFERRED")


def assert_rights(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("tract_id", "")), "tract_id must be a UUID"
    assert data["mineral_rights"] in ("CONVEYED", "RESERVED", "PARTIALLY_CONVEYED")
    assert data["wind_rights"] in ("CONVEYED", "RESERVED", "LEASED_TO_THIRD_PARTY")
    assert data["status"] in ("DECLARED", "LOCKED")


def assert_closing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("auction_id", "")), "auction_id must be a UUID"
    assert is_iso8601_timestamp(data["target_closing_date"])
    assert data["payoff_amount"] >= 0
    assert data["title_status"] in (
        "NOT_ORDERED",
        "ORDERED",
        "COMMITMENT_RECEIVED",
        "EXCEPTION_RAISED",
        "CLEARED",
    )
    assert data["survey_status"] in (
        "NOT_ORDERED",
        "ORDERED",
        "COMPLETED",
        "WAIVED",
    )
    assert data["funding_status"] in ("UNFUNDED", "FUNDS_RECEIVED", "DISBURSED")
    assert data["overall_status"] in (
        "INITIATED",
        "COORDINATION",
        "READY_TO_CLOSE",
        "CLOSED",
        "TERMINATED",
    )


def assert_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("closing_id", "")), "closing_id must be a UUID"
    assert data["variant"] in ("PROVISIONAL", "FINAL")
    for field in (
        "gross_price",
        "commission_amount",
        "allocated_seller_costs",
        "payoff_amount",
        "rent_credit",
        "seller_net",
    ):
        assert isinstance(data[field], (int, float))
        assert_cost_precision(data[field])
    if data["variant"] == "FINAL":
        assert isinstance(data["tract_allocations"], list), (
            "FINAL statements expose per-tract allocations"
        )
        for entry in data["tract_allocations"]:
            assert is_valid_uuid(entry.get("tract_id", ""))
            assert_cost_precision(entry["share"])
    else:
        assert data["tract_allocations"] is None, (
            "PROVISIONAL statements perform no per-tract allocation"
        )
    assert data["status"] in ("PROVISIONAL", "SUPERSEDED", "FINAL", "PAID")


def assert_escrow_conservation(deposit: dict):
    """Escrow dollars are conserved across a terminal allocation (PRD §3.7/§3.8):
    exactly one of refunded/forfeited/applied absorbs the received amount."""
    assert deposit["status"] in ("FORFEITED", "REFUNDED", "APPLIED_TO_CLOSING")
    received = deposit["amount_received"]
    total = (
        deposit["amount_refunded"]
        + deposit["amount_forfeited"]
        + deposit["amount_applied"]
    )
    assert total == pytest.approx(received, abs=0.005), (
        f"received {received} must equal refunded + forfeited + applied ({total})"
    )
    nonzero = [
        v
        for v in (
            deposit["amount_refunded"],
            deposit["amount_forfeited"],
            deposit["amount_applied"],
        )
        if abs(v) > 0.005
    ]
    assert len(nonzero) <= 1, "at most one terminal allocation may be nonzero"
