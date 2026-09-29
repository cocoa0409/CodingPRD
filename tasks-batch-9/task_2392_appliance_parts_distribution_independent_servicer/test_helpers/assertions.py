"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Generic shape helpers
# ---------------------------------------------------------------------------

def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a comparable instant.

    The PRD pins the *instant* a timestamp field carries, not the number of
    fractional digits used to serialise it, so timestamp assertions compare
    parsed instants rather than raw strings.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "timestamp"):
    """The field carries exactly the expected UTC instant."""
    assert _instant(actual) == _instant(expected), (
        f"Expected {label} to carry the instant {expected}, got {actual}"
    )

def assert_identity_fields(data: dict):
    """Every row carries a UUID `id` with no type prefix and an ISO 8601
    `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert "-" in str(data.get("id", "")), "id must not carry a type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


def assert_versioned_fields(data: dict):
    """Rows that are not append-only also carry `updated_at` and `version`."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_branch(data: dict):
    assert_versioned_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["will_call_enabled"], bool)
    assert isinstance(data["cutoff_hour_utc"], int)
    assert 0 <= data["cutoff_hour_utc"] <= 23
    assert isinstance(data["overnight_surcharge_cents"], int)
    assert data["overnight_surcharge_cents"] >= 0
    assert data["branch_status"] in ("OPEN", "COUNT_FREEZE", "CLOSED")


def assert_part(data: dict):
    assert_versioned_fields(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["oem_code"], str) and data["oem_code"]
    assert isinstance(data["description"], str)
    assert data["category"] in ("ELECTRICAL", "MECHANICAL", "COSMETIC", "SEALED_SYSTEM")
    assert data["lifecycle_status"] in ("ACTIVE", "SUPERSEDED", "OBSOLETE", "NLA")
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert isinstance(data["core_required"], bool)
    assert isinstance(data["core_deposit_cents"], int)
    assert isinstance(data["weight_grams"], int) and data["weight_grams"] > 0
    assert data["cert_level_required"] in ("NONE", "BASIC", "ADVANCED", "SEALED_SYSTEM")
    assert isinstance(data["is_returnable"], bool)


def assert_model_part_xref(data: dict):
    """A cross-reference row is immutable and append-only: it carries `id` and
    `created_at` only."""
    assert_identity_fields(data)
    assert "version" not in data, (
        "a model-to-part cross-reference carries no version field"
    )
    assert "updated_at" not in data, (
        "a model-to-part cross-reference carries no updated_at field"
    )
    assert isinstance(data["model_number"], str) and data["model_number"]
    assert is_valid_uuid(data["part_id"])
    assert isinstance(data["position_code"], str) and data["position_code"]
    assert data["xref_source"] in ("OEM_PUBLICATION", "MANUAL_ENTRY")


def assert_pricing_tier(data: dict):
    assert_versioned_fields(data)
    assert isinstance(data["tier_code"], str) and data["tier_code"]
    for field in (
        "discount_pct_electrical",
        "discount_pct_mechanical",
        "discount_pct_cosmetic",
        "discount_pct_sealed_system",
    ):
        assert 0 <= data[field] <= 0.45, f"{field} must be between 0 and 0.45 inclusive"
    assert isinstance(data["min_annual_volume_cents"], int)
    assert data["min_annual_volume_cents"] >= 0


def assert_servicer_account(data: dict):
    assert_versioned_fields(data)
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["oem_authorizations"], list)
    assert data["credit_terms"] in ("PREPAY", "NET_15", "NET_30", "NET_45")
    assert data["account_status"] in ("ACTIVE", "CREDIT_HOLD", "SUSPENDED")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["core_liability_limit_cents"], int)
    assert isinstance(data["credit_used_cents"], int)
    assert data["credit_used_cents"] >= 0, (
        "credit exposure is floored at zero, never negative"
    )
    assert isinstance(data["core_liability_cents"], int)
    assert 0 <= data["delinquency_score"] <= 100, (
        "the delinquency score is clamped into the range 0 through 100 inclusive"
    )


def assert_technician_certification(data: dict):
    assert_versioned_fields(data)
    assert isinstance(data["technician_name"], str) and data["technician_name"]
    assert data["cert_level"] in ("BASIC", "ADVANCED", "SEALED_SYSTEM")
    assert data["cert_status"] in ("ACTIVE", "EXPIRED", "REVOKED")
    assert isinstance(data["is_effective"], bool)


def assert_inventory_record(data: dict):
    assert_versioned_fields(data)
    assert isinstance(data["on_hand_units"], int)
    assert isinstance(data["reserved_units"], int)
    assert isinstance(data["available_units"], int)
    assert data["available_units"] == data["on_hand_units"] - data["reserved_units"], (
        "available_units is always on_hand_units minus reserved_units"
    )


def assert_price_file(data: dict):
    assert_versioned_fields(data)
    assert data["price_file_status"] in (
        "DRAFT", "PUBLISHED", "SUPERSEDED", "ROLLED_BACK"
    )
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0


