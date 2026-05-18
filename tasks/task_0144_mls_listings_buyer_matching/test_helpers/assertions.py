"""Entity assertions and domain invariant checkers.

Each assert_<entity>(data) validates the response shape against the
PRD-declared field set, including:
- id is a UUID (PRD §2.4).
- created_at / updated_at are ISO 8601 timestamps (PRD §2.4).
- Status enum values are members of PRD §2.11.
- Mutable resources carry updated_at and version.
- Counter and CommissionSplit carry NEITHER updated_at NOR version
  (PRD §2.4: "they have neither updated_at nor version because their
  content does not change after the row is emitted").
"""
from __future__ import annotations

from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Generic shape helpers
# ---------------------------------------------------------------------------
def _assert_common_mutable_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: mutable resources carry id, created_at, updated_at,
    version. version starts at 1 and increments by 1 on each successful
    mutation."""
    assert "id" in data, "id missing from response"
    assert is_valid_uuid(data["id"]), f"id is not a valid UUID: {data['id']!r}"
    assert "created_at" in data, "created_at missing"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at is not ISO 8601: {data['created_at']!r}"
    )
    assert "updated_at" in data, "updated_at missing"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at is not ISO 8601: {data['updated_at']!r}"
    )
    assert "version" in data, "version missing"
    assert isinstance(data["version"], int), "version is not int"
    assert data["version"] >= 1, f"version must be >= 1, got {data['version']}"


def _assert_common_immutable_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: immutable resources (Counter, CommissionSplit) carry
    ONLY id and created_at. They have NEITHER updated_at NOR version."""
    assert "id" in data, "id missing from response"
    assert is_valid_uuid(data["id"]), f"id is not a valid UUID: {data['id']!r}"
    assert "created_at" in data, "created_at missing"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at is not ISO 8601: {data['created_at']!r}"
    )


def _assert_in(value: Any, allowed: Iterable[str], field: str) -> None:
    assert value in allowed, (
        f"{field}={value!r} not in allowed set {sorted(allowed)}"
    )


# ---------------------------------------------------------------------------
# Agent — PRD §3.1
# ---------------------------------------------------------------------------
AGENT_ROLE_VALUES = {"LISTING_AGENT", "BUYER_AGENT", "DUAL_AGENT"}
AGENT_STATUS_VALUES = {"ACTIVE", "SUSPENDED"}


def assert_agent(data: Dict[str, Any]) -> None:
    _assert_common_mutable_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("brokerage_name"), str) and data["brokerage_name"]
    _assert_in(data.get("agent_role"), AGENT_ROLE_VALUES, "agent_role")
    assert isinstance(data.get("license_number"), str) and data["license_number"]
    # PRD §3.1: 0 < x <= 1.0, stored to 4 decimals.
    assert isinstance(data.get("brokerage_split_pct"), (int, float))
    assert 0.0 < float(data["brokerage_split_pct"]) <= 1.0, (
        f"brokerage_split_pct out of range: {data['brokerage_split_pct']!r}"
    )
    _assert_in(data.get("status"), AGENT_STATUS_VALUES, "status")


# ---------------------------------------------------------------------------
# Listing — PRD §3.2
# ---------------------------------------------------------------------------
LISTING_STATUS_VALUES = {
    "ACTIVE", "UNDER_CONTRACT", "SOLD", "WITHDRAWN", "EXPIRED",
}


def assert_listing(data: Dict[str, Any]) -> None:
    _assert_common_mutable_fields(data)
    assert is_valid_uuid(data.get("listing_agent_id", "")), (
        "listing_agent_id must be a valid UUID"
    )
    assert isinstance(data.get("address_line"), str) and data["address_line"]
    # PRD §3.2: zip_code must be exactly 5 digits.
    zc = data.get("zip_code", "")
    assert isinstance(zc, str) and len(zc) == 5 and zc.isdigit(), (
        f"zip_code must be exactly 5 digits, got {zc!r}"
    )
    # PRD §3.2: list_price_cents >= 1,000,000.
    assert isinstance(data.get("list_price_cents"), int)
    assert data["list_price_cents"] >= 1_000_000, (
        f"list_price_cents must be >= 1_000_000, got {data['list_price_cents']}"
    )
    assert isinstance(data.get("bedrooms"), int)
    assert 0 <= data["bedrooms"] <= 20
    assert isinstance(data.get("bathrooms"), (int, float))
    assert 0 <= float(data["bathrooms"]) <= 20
    assert isinstance(data.get("features"), list)
    # PRD §3.2 fiscal bounds.
    assert isinstance(data.get("co_op_pct"), (int, float))
    assert 0.0 <= float(data["co_op_pct"]) <= 0.06, (
        f"co_op_pct out of [0, 0.06]: {data['co_op_pct']!r}"
    )
    assert isinstance(data.get("total_commission_pct"), (int, float))
    assert (
        float(data["co_op_pct"]) <= float(data["total_commission_pct"]) <= 0.10
    ), (
        "total_commission_pct must be in [co_op_pct, 0.10], got "
        f"{data['total_commission_pct']!r} with co_op_pct={data['co_op_pct']!r}"
    )
    _assert_in(data.get("status"), LISTING_STATUS_VALUES, "status")
    # accepted_offer_id may be None.
    aoi = data.get("accepted_offer_id")
    if aoi is not None:
        assert is_valid_uuid(aoi), (
            f"accepted_offer_id must be UUID or None, got {aoi!r}"
        )
    assert isinstance(data.get("showing_count"), int)
    assert data["showing_count"] >= 0


