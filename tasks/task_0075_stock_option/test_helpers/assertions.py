"""Entity assertions and domain invariants for the Stock Option API.

Uses the framework's generic helpers (is_valid_uuid, is_iso8601_timestamp)
under the hood. Each asserter accepts the dict shape returned by the
respective endpoint and verifies all PRD-required fields.
"""
from __future__ import annotations
from typing import Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Mutable-entity common-fields (PRD §2.4): id, created_at, updated_at, version
# ---------------------------------------------------------------------------
def _assert_common_mutable(data: dict, entity_name: str) -> None:
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601, got "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be a positive int, got "
        f"{data.get('version')!r}"
    )


# Append-only (PRD §2.4): id and created_at only — no updated_at, no version.
def _assert_common_appendonly(data: dict, entity_name: str) -> None:
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# OptionPlan
# ---------------------------------------------------------------------------
def assert_option_plan(data: dict) -> None:
    """Validate OptionPlan envelope (PRD §3.1)."""
    _assert_common_mutable(data, "OptionPlan")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("pool_total_options"), int)
    assert data["pool_total_options"] >= 1
    assert isinstance(data.get("pool_reserved_options"), int)
    assert data["pool_reserved_options"] >= 0
    assert isinstance(data.get("pool_remaining_options"), int)
    assert data["pool_remaining_options"] >= 0
    # PRD §3.1: pool_remaining_options = pool_total_options - pool_reserved_options
    assert (
        data["pool_remaining_options"]
        == data["pool_total_options"] - data["pool_reserved_options"]
    ), (
        "pool_remaining_options must equal pool_total - pool_reserved"
    )
    assert data.get("jurisdiction_code") in {"US", "UK", "CN", "SG"}
    assert data.get("status") in {"DRAFT", "ACTIVE", "CLOSED"}


# ---------------------------------------------------------------------------
# GrantBatch
# ---------------------------------------------------------------------------
def assert_grant_batch(data: dict) -> None:
    """Validate GrantBatch envelope (PRD §3.2)."""
    _assert_common_mutable(data, "GrantBatch")
    assert is_valid_uuid(data.get("plan_id", ""))
    assert isinstance(data.get("batch_label"), str)
    assert isinstance(data.get("cliff_months"), int)
    assert data["cliff_months"] >= 0
    assert isinstance(data.get("vesting_total_months"), int)
    assert data["vesting_total_months"] >= 1
    assert data.get("vesting_period_months") in (1, 3, 12)
    assert data.get("vesting_algorithm") in {
        "ANNIVERSARY_BATCH", "CONTINUOUS_DAILY",
    }
    assert isinstance(data.get("performance_condition_required"), bool)
    assert data.get("status") in {
        "DRAFT", "OPEN_FOR_GRANTS", "LOCKED",
    }


# ---------------------------------------------------------------------------
# Grantee
# ---------------------------------------------------------------------------
def assert_grantee(data: dict) -> None:
    """Validate Grantee envelope (PRD §3.3)."""
    _assert_common_mutable(data, "Grantee")
    assert is_valid_uuid(data.get("plan_id", ""))
    assert isinstance(data.get("hr_employee_id"), str)
    assert len(data["hr_employee_id"]) > 0
    assert isinstance(data.get("full_name"), str)
    assert data.get("tax_residency") in {"US", "UK", "CN", "SG"}
    assert data.get("eligibility_status") in {
        "ELIGIBLE", "INELIGIBLE", "DEPARTED",
    }