def assert_part_order(data: dict):
    assert_versioned_fields(data)
    assert data["fulfillment_mode"] in ("WILL_CALL", "OVERNIGHT_DROP_SHIP")
    assert data["fulfillment_status"] in (
        "DRAFT", "ALLOCATED", "HELD", "FULFILLED", "CANCELLED"
    )
    assert data["settlement_status"] in (
        "PENDING_CREDIT", "CREDIT_APPROVED", "CREDIT_DECLINED",
        "INVOICED", "PAID", "WRITTEN_OFF",
    )
    assert data["pricing_basis"] in ("ORDER_DATE", "SHIP_DATE")
    if data["fulfillment_status"] == "HELD":
        assert data["hold_reason"] in (
            "SUBSTITUTE_PENDING", "CREDIT_HOLD", "BACKORDER"
        )
    else:
        assert data["hold_reason"] is None, (
            "hold_reason is null whenever fulfillment_status is not HELD"
        )
    assert data["total_cents"] == (
        data["subtotal_cents"] + data["core_deposit_total_cents"] + data["freight_cents"]
    ), "total_cents is subtotal plus core deposit total plus freight"


def assert_order_line(data: dict):
    assert_versioned_fields(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["line_status"] in (
        "REQUESTED", "RESOLVED", "ALLOCATED", "BACKORDERED",
        "SUBSTITUTE_PENDING", "SHIPPED", "RETURNED", "CANCELLED",
    )
    assert data["line_status"] != "REQUESTED", (
        "no persisted line is ever observed in REQUESTED"
    )
    assert isinstance(data["supersession_hops"], int)
    assert 0 <= data["supersession_hops"] <= 5
    assert isinstance(data["returned_units"], int)
    assert data["returned_units"] <= data["quantity"]


def assert_substitute_request(data: dict):
    assert_versioned_fields(data)
    assert data["request_status"] in ("PENDING", "APPROVED", "REJECTED", "WITHDRAWN")
    assert data["source"] in ("CHAIN_TERMINAL_OBSOLETE", "PRICE_FILE_OBSOLESCENCE")


def assert_warranty_claim(data: dict):
    assert_versioned_fields(data)
    assert data["claim_status"] in (
        "DRAFT", "SUBMITTED", "OEM_INFO_REQUESTED", "OEM_APPROVED",
        "OEM_DENIED", "CREDITED", "VOID",
    )
    assert isinstance(data["resubmission_count"], int)
    assert 0 <= data["resubmission_count"] <= 2


def assert_return_authorization(data: dict):
    assert_versioned_fields(data)
    assert data["ra_status"] in (
        "REQUESTED", "APPROVED", "REJECTED", "RECEIVED", "CREDITED"
    )
    assert data["reason_code"] in (
        "WRONG_PART", "DEFECTIVE_ON_ARRIVAL", "NO_LONGER_NEEDED", "CORE_RETURN"
    )
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["fee_waived"], bool)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_restocking_split_reconstitutes_gross(ra: dict):
    """Fee plus credit always equals the gross return amount exactly."""
    assert ra["restocking_fee_cents"] + ra["credit_amount_cents"] == (
        ra["gross_return_cents"]
    ), (
        "restocking_fee_cents plus credit_amount_cents must reconstitute "
        f"gross_return_cents exactly, got {ra['restocking_fee_cents']} + "
        f"{ra['credit_amount_cents']} != {ra['gross_return_cents']}"
    )


def assert_inventory_units(record: dict, on_hand: int, reserved: int, available: int):
    """Pin all three unit counters of one inventory position."""
    assert record["on_hand_units"] == on_hand, (
        f"Expected on_hand_units {on_hand}, got {record['on_hand_units']}"
    )
    assert record["reserved_units"] == reserved, (
        f"Expected reserved_units {reserved}, got {record['reserved_units']}"
    )
    assert record["available_units"] == available, (
        f"Expected available_units {available}, got {record['available_units']}"
    )


def assert_order_money(order: dict, subtotal: int, freight: int, total: int,
                       core_deposit_total: int = None):
    assert order["subtotal_cents"] == subtotal, (
        f"Expected subtotal_cents {subtotal}, got {order['subtotal_cents']}"
    )
    assert order["freight_cents"] == freight, (
        f"Expected freight_cents {freight}, got {order['freight_cents']}"
    )
    assert order["total_cents"] == total, (
        f"Expected total_cents {total}, got {order['total_cents']}"
    )
    if core_deposit_total is not None:
        assert order["core_deposit_total_cents"] == core_deposit_total, (
            f"Expected core_deposit_total_cents {core_deposit_total}, "
            f"got {order['core_deposit_total_cents']}"
        )


def assert_catalog_list_price_sum(parts: list, expected_sum: int):
    """The sum of `list_price_cents` across the catalog."""
    actual = sum(part["list_price_cents"] for part in parts)
    assert actual == expected_sum, (
        f"Expected catalog list-price sum {expected_sum}, got {actual}"
    )
