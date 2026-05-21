"""Per-entity assertions and domain invariant checkers.

Each assertion validates an entity's response against its PRD-defined
shape. Fields with PRD-defined enums or numeric ranges are checked.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields assertion — for entities carrying id + created_at +
# updated_at + version (PRD §2.4).
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a UUID; got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601; got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601; got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be int; got {data.get('version')!r}"
    )
    assert data["version"] >= 1, (
        f"version must start at 1; got {data['version']}"
    )


def assert_lean_fields(data: Dict[str, Any]) -> None:
    """For event-style records (TollEvent, ReloadEvent, InteropPolicy).

    PRD §2.4: these carry only `id` and `created_at` — no `updated_at`
    and no `version`.
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a UUID; got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601; got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------
def assert_account(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["holder_name"], str) and (
        1 <= len(data["holder_name"]) <= 120
    )
    assert data["home_agency_code"] in {
        "NY_EZPASS", "NJ_EZPASS", "PA_TURNPIKE", "FL_SUNPASS"
    }
    assert isinstance(data["balance_cents"], int), (
        "balance_cents must be int"
    )
    assert isinstance(data["auto_reload_enabled"], bool)
    assert isinstance(data["auto_reload_threshold_cents"], int)
    assert 0 <= data["auto_reload_threshold_cents"] <= 10000
    assert isinstance(data["auto_reload_topup_cents"], int)
    assert 1000 <= data["auto_reload_topup_cents"] <= 20000
    assert data["status"] in {"ACTIVE", "SUSPENDED", "CLOSED"}
    assert isinstance(data["outstanding_fine_cents"], int)
    assert data["outstanding_fine_cents"] >= 0


# ---------------------------------------------------------------------------
# Vehicle
# ---------------------------------------------------------------------------
def assert_vehicle(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["plate_number"], str)
    assert 1 <= len(data["plate_number"]) <= 10
    assert data["plate_state"] in {
        "NY", "NJ", "PA", "FL", "CA", "TX", "OTHER"
    }
    assert isinstance(data["axle_count"], int)
    assert 2 <= data["axle_count"] <= 7
    assert data["vehicle_class"] in {
        "CLASS_2", "CLASS_3", "CLASS_4", "CLASS_5_PLUS"
    }
    assert isinstance(data["hov_capable"], bool)
    assert data["status"] in {"ACTIVE", "BLOCKED"}


# ---------------------------------------------------------------------------
# Transponder
# ---------------------------------------------------------------------------
def assert_transponder(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["serial_number"], str)
    assert 10 <= len(data["serial_number"]) <= 24
    assert data["status"] in {
        "UNBOUND", "ACTIVE", "SUSPENDED", "RETURNED"
    }
    bv = data.get("bound_vehicle_id")
    if bv is not None:
        assert is_valid_uuid(bv), (
            f"bound_vehicle_id must be a UUID when present; got {bv!r}"
        )
    bound_at = data.get("bound_at")
    if bound_at is not None:
        assert is_iso8601_timestamp(bound_at), (
            f"bound_at must be ISO-8601 when present; got {bound_at!r}"
        )


# ---------------------------------------------------------------------------
# TollEvent — event-style: id + created_at only
# ---------------------------------------------------------------------------
def assert_toll_event(data: Dict[str, Any]) -> None:
    assert_lean_fields(data)
    assert isinstance(data["gantry_id"], str)
    assert 1 <= len(data["gantry_id"]) <= 32
    assert data["agency_code"] in {
        "NY_EZPASS", "NJ_EZPASS", "PA_TURNPIKE", "FL_SUNPASS"
    }
    assert isinstance(data["base_rate_cents"], int)
    assert data["base_rate_cents"] >= 0
    assert is_iso8601_timestamp(data["read_at"]), (
        f"read_at must be ISO 8601; got {data['read_at']!r}"
    )
    assert data["billing_status"] in {
        "PENDING", "POSTED", "TOLL_BY_PLATE_INVOICED",
        "VIOLATED", "EXEMPTED", "VOIDED",
    }
    cm = data.get("capture_method")
    assert cm in {None, "TRANSPONDER", "PLATE", "UNRESOLVED"}, (
        f"capture_method must be one of TRANSPONDER/PLATE/UNRESOLVED "
        f"or null; got {cm!r}"
    )
    assert isinstance(data["gross_toll_cents"], int)
    assert data["gross_toll_cents"] >= 0
    assert isinstance(data["net_toll_cents"], int)
    assert data["net_toll_cents"] >= 0
    assert isinstance(data["hov_exempt_applied"], bool)


