"""Entity assertions and domain invariant checkers for the Shared Office API.

Each assert_<entity>(data) validates the shape and field domain of a server response
against the PRD contract. Per PRD §2.4:
  - Tenant/Member/Lease/Resource/Reservation/AccessBadge/Bill carry id + created_at
    + updated_at + version.
  - Visitor and BillLine omit updated_at and version.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ──────────────────────────────────────────────────────────
# Common helpers
# ──────────────────────────────────────────────────────────


def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID; got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601; got {data.get('created_at')}"


def _assert_versioned(data: Dict[str, Any]) -> None:
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601; got {data.get('updated_at')}"
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, f"version must be int >= 1; got {version}"


def _assert_optional_timestamp(data: Dict[str, Any], key: str) -> None:
    v = data.get(key)
    if v is None:
        return
    assert is_iso8601_timestamp(v), f"{key} must be ISO 8601 or null; got {v}"


# ──────────────────────────────────────────────────────────
# Entity assertions
# ──────────────────────────────────────────────────────────


def assert_tenant(data: Dict[str, Any]) -> None:
    """Shape-check a Tenant response per PRD §2.4, §3.1, §2.10."""
    _assert_id_and_created_at(data)
    _assert_versioned(data)
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0
    assert data["access_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert data["status"] in ("ACTIVE", "TERMINATING", "CLOSED")


def assert_member(data: Dict[str, Any]) -> None:
    """Shape-check a Member response per PRD §2.4, §3.1."""
    _assert_id_and_created_at(data)
    _assert_versioned(data)
    assert isinstance(data["tenant_id"], str) and is_valid_uuid(data["tenant_id"])
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["role_in_tenant"] in ("ADMIN", "STAFF")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "REVOKED")


def assert_lease(data: Dict[str, Any]) -> None:
    """Shape-check a Lease response per PRD §2.4, §3.1, §3.6."""
    _assert_id_and_created_at(data)
    _assert_versioned(data)
    assert is_valid_uuid(data["tenant_id"])
    assert data["billing_plan"] in ("HOURLY", "DAILY", "MONTHLY")
    assert isinstance(data["monthly_rate_cents"], int) and data["monthly_rate_cents"] >= 0
    assert isinstance(data["term_start_date"], str)
    assert isinstance(data["term_end_date"], str)
    assert data["status"] in (
        "DRAFT",
        "ACTIVE",
        "TERMINATION_REQUESTED",
        "TERMINATION_REVIEWING",
        "TERMINATED",
        "REJECTED",
    )
    assert isinstance(data["termination_penalty_cents"], int)
    assert data["termination_penalty_cents"] >= 0


def assert_resource(data: Dict[str, Any]) -> None:
    """Shape-check a Resource response per PRD §2.4, §3.2."""
    _assert_id_and_created_at(data)
    _assert_versioned(data)
    assert data["kind"] in ("WORKSTATION", "MEETING_ROOM", "EVENT_AREA")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    for rate_field in ("hourly_rate_cents", "daily_rate_cents", "block_rate_cents"):
        assert isinstance(data[rate_field], int) and data[rate_field] >= 0
    assert data["status"] in ("AVAILABLE", "MAINTENANCE", "RETIRED")


def assert_reservation(data: Dict[str, Any]) -> None:
    """Shape-check a Reservation response per PRD §2.4, §3.3."""
    _assert_id_and_created_at(data)
    _assert_versioned(data)
    assert is_valid_uuid(data["tenant_id"])
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["resource_id"])
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert data["status"] in (
        "PENDING",
        "CONFIRMED",
        "IN_USE",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
    )
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["final_fee_cents"], int)
    _assert_optional_timestamp(data, "actual_start_at")
    _assert_optional_timestamp(data, "actual_end_at")
    if data.get("bill_id") is not None:
        assert is_valid_uuid(data["bill_id"])


def assert_visitor(data: Dict[str, Any]) -> None:
    """Shape-check a Visitor response. PRD §2.4 pins Visitor as lighter: id +
    created_at only (no updated_at, no version)."""
    _assert_id_and_created_at(data)
    # PRD §2.4: updated_at and version are intentionally absent on Visitor.
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert is_valid_uuid(data["host_member_id"])
    assert is_valid_uuid(data["tenant_id"])
    assert isinstance(data["visitor_name"], str) and len(data["visitor_name"]) > 0
    assert is_iso8601_timestamp(data["expected_arrival_at"])
    assert is_iso8601_timestamp(data["expected_departure_at"])
    _assert_optional_timestamp(data, "actual_arrival_at")
    _assert_optional_timestamp(data, "actual_departure_at")
    assert data["status"] in ("REGISTERED", "CHECKED_IN", "CHECKED_OUT", "NO_SHOW", "REVOKED")
    assert isinstance(data["overstay_fee_cents"], int) and data["overstay_fee_cents"] >= 0
    if data.get("bill_id") is not None:
        assert is_valid_uuid(data["bill_id"])


def assert_access_badge(data: Dict[str, Any]) -> None:
    """Shape-check an AccessBadge response per PRD §2.4, §3.5."""
    _assert_id_and_created_at(data)
    _assert_versioned(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["badge_serial"], str) and len(data["badge_serial"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "REVOKED")
    _assert_optional_timestamp(data, "last_used_at")


def assert_bill(data: Dict[str, Any]) -> None:
    """Shape-check a Bill response per PRD §2.4, §3.7, §2.9."""
    _assert_id_and_created_at(data)
    _assert_versioned(data)
    assert is_valid_uuid(data["tenant_id"])
    assert isinstance(data["period_start_date"], str)
    assert isinstance(data["period_end_date"], str)
    for money_field in ("subtotal_cents", "tax_cents", "late_fee_cents", "total_due_cents"):
        v = data[money_field]
        assert isinstance(v, int) and v >= 0, f"{money_field} must be non-negative int; got {v}"
    # PRD §2.9: total_due_cents = subtotal_cents + tax_cents + late_fee_cents (plain sum).
    assert (
        data["total_due_cents"]
        == data["subtotal_cents"] + data["tax_cents"] + data["late_fee_cents"]
    ), (
        "Per PRD §2.9, total_due_cents is the plain sum of subtotal_cents, tax_cents, "
        "and late_fee_cents."
    )
    assert data["status"] in ("DRAFT", "ISSUED", "OVERDUE", "PAID", "VOIDED")
    _assert_optional_timestamp(data, "issued_at")
    _assert_optional_timestamp(data, "due_at")
    _assert_optional_timestamp(data, "paid_at")


def assert_bill_line(data: Dict[str, Any]) -> None:
    """Shape-check a BillLine. PRD §2.4: BillLines are append-only; id +
    created_at only (no updated_at, no version)."""
    _assert_id_and_created_at(data)
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert is_valid_uuid(data["bill_id"])
    assert data["line_kind"] in (
        "WORKSTATION_FEE",
        "MEETING_ROOM_FEE",
        "EVENT_AREA_FEE",
        "VISITOR_OVERSTAY",
        "TERMINATION_PENALTY",
        "MONTHLY_COMMITMENT",
    )
    assert is_valid_uuid(data["source_entity_id"])
    assert isinstance(data["amount_cents"], int)


# ──────────────────────────────────────────────────────────
# Domain invariants
# ──────────────────────────────────────────────────────────


def assert_bill_totals_consistent(bill: Dict[str, Any]) -> None:
    """PRD §2.9: total_due_cents is subtotal_cents + tax_cents + late_fee_cents (plain sum)."""
    assert (
        bill["total_due_cents"]
        == bill["subtotal_cents"] + bill["tax_cents"] + bill["late_fee_cents"]
    )


def assert_bill_sum_then_round_tax(bill: Dict[str, Any], tax_rate: float = 0.0825) -> None:
    """PRD §2.9 / §3.7: tax_cents = round_half_up(subtotal_cents * 0.0825) — sum-then-round."""
    expected_tax = _round_half_up(bill["subtotal_cents"] * tax_rate)
    assert bill["tax_cents"] == expected_tax, (
        f"tax_cents must equal round_half_up(subtotal_cents * {tax_rate}); "
        f"got tax_cents={bill['tax_cents']}, subtotal_cents={bill['subtotal_cents']}, "
        f"expected={expected_tax}"
    )


def _round_half_up(x: float) -> int:
    """Integer cents via half-up rounding. PRD §2.9 pins half-up, not banker's."""
    import math

    if x >= 0:
        return int(math.floor(x + 0.5))
    return -int(math.floor(-x + 0.5))


def round_half_up(x: float) -> int:
    """Public helper: half-up rounding to int per PRD §2.9."""
    return _round_half_up(x)