# ---------------------------------------------------------------------------
# Grant
# ---------------------------------------------------------------------------
def assert_grant(data: dict) -> None:
    """Validate Grant envelope (PRD §3.4)."""
    _assert_common_mutable(data, "Grant")
    assert is_valid_uuid(data.get("plan_id", ""))
    assert is_valid_uuid(data.get("batch_id", ""))
    assert is_valid_uuid(data.get("grantee_id", ""))
    assert isinstance(data.get("quantity"), int)
    assert data["quantity"] >= 1
    assert isinstance(data.get("grant_date_fair_value_cents"), int)
    assert data["grant_date_fair_value_cents"] >= 1
    assert isinstance(data.get("vested_quantity"), int)
    assert data["vested_quantity"] >= 0
    assert isinstance(data.get("exercised_quantity"), int)
    assert data["exercised_quantity"] >= 0
    assert isinstance(data.get("forfeited_quantity"), int)
    assert data["forfeited_quantity"] >= 0
    # PRD §3.5: outstanding = quantity - exercised - forfeited.
    assert isinstance(data.get("outstanding_quantity"), int)
    assert (
        data["outstanding_quantity"]
        == data["quantity"]
        - data["exercised_quantity"]
        - data["forfeited_quantity"]
    ), "outstanding_quantity formula violated"
    assert data.get("status") in {
        "DRAFT", "BOARD_APPROVED", "SHAREHOLDER_APPROVED",
        "AGREEMENT_SIGNED", "LIVE", "FROZEN", "TERMINATED",
    }


# ---------------------------------------------------------------------------
# ExerciseWindow
# ---------------------------------------------------------------------------
def assert_exercise_window(data: dict) -> None:
    """Validate ExerciseWindow envelope (PRD §3.6)."""
    _assert_common_mutable(data, "ExerciseWindow")
    assert is_valid_uuid(data.get("plan_id", ""))
    assert isinstance(data.get("label"), str)
    assert is_iso8601_timestamp(data.get("open_ts", ""))
    assert is_iso8601_timestamp(data.get("close_ts", ""))
    assert data.get("status") in {
        "SCHEDULED", "OPEN", "CLOSED", "ARCHIVED",
    }


# ---------------------------------------------------------------------------
# ExerciseApplication
# ---------------------------------------------------------------------------
def assert_exercise_application(data: dict) -> None:
    """Validate ExerciseApplication envelope (PRD §3.8)."""
    _assert_common_mutable(data, "ExerciseApplication")
    assert is_valid_uuid(data.get("plan_id", ""))
    assert is_valid_uuid(data.get("grant_id", ""))
    assert is_valid_uuid(data.get("window_id", ""))
    assert is_valid_uuid(data.get("pinned_price_version_id", ""))
    assert isinstance(data.get("requested_quantity"), int)
    assert data["requested_quantity"] >= 1
    assert data.get("settlement_mode") in {
        "SHARE_ISSUANCE", "CASH_SETTLEMENT",
    }
    assert data.get("status") in {
        "SUBMITTED", "ELIGIBILITY_VERIFIED", "PAYMENT_RECEIVED",
        "TAX_WITHHELD", "SETTLED", "REJECTED", "CANCELLED",
    }


# ---------------------------------------------------------------------------
# DepartureRecord
# ---------------------------------------------------------------------------
def assert_departure_record(data: dict) -> None:
    """Validate DepartureRecord envelope (PRD §3.10)."""
    _assert_common_mutable(data, "DepartureRecord")
    assert is_valid_uuid(data.get("grantee_id", ""))
    assert data.get("departure_type") in {
        "RESIGNATION", "TERMINATION", "RETIREMENT", "DEATH",
    }
    if data.get("leaver_class") is not None:
        assert data["leaver_class"] in {"GOOD_LEAVER", "BAD_LEAVER"}
    assert is_iso8601_timestamp(data.get("departed_ts", ""))
    assert data.get("status") in {"DRAFT", "SETTLED"}


# ---------------------------------------------------------------------------
# Append-only entities
# ---------------------------------------------------------------------------
def assert_corporate_event(data: dict) -> None:
    """Validate CorporateEvent envelope (PRD §3.6 / §3.7).

    Append-only: only id and created_at common fields.
    """
    _assert_common_appendonly(data, "CorporateEvent")
    # PRD §2.4: append-only entities do NOT carry updated_at or version.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "CorporateEvent must not expose updated_at (append-only per PRD §2.4)"
    )
    assert "version" not in data or data.get("version") is None, (
        "CorporateEvent must not expose version (append-only per PRD §2.4)"
    )
    assert is_valid_uuid(data.get("plan_id", ""))
    assert data.get("event_type") in {
        "EARNINGS_BLACKOUT", "MATERIAL_EVENT_BLACKOUT",
        "STOCK_SPLIT", "CASH_DIVIDEND", "RESTRUCTURING",
        "CHANGE_OF_CONTROL", "IPO",
    }
    assert is_iso8601_timestamp(data.get("effective_ts", ""))


