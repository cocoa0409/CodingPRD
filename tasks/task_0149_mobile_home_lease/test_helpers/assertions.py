"""Entity assertions and domain invariant checkers.

PRD §2.4 — entities split into two shapes:

    common-fields (Park, Lot, Home, Resident, Lease, RentIncreaseNotice,
    EvictionCase, HomeSaleTransfer, ConversionRequest):
        id, created_at, updated_at, version

    lean (UtilityBill):
        id, created_at only — no updated_at, no version.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    APPORTIONMENT_METHODS,
    STATE_CODES,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'version — an integer that begins at 1 and increments
    by exactly one with each mutation that refreshes updated_at.'"""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4 common-fields entities."""
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)


def assert_lean_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4 lean entities (UtilityBill) — no updated_at, no version."""
    _assert_id_and_created_at(data)
    # PRD §2.4 explicitly excludes these on UtilityBill.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "UtilityBill must not expose updated_at per PRD §2.4"
    )
    assert "version" not in data or data.get("version") is None, (
        "UtilityBill must not expose version per PRD §2.4"
    )


def assert_version_incremented_by(
    before: Dict[str, Any], after: Dict[str, Any], delta: int = 1,
) -> None:
    """PRD §2.7: every mutation increments version by exactly one."""
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version']}+{delta} = "
        f"{before['version'] + delta}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_park(data: Dict[str, Any]) -> None:
    """PRD §3.1 Park fields."""
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["state_code"] in STATE_CODES, (
        f"unexpected state_code: {data.get('state_code')!r}"
    )
    assert isinstance(data["master_cpi_pct"], (int, float))
    assert 0.0 <= float(data["master_cpi_pct"]) <= 20.0
    assert data["utility_apportionment_method"] in APPORTIONMENT_METHODS, (
        f"unexpected utility_apportionment_method: "
        f"{data.get('utility_apportionment_method')!r}"
    )
    assert isinstance(data["billing_period_anchor_day"], int)
    assert 1 <= data["billing_period_anchor_day"] <= 28
    assert isinstance(data["ownership_pool_count"], int)
    assert data["ownership_pool_count"] >= 0


def assert_lot(data: Dict[str, Any]) -> None:
    """PRD §3.1 Lot fields."""
    assert_common_fields(data)
    assert isinstance(data["park_id"], str) and data["park_id"]
    assert isinstance(data["lot_number"], str)
    assert 1 <= len(data["lot_number"]) <= 16
    assert data["ownership_mode"] in ("PARK_OWNED", "RESIDENT_OWNED"), (
        f"unexpected ownership_mode: {data.get('ownership_mode')!r}"
    )
    assert isinstance(data["base_rent_cents"], int)
    assert data["base_rent_cents"] > 0
    assert isinstance(data["sub_meter_reading_kwh"], (int, float))
    assert float(data["sub_meter_reading_kwh"]) >= 0.0
    # home_id and current_lease_id are nullable
    assert "home_id" in data
    assert "current_lease_id" in data


def assert_home(data: Dict[str, Any]) -> None:
    """PRD §3.1 Home fields."""
    assert_common_fields(data)
    assert isinstance(data["park_id"], str) and data["park_id"]
    # lot_id may be transiently null during sale handover per PRD §3.1
    assert "lot_id" in data
    # owner_resident_id is null when Lot.ownership_mode == PARK_OWNED
    assert "owner_resident_id" in data
    assert isinstance(data["vin"], str)
    assert len(data["vin"]) == 17, (
        f"PRD §3.1: VIN must be exactly 17 chars, got len={len(data['vin'])}"
    )
    assert isinstance(data["assessed_value_cents"], int)
    assert data["assessed_value_cents"] > 0


def assert_resident(data: Dict[str, Any]) -> None:
    """PRD §3.1 Resident fields."""
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert 1 <= len(data["full_name"]) <= 120
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["violation_count_12mo"], int)
    assert data["violation_count_12mo"] >= 0


def assert_lease(data: Dict[str, Any]) -> None:
    """PRD §3.2/§3.3 Lease fields."""
    assert_common_fields(data)
    assert isinstance(data["lot_id"], str) and data["lot_id"]
    assert isinstance(data["resident_id"], str) and data["resident_id"]
    # monthly_rent_cents is uninitialised until signing (PRD §3.2).
    assert "monthly_rent_cents" in data
    assert isinstance(data["start_date"], str)
    assert data["status"] in (
        "DRAFT", "CURRENT", "DELINQUENT", "GRACE", "TERMINATED", "ASSUMED",
    ), f"unexpected lease status: {data.get('status')!r}"
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0
    # predecessor_lease_id is null on original leases (PRD §3.2)
    assert "predecessor_lease_id" in data