# ---------------------------------------------------------------------------
# Buyer — PRD §3.3
# ---------------------------------------------------------------------------
BUYER_STATUS_VALUES = {"ACTIVE", "SOLD", "WITHDRAWN"}


def assert_buyer(data: Dict[str, Any]) -> None:
    _assert_common_mutable_fields(data)
    assert is_valid_uuid(data.get("buyer_agent_id", "")), (
        "buyer_agent_id must be valid UUID"
    )
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("max_price_cents"), int)
    assert isinstance(data.get("min_price_cents"), int)
    # PRD §3.3: min_price_cents <= max_price_cents.
    assert data["min_price_cents"] <= data["max_price_cents"]
    assert isinstance(data.get("min_bedrooms"), int)
    assert isinstance(data.get("min_bathrooms"), (int, float))
    # PRD §3.3: desired_zips non-empty.
    assert isinstance(data.get("desired_zips"), list)
    assert len(data["desired_zips"]) >= 1
    assert isinstance(data.get("desired_features"), list)
    _assert_in(data.get("status"), BUYER_STATUS_VALUES, "status")


# ---------------------------------------------------------------------------
# Lockbox — PRD §3.5
# ---------------------------------------------------------------------------
LOCKBOX_STATUS_VALUES = {"ARMED", "DISARMED", "RETIRED"}


def assert_lockbox(data: Dict[str, Any]) -> None:
    _assert_common_mutable_fields(data)
    assert is_valid_uuid(data.get("listing_id", "")), (
        "listing_id must be valid UUID"
    )
    assert isinstance(data.get("serial_number"), str) and data["serial_number"]
    # PRD §3.5: access_code is a 6-digit numeric string.
    ac = data.get("access_code")
    assert isinstance(ac, str) and len(ac) == 6 and ac.isdigit(), (
        f"access_code must be a 6-digit numeric string, got {ac!r}"
    )
    assert is_iso8601_timestamp(data.get("code_rotated_at", "")), (
        f"code_rotated_at must be ISO 8601, got {data.get('code_rotated_at')!r}"
    )
    _assert_in(data.get("status"), LOCKBOX_STATUS_VALUES, "status")


# ---------------------------------------------------------------------------
# ShowingAppointment — PRD §3.5
# ---------------------------------------------------------------------------
SHOWING_STATUS_VALUES = {
    "REQUESTED", "SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW",
}


def assert_showing(data: Dict[str, Any]) -> None:
    _assert_common_mutable_fields(data)
    assert is_valid_uuid(data.get("listing_id", ""))
    assert is_valid_uuid(data.get("buyer_agent_id", ""))
    assert is_valid_uuid(data.get("buyer_id", ""))
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    _assert_in(data.get("status"), SHOWING_STATUS_VALUES, "status")
    lag = data.get("lockbox_access_granted_at")
    if lag is not None:
        assert is_iso8601_timestamp(lag), (
            f"lockbox_access_granted_at must be ISO 8601 or null, got {lag!r}"
        )


# ---------------------------------------------------------------------------
# Offer — PRD §3.6
# ---------------------------------------------------------------------------
OFFER_STATUS_VALUES = {
    "SUBMITTED", "COUNTERED", "ACCEPTED", "REJECTED", "WITHDRAWN", "EXPIRED",
}


def assert_offer(data: Dict[str, Any]) -> None:
    _assert_common_mutable_fields(data)
    assert is_valid_uuid(data.get("listing_id", ""))
    assert is_valid_uuid(data.get("buyer_id", ""))
    assert isinstance(data.get("offer_price_cents"), int)
    assert data["offer_price_cents"] > 0
    assert isinstance(data.get("earnest_money_cents"), int)
    assert data["earnest_money_cents"] >= 0
    assert isinstance(data.get("estimated_seller_concessions_cents"), int)
    assert data["estimated_seller_concessions_cents"] >= 0
    assert isinstance(data.get("round_no"), int)
    assert data["round_no"] >= 1
    pci = data.get("parent_counter_id")
    if pci is not None:
        assert is_valid_uuid(pci)
    _assert_in(data.get("status"), OFFER_STATUS_VALUES, "status")
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    pnts = data.get("provisional_net_to_seller_cents")
    if pnts is not None:
        assert isinstance(pnts, int)


# ---------------------------------------------------------------------------
# Counter — PRD §3.6 (IMMUTABLE: no updated_at, no version)
# ---------------------------------------------------------------------------
COUNTER_STATUS_VALUES = {"OPEN", "REBOUND", "EXPIRED", "WITHDRAWN"}