# ---------------------------------------------------------------------------
# ReloadEvent — event-style
# ---------------------------------------------------------------------------
def assert_reload_event(data: Dict[str, Any]) -> None:
    assert_lean_fields(data)
    assert data["kind"] in {"MANUAL", "AUTO"}
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 1
    assert isinstance(data["balance_before_cents"], int)
    assert isinstance(data["balance_after_cents"], int)
    # PRD §3.4: "captures balance_after_cents as the credited value"
    assert (
        data["balance_after_cents"]
        == data["balance_before_cents"] + data["amount_cents"]
    ), (
        f"balance_after_cents must equal balance_before_cents + "
        f"amount_cents; got before={data['balance_before_cents']} "
        f"after={data['balance_after_cents']} amount={data['amount_cents']}"
    )
    if data["kind"] == "MANUAL":
        # PRD §3.4: "a MANUAL reload leaves that field null".
        assert data.get("triggered_by_event_id") in (None,)


# ---------------------------------------------------------------------------
# Violation — common fields
# ---------------------------------------------------------------------------
def assert_violation(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["toll_event_id"])
    assert data["reason_code"] in {
        "UNREAD_TRANSPONDER_NO_PLATE",
        "INSUFFICIENT_FUNDS_ON_PLATE_BILL",
        "BLOCKED_VEHICLE",
        "HOV_FRAUD",
    }
    assert data["status"] in {"OPEN", "CLEARED", "ESCALATED"}


# ---------------------------------------------------------------------------
# Fine — common fields
# ---------------------------------------------------------------------------
def assert_fine(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 0
    assert isinstance(data["civil_penalty_cents"], int)
    assert data["civil_penalty_cents"] >= 0
    assert data["settlement_status"] in {
        "PENDING", "OVERDUE", "DISPUTED", "SETTLED", "DISMISSED"
    }
    assert is_iso8601_timestamp(data["due_at"])
    assert is_iso8601_timestamp(data["issued_at"])
    assert isinstance(data["dispute_count"], int)
    assert 0 <= data["dispute_count"] <= 2


# ---------------------------------------------------------------------------
# InteropPolicy — event-style
# ---------------------------------------------------------------------------
def assert_interop_policy(data: Dict[str, Any]) -> None:
    assert_lean_fields(data)
    assert data["home_agency"] in {
        "NY_EZPASS", "NJ_EZPASS", "PA_TURNPIKE", "FL_SUNPASS"
    }
    assert data["gantry_agency"] in {
        "NY_EZPASS", "NJ_EZPASS", "PA_TURNPIKE", "FL_SUNPASS"
    }
    assert isinstance(data["surcharge_bps"], int)
    assert 0 <= data["surcharge_bps"] <= 5000
    assert isinstance(data["discount_bps"], int)
    assert 0 <= data["discount_bps"] <= 5000


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_version_incremented_by(new_version: int,
                                  old_version: int,
                                  delta: int = 1) -> None:
    """PRD §2.4: "version starts at 1 and increments by 1 on every
    mutation." Some operations cascade and mutate twice — delta lets
    callers state the expected step count."""
    assert new_version == old_version + delta, (
        f"version expected to increment by {delta}: "
        f"old={old_version} new={new_version}"
    )


def assert_account_outstanding_matches_sum(
    account_outstanding_cents: int,
    pending_or_overdue_fine_amounts: list[int],
) -> None:
    """PRD §3.5: "outstanding_fine_cents [is] the sum of `amount_cents`
    of every fine tied to the account whose `settlement_status` is
    `PENDING` or `OVERDUE`."""
    expected = sum(pending_or_overdue_fine_amounts)
    assert account_outstanding_cents == expected, (
        f"outstanding_fine_cents={account_outstanding_cents} but "
        f"sum(PENDING|OVERDUE)={expected}"
    )


__all__ = [
    "assert_common_fields",
    "assert_lean_fields",
    "assert_account",
    "assert_vehicle",
    "assert_transponder",
    "assert_toll_event",
    "assert_reload_event",
    "assert_violation",
    "assert_fine",
    "assert_interop_policy",
    "assert_version_incremented_by",
    "assert_account_outstanding_matches_sum",
]