def assert_rent_increase_notice(data: Dict[str, Any]) -> None:
    """PRD §3.5 RentIncreaseNotice fields."""
    assert_common_fields(data)
    assert isinstance(data["lease_id"], str) and data["lease_id"]
    assert isinstance(data["proposed_new_rent_cents"], int)
    assert data["proposed_new_rent_cents"] > 0
    assert isinstance(data["effective_on"], str)
    assert "capped_new_rent_cents" in data  # null until issuance
    assert data["status"] in ("DRAFT", "ISSUED", "EFFECTIVE", "VOIDED"), (
        f"unexpected notice status: {data.get('status')!r}"
    )


def assert_eviction_case(data: Dict[str, Any]) -> None:
    """PRD §3.6 EvictionCase fields."""
    assert_common_fields(data)
    assert isinstance(data["lease_id"], str) and data["lease_id"]
    assert data["violation_type"] in (
        "NONPAYMENT", "RULE_VIOLATION", "ILLEGAL_USE",
    ), f"unexpected violation_type: {data.get('violation_type')!r}"
    assert isinstance(data["filed_at"], str) and is_iso8601_timestamp(
        data["filed_at"]
    )
    # cure_deadline is null when violation_type == ILLEGAL_USE.
    assert "cure_deadline" in data
    assert data["status"] in (
        "FILED", "IN_CURE", "CURED", "FINALIZED_FOR_CAUSE", "DISMISSED",
    ), f"unexpected case status: {data.get('status')!r}"


def assert_utility_bill(data: Dict[str, Any]) -> None:
    """PRD §3.3 UtilityBill fields — lean entity per PRD §2.4."""
    assert_lean_fields(data)
    assert isinstance(data["lot_id"], str) and data["lot_id"]
    # lease_id may be null (PRD §3.3 'or null if the lot is vacant').
    assert "lease_id" in data
    assert isinstance(data["billing_period_start"], str)
    assert isinstance(data["billing_period_end"], str)
    assert isinstance(data["master_total_cents"], int)
    assert data["master_total_cents"] >= 0
    assert isinstance(data["lot_share_cents"], int)
    assert data["lot_share_cents"] >= 0
    assert isinstance(data["rent_due_cents"], int)
    assert data["rent_due_cents"] >= 0
    assert isinstance(data["total_due_cents"], int)
    assert data["total_due_cents"] == (
        data["rent_due_cents"] + data["lot_share_cents"]
    ), (
        "PRD §3.3: 'Each bill's total_due_cents is then the sum of its "
        "rent_due_cents and its lot_share_cents.'"
    )
    # paid_at is nullable until marked paid
    assert "paid_at" in data


def assert_home_sale_transfer(data: Dict[str, Any]) -> None:
    """PRD §3.7 HomeSaleTransfer fields."""
    assert_common_fields(data)
    assert isinstance(data["home_id"], str) and data["home_id"]
    assert isinstance(data["seller_resident_id"], str) and data["seller_resident_id"]
    assert isinstance(data["buyer_resident_id"], str) and data["buyer_resident_id"]
    assert isinstance(data["sale_price_cents"], int)
    assert data["sale_price_cents"] > 0
    assert data["status"] in (
        "PENDING_PARK_APPROVAL", "APPROVED", "REJECTED", "CLOSED",
    ), f"unexpected transfer status: {data.get('status')!r}"
    # new_lease_id is null until close cascade runs (PRD §3.7).
    assert "new_lease_id" in data


def assert_conversion_request(data: Dict[str, Any]) -> None:
    """PRD §3.8 ConversionRequest fields."""
    assert_common_fields(data)
    assert isinstance(data["lot_id"], str) and data["lot_id"]
    assert isinstance(data["prospective_buyer_resident_id"], str)
    assert data["prospective_buyer_resident_id"]
    assert isinstance(data["offer_price_cents"], int)
    assert data["offer_price_cents"] > 0
    assert data["status"] in ("OFFERED", "ACCEPTED", "REJECTED", "CLOSED"), (
        f"unexpected conversion status: {data.get('status')!r}"
    )


__all__ = [
    "assert_common_fields",
    "assert_lean_fields",
    "assert_version_incremented_by",
    "assert_park",
    "assert_lot",
    "assert_home",
    "assert_resident",
    "assert_lease",
    "assert_rent_increase_notice",
    "assert_eviction_case",
    "assert_utility_bill",
    "assert_home_sale_transfer",
    "assert_conversion_request",
]
