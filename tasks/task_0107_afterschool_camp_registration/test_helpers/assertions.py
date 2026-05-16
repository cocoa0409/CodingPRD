"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract. They are intentionally generous about server-minted
fields: a test that wants to pin a specific computed value asserts it
directly in test code.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
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
    """PRD §2.4: every entity that participates in update workflows
    carries four system-managed properties: id, created_at, updated_at,
    and version. Asserted on Family, Guardian, Child, EmergencyContact,
    Session, Enrollment, ScholarshipAward.
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Family — PRD §3.1
# ---------------------------------------------------------------------------
def assert_family(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("household_name"), str) and data[
        "household_name"
    ]
    # PRD §3.1: primary_email is "lower-cased on intake".
    assert isinstance(data.get("primary_email"), str)
    assert data["primary_email"] == data["primary_email"].lower(), (
        f"primary_email must be lower-cased on intake, got "
        f"{data['primary_email']!r}"
    )
    assert data.get("residency_status") in {
        "STANDARD", "IN_DISTRICT", "OUT_OF_DISTRICT",
    }
    assert isinstance(data.get("archived"), bool)


# ---------------------------------------------------------------------------
# Guardian — PRD §3.1
# ---------------------------------------------------------------------------
def assert_guardian(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("family_id", ""))
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("phone"), str)
    assert data.get("relationship") in {
        "PARENT", "STEP_PARENT", "LEGAL_GUARDIAN", "OTHER",
    }
    assert isinstance(data.get("is_primary"), bool)


# ---------------------------------------------------------------------------
# Child — PRD §3.1
# ---------------------------------------------------------------------------
def assert_child(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("family_id", ""))
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str)
    # PRD §2.12: medical_authorization_status and
    # pickup_authorization_status are each one of NONE, ACTIVE, EXPIRED.
    assert data.get("medical_authorization_status") in {
        "NONE", "ACTIVE", "EXPIRED",
    }
    assert data.get("pickup_authorization_status") in {
        "NONE", "ACTIVE", "EXPIRED",
    }
    assert (
        isinstance(data.get("emergency_contact_count"), int)
        and data["emergency_contact_count"] >= 0
    )


# ---------------------------------------------------------------------------
# EmergencyContact — PRD §3.2
# ---------------------------------------------------------------------------
def assert_emergency_contact(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("child_id", ""))
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("phone"), str)
    assert isinstance(data.get("relationship"), str)
    assert isinstance(data.get("priority"), int)
    # PRD §3.2: integer priority between 1 and 9 inclusive.
    assert 1 <= data["priority"] <= 9
    assert isinstance(data.get("archived"), bool)


# ---------------------------------------------------------------------------
# Authorization — PRD §3.2; PRD §2.4 lean entity (id + created_at only)
# ---------------------------------------------------------------------------
def assert_authorization(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: "Authorization and SessionDay carry only id and
    # created_at — both updated_at and version are absent on these
    # rows." So we do NOT assert updated_at/version.
    assert is_valid_uuid(data.get("child_id", ""))
    assert is_valid_uuid(data.get("guardian_id", ""))
    assert data.get("kind") in {"MEDICAL", "PICKUP"}
    assert isinstance(data.get("scope_text"), str)
    assert is_iso8601_timestamp(data.get("effective_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))
    assert data.get("status") in {"ACTIVE", "EXPIRED", "REVOKED"}


# ---------------------------------------------------------------------------
# Session — PRD §3.3
# ---------------------------------------------------------------------------
def assert_session(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("title"), str) and data["title"]
    assert data.get("kind") in {"AFTERSCHOOL", "SUMMER_CAMP"}
    assert isinstance(data.get("age_min"), int)
    assert isinstance(data.get("age_max"), int)
    # PRD §3.3: "both values lie between 3 and 17 and age_min is at
    # most age_max".
    assert 3 <= data["age_min"] <= data["age_max"] <= 17
    assert isinstance(data.get("reference_date"), str)
    assert isinstance(data.get("weekly_capacity"), int)
    assert 1 <= data["weekly_capacity"] <= 200
    assert isinstance(data.get("week_start"), str)
    assert isinstance(data.get("week_count"), int)
    assert 1 <= data["week_count"] <= 12
    assert isinstance(data.get("base_weekly_fee_cents"), int)
    assert data["base_weekly_fee_cents"] >= 0
    assert isinstance(data.get("rainy_day_pool_per_week"), int)
    assert 0 <= data["rainy_day_pool_per_week"] <= data["weekly_capacity"]
    assert data.get("status") in {"DRAFT", "OPEN", "CLOSED", "CANCELLED"}


# ---------------------------------------------------------------------------
# Enrollment — PRD §3.4 / §3.5
# ---------------------------------------------------------------------------
def assert_enrollment(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("child_id", ""))
    assert is_valid_uuid(data.get("session_id", ""))
    assert isinstance(data.get("week_index"), int) and data["week_index"] >= 0
    assert data.get("status") in {
        "PENDING_AUTH", "CONFIRMED", "WAITLISTED", "CANCELLED", "COMPLETED",
    }
    # PRD §2.10: integer cents.
    for field in (
        "list_fee_cents", "sibling_discount_cents",
        "scholarship_discount_cents", "final_fee_cents",
    ):
        assert isinstance(data.get(field), int), (
            f"{field} must be an integer, got {data.get(field)!r}"
        )
        assert data[field] >= 0, (
            f"{field} must be >= 0, got {data[field]}"
        )
    # PRD §3.5: "final_fee_cents is set to the larger of zero and
    # list_fee_cents minus sibling_discount_cents minus
    # scholarship_discount_cents". Verified only when enrollment is
    # CONFIRMED or terminal-after-confirmed (COMPLETED) — pre-confirm
    # snapshots may be zero.
    if data["status"] in {"CONFIRMED", "COMPLETED"}:
        expected_final = max(
            0,
            data["list_fee_cents"]
            - data["sibling_discount_cents"]
            - data["scholarship_discount_cents"],
        )
        assert data["final_fee_cents"] == expected_final, (
            f"final_fee_cents ({data['final_fee_cents']}) must equal "
            f"max(0, list_fee_cents - sibling_discount_cents - "
            f"scholarship_discount_cents) = {expected_final}"
        )


# ---------------------------------------------------------------------------
# ScholarshipAward — PRD §3.6
# ---------------------------------------------------------------------------
def assert_scholarship_award(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("family_id", ""))
    assert isinstance(data.get("total_credit_cents"), int)
    # PRD §3.6: "total_credit_cents (at least 1)".
    assert data["total_credit_cents"] >= 1
    assert isinstance(data.get("consumed_credit_cents"), int)
    # Invariant: 0 <= consumed_credit_cents <= total_credit_cents.
    assert 0 <= data["consumed_credit_cents"] <= data["total_credit_cents"]
    assert data.get("granted_for_kind") in {
        "AFTERSCHOOL", "SUMMER_CAMP", "ANY",
    }
    assert data.get("status") in {"ACTIVE", "EXHAUSTED", "REVOKED"}


# ---------------------------------------------------------------------------
# SessionDay — PRD §3.8; PRD §2.4 lean entity (id + created_at only)
# ---------------------------------------------------------------------------
def assert_session_day(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: "Authorization and SessionDay carry only id and
    # created_at — both updated_at and version are absent on these
    # rows." So we do NOT assert updated_at/version.
    assert is_valid_uuid(data.get("session_id", ""))
    assert isinstance(data.get("week_index"), int) and data["week_index"] >= 0
    assert isinstance(data.get("day_date"), str)
    assert data.get("weather_status") in {"NORMAL", "RAINY", "CLOSED"}
    assert (
        isinstance(data.get("rainy_day_used"), int)
        and data["rainy_day_used"] >= 0
    )
    assert (
        isinstance(data.get("outdoor_headcount"), int)
        and data["outdoor_headcount"] >= 0
    )


# ---------------------------------------------------------------------------
# Version-bump invariant — PRD §2.4
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: version "starts at 1 on creation and increments by
    exactly 1 on every persisted mutation of that row, including
    mutations driven by side-effect cascades rather than direct PATCH
    calls."
    """
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Scholarship credit invariant — PRD §3.6
# ---------------------------------------------------------------------------
def assert_scholarship_balance_invariant(award: Dict[str, Any]) -> None:
    """PRD §3.6 + §3.5: consumed_credit_cents never exceeds
    total_credit_cents; status reflects whether the award is at the
    boundary (EXHAUSTED) or below it (ACTIVE / REVOKED).
    """
    assert (
        0 <= award["consumed_credit_cents"] <= award["total_credit_cents"]
    ), (
        f"award invariant: 0 <= consumed_credit_cents "
        f"({award['consumed_credit_cents']}) <= total_credit_cents "
        f"({award['total_credit_cents']}) must hold"
    )


__all__ = [
    "assert_family",
    "assert_guardian",
    "assert_child",
    "assert_emergency_contact",
    "assert_authorization",
    "assert_session",
    "assert_enrollment",
    "assert_scholarship_award",
    "assert_session_day",
    "assert_version_incremented_by_one",
    "assert_scholarship_balance_invariant",
]