def assert_exercise_price_version(data: dict) -> None:
    """Validate ExercisePriceVersion envelope (PRD §3.2 / §3.7)."""
    _assert_common_appendonly(data, "ExercisePriceVersion")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert is_valid_uuid(data.get("batch_id", ""))
    assert isinstance(data.get("version_index"), int)
    assert data["version_index"] >= 1
    assert data.get("cause") in {
        "INITIAL", "STOCK_SPLIT", "CASH_DIVIDEND", "RESTRUCTURING",
    }
    assert isinstance(data.get("price_per_option_cents"), int)
    assert data["price_per_option_cents"] >= 1
    assert is_iso8601_timestamp(data.get("effective_from_ts", ""))


def assert_vesting_record(data: dict) -> None:
    """Validate VestingRecord envelope (PRD §3.5)."""
    _assert_common_appendonly(data, "VestingRecord")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert is_valid_uuid(data.get("grant_id", ""))
    assert isinstance(data.get("tranche_index"), int)
    assert data["tranche_index"] >= 1
    assert isinstance(data.get("tranche_quantity"), int)
    assert data.get("cause") in {
        "CLIFF", "PERIODIC", "PERFORMANCE_ATTEST",
        "ACCELERATION_CHANGE_OF_CONTROL", "ACCELERATION_IPO",
    }
    assert isinstance(data.get("archived"), bool)


def assert_tax_event_record(data: dict) -> None:
    """Validate TaxEventRecord envelope (PRD §3.9)."""
    _assert_common_appendonly(data, "TaxEventRecord")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert is_valid_uuid(data.get("grant_id", ""))
    assert data.get("event_type") in {"GRANT", "VEST", "EXERCISE", "SALE"}
    assert isinstance(data.get("taxable_amount_cents"), int)
    assert isinstance(data.get("withheld_amount_cents"), int)
    assert isinstance(data.get("deferred"), bool)
    assert data.get("jurisdiction_code") in {"US", "UK", "CN", "SG"}


def assert_audit_log_entry(data: dict) -> None:
    """Validate AuditLogEntry envelope (PRD §3.11)."""
    _assert_common_appendonly(data, "AuditLogEntry")
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("actor_role"), str)
    assert data.get("action_code") in {
        "GRANT_CREATED", "GRANT_BOARD_APPROVED",
        "GRANT_SHAREHOLDER_APPROVED", "GRANT_AGREEMENT_SIGNED",
        "GRANT_TERMINATED", "EXERCISE_SUBMITTED", "EXERCISE_SETTLED",
        "EXERCISE_REJECTED", "PRICE_VERSION_CREATED",
        "DEPARTURE_SETTLED",
    }


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_plan_pool_invariants(plan: dict) -> None:
    """PRD §3.1 / §3.4: pool_reserved + pool_remaining == pool_total
    and pool_reserved >= 0."""
    assert plan["pool_reserved_options"] >= 0
    assert plan["pool_remaining_options"] >= 0
    assert (
        plan["pool_remaining_options"]
        == plan["pool_total_options"] - plan["pool_reserved_options"]
    )


def assert_grant_quantity_invariants(grant: dict) -> None:
    """PRD §3.5: outstanding = quantity - exercised - forfeited;
    each component must be non-negative."""
    assert grant["quantity"] >= 0
    assert grant["exercised_quantity"] >= 0
    assert grant["forfeited_quantity"] >= 0
    assert grant["vested_quantity"] >= 0
    assert grant["vested_quantity"] <= grant["quantity"]
    assert (
        grant["outstanding_quantity"]
        == grant["quantity"]
        - grant["exercised_quantity"]
        - grant["forfeited_quantity"]
    )


__all__ = [
    "assert_option_plan",
    "assert_grant_batch",
    "assert_grantee",
    "assert_grant",
    "assert_exercise_window",
    "assert_exercise_application",
    "assert_departure_record",
    "assert_corporate_event",
    "assert_exercise_price_version",
    "assert_vesting_record",
    "assert_tax_event_record",
    "assert_audit_log_entry",
    "assert_plan_pool_invariants",
    "assert_grant_quantity_invariants",
]