def assert_counter(data: Dict[str, Any]) -> None:
    # PRD §2.4: Counter rows carry only id and created_at.
    _assert_common_immutable_fields(data)
    assert is_valid_uuid(data.get("offer_id", ""))
    assert isinstance(data.get("counter_price_cents"), int)
    assert data["counter_price_cents"] > 0
    assert isinstance(data.get("counter_concessions_cents"), int)
    assert is_iso8601_timestamp(data.get("counter_expires_at", ""))
    _assert_in(data.get("status"), COUNTER_STATUS_VALUES, "status")
    # PRD §2.4: counters have NEITHER updated_at NOR version.
    assert "updated_at" not in data, (
        "Counter rows are immutable; PRD §2.4 forbids updated_at"
    )
    assert "version" not in data, (
        "Counter rows are immutable; PRD §2.4 forbids version"
    )


# ---------------------------------------------------------------------------
# Contingency — PRD §3.7
# ---------------------------------------------------------------------------
CONTINGENCY_STATUS_VALUES = {"PENDING", "SATISFIED", "WAIVED", "FAILED"}
CONTINGENCY_KIND_VALUES = {"INSPECTION", "APPRAISAL", "FINANCING"}


def assert_contingency(data: Dict[str, Any]) -> None:
    _assert_common_mutable_fields(data)
    assert is_valid_uuid(data.get("offer_id", ""))
    _assert_in(data.get("kind"), CONTINGENCY_KIND_VALUES, "kind")
    assert is_iso8601_timestamp(data.get("deadline_at", ""))
    _assert_in(data.get("status"), CONTINGENCY_STATUS_VALUES, "status")


# ---------------------------------------------------------------------------
# CommissionSplit — PRD §3.8 (IMMUTABLE: no updated_at, no version)
# ---------------------------------------------------------------------------
COMMISSION_SPLIT_VARIANT_VALUES = {"PROVISIONAL", "FINAL"}


def assert_commission_split(data: Dict[str, Any]) -> None:
    # PRD §2.4: CommissionSplit rows carry only id and created_at.
    _assert_common_immutable_fields(data)
    assert is_valid_uuid(data.get("listing_id", ""))
    assert is_valid_uuid(data.get("offer_id", ""))
    assert isinstance(data.get("sale_price_cents"), int)
    assert isinstance(data.get("gross_commission_cents"), int)
    assert isinstance(data.get("listing_side_cents"), int)
    assert isinstance(data.get("buyer_side_cents"), int)
    assert isinstance(data.get("listing_agent_cents"), int)
    assert isinstance(data.get("listing_brokerage_cents"), int)
    assert isinstance(data.get("buyer_agent_cents"), int)
    assert isinstance(data.get("buyer_brokerage_cents"), int)
    _assert_in(data.get("variant"), COMMISSION_SPLIT_VARIANT_VALUES, "variant")
    # PRD §2.4: CommissionSplit rows have NEITHER updated_at NOR version.
    assert "updated_at" not in data, (
        "CommissionSplit rows are immutable; PRD §2.4 forbids updated_at"
    )
    assert "version" not in data, (
        "CommissionSplit rows are immutable; PRD §2.4 forbids version"
    )


# ---------------------------------------------------------------------------
# Commission residual invariants — PRD §3.8
# "listing_side_cents is the gross commission minus the buyer-side
# portion — a residual assignment that guarantees the two side totals
# add up exactly to the gross, with no penny drift".
# Each side's agent take + brokerage take must likewise sum exactly.
# ---------------------------------------------------------------------------
def assert_commission_residual_invariants(data: Dict[str, Any]) -> None:
    assert (
        data["gross_commission_cents"]
        == data["listing_side_cents"] + data["buyer_side_cents"]
    ), (
        "PRD §3.8 residual identity broken: gross != listing_side + buyer_side"
    )
    assert (
        data["listing_side_cents"]
        == data["listing_agent_cents"] + data["listing_brokerage_cents"]
    ), (
        "PRD §3.8 residual identity broken: listing_side != "
        "listing_agent + listing_brokerage"
    )
    assert (
        data["buyer_side_cents"]
        == data["buyer_agent_cents"] + data["buyer_brokerage_cents"]
    ), (
        "PRD §3.8 residual identity broken: buyer_side != "
        "buyer_agent + buyer_brokerage"
    )


def assert_version_incremented_by_one(new: Dict[str, Any],
                                      old: Dict[str, Any]) -> None:
    """PRD §2.6: version increments by exactly 1 on every successful
    mutation."""
    assert new["version"] == old["version"] + 1, (
        f"version must increment by exactly 1: {old['version']} -> "
        f"{new['version']}"
    )


__all__ = [
    "assert_agent",
    "assert_listing",
    "assert_buyer",
    "assert_lockbox",
    "assert_showing",
    "assert_offer",
    "assert_counter",
    "assert_contingency",
    "assert_commission_split",
    "assert_commission_residual_invariants",
    "assert_version_incremented_by_one",
]
