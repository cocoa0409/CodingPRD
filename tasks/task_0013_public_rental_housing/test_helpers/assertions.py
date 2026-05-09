"""Per-entity assertions and domain invariant checkers for the Public Rental Housing API.

Each `assert_<entity>` validates the structure of a single entity payload against the
PRD contract: id is a 36-char UUID (PRD §2.4); created_at is ISO 8601 UTC with three
fractional digits; status is one of the PRD enumeration values; numeric fields are
non-negative where the PRD requires it.

Append-only entities (SyncEvent — PRD §2.4) are checked WITHOUT updated_at/version
because the PRD explicitly states those fields are absent on append-only resources.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _check_common_fields(data: Dict[str, Any], *, append_only: bool = False) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    if append_only:
        # PRD §2.4: append-only entities carry only id and created_at.
        return
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version must start at 1 and increment"


# ──────────────────────────────────────────────────────────
# HousingProgram
# ──────────────────────────────────────────────────────────


def assert_program(data: Dict[str, Any]) -> None:
    _check_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"], "name must be non-empty string"
    assert isinstance(data.get("current_period_index"), int)
    assert data["current_period_index"] >= 0
    assert isinstance(data.get("notice_period_length"), int) and data["notice_period_length"] >= 1
    assert isinstance(data.get("grace_period_length"), int) and data["grace_period_length"] >= 1
    assert isinstance(data.get("per_capita_income_threshold_cents"), int)
    assert isinstance(data.get("per_capita_asset_threshold_cents"), int)


# ──────────────────────────────────────────────────────────
# Application
# ──────────────────────────────────────────────────────────


_APP_STATUSES = {
    "DRAFT",
    "UNDER_REVIEW",
    "SCORED",
    "QUEUED",
    "ALLOCATED",
    "OCCUPIED",
    "EXIT_PENDING",
    "EXITED",
    "REJECTED",
}


def assert_application(data: Dict[str, Any]) -> None:
    _check_common_fields(data)
    assert data["status"] in _APP_STATUSES, f"unexpected Application.status {data['status']!r}"
    assert isinstance(data.get("housing_program_id"), str)
    assert isinstance(data.get("applicant_user_id"), str)
    assert isinstance(data.get("household_members"), list)
    assert isinstance(data.get("family_size"), int) and data["family_size"] >= 1
    assert data["family_size"] == len(data["household_members"]), (
        "PRD §3.2: family_size is computed as the length of household_members"
    )
    assert isinstance(data.get("requires_accessibility"), bool)
    assert data["household_type"] in {"LOW_INCOME", "NEW_CITIZEN", "RELOCATION", "TALENT"}
    assert isinstance(data.get("declared_monthly_income_cents"), int)
    assert isinstance(data.get("declared_total_assets_cents"), int)
    assert isinstance(data.get("residence_start_period"), int)


# ──────────────────────────────────────────────────────────
# HousingUnit
# ──────────────────────────────────────────────────────────


_APARTMENT_TO_BEDROOMS = {
    "STUDIO": 0,
    "ONE_BEDROOM": 1,
    "TWO_BEDROOM": 2,
    "THREE_BEDROOM": 3,
}

_UNIT_STATUSES = {"AVAILABLE", "RESERVED", "OCCUPIED", "RETIRED"}


def assert_housing_unit(data: Dict[str, Any]) -> None:
    _check_common_fields(data)
    assert data["status"] in _UNIT_STATUSES
    assert data["apartment_type"] in _APARTMENT_TO_BEDROOMS
    assert data["bedroom_count"] == _APARTMENT_TO_BEDROOMS[data["apartment_type"]], (
        "PRD §3.1: bedroom_count must match apartment_type"
    )
    assert isinstance(data["square_meters"], int) and data["square_meters"] >= 1
    assert isinstance(data["monthly_base_rent_cents"], int) and data["monthly_base_rent_cents"] >= 0
    assert 1 <= data["location_priority_tier"] <= 5
    assert isinstance(data["accessibility_compliant"], bool)


# ──────────────────────────────────────────────────────────
# Allocation
# ──────────────────────────────────────────────────────────


_ALLOC_STATUSES = {"PUBLISHED", "UNDER_OBJECTION", "CONFIRMED", "REVERTED"}


def assert_allocation(data: Dict[str, Any]) -> None:
    _check_common_fields(data)
    assert data["status"] in _ALLOC_STATUSES
    assert isinstance(data["application_id"], str)
    assert isinstance(data["housing_unit_id"], str)
    assert isinstance(data["notice_start_period"], int)
    assert isinstance(data["notice_end_period"], int)
    # PRD §3.4: notice_end_period = notice_start_period + program.notice_period_length.
    assert data["notice_end_period"] > data["notice_start_period"]


# ──────────────────────────────────────────────────────────
# Objection
# ──────────────────────────────────────────────────────────


_OBJ_STATUSES = {"PENDING_REVIEW", "SUSTAINED", "DISMISSED"}


def assert_objection(data: Dict[str, Any]) -> None:
    _check_common_fields(data)
    assert data["status"] in _OBJ_STATUSES
    assert isinstance(data["allocation_id"], str)
    assert isinstance(data["submitter_user_id"], str)
    assert isinstance(data["reason_text"], str) and len(data["reason_text"]) >= 20


# ──────────────────────────────────────────────────────────
# Contract
# ──────────────────────────────────────────────────────────


_CONTRACT_STATUSES = {"DRAFT", "DEPOSIT_PAID", "SIGNED", "ACTIVE", "TERMINATED"}


def assert_contract(data: Dict[str, Any]) -> None:
    _check_common_fields(data)
    assert data["status"] in _CONTRACT_STATUSES
    assert isinstance(data["allocation_id"], str)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["housing_unit_id"], str)
    assert isinstance(data["deposit_amount_cents"], int) and data["deposit_amount_cents"] >= 0
    assert isinstance(data["deposit_paid"], bool)
    assert isinstance(data["handover_recorded"], bool)


# ──────────────────────────────────────────────────────────
# RentReduction
# ──────────────────────────────────────────────────────────


_RR_STATUSES = {
    "SUBMITTED",
    "PRIMARY_REVIEW",
    "SECONDARY_REVIEW",
    "FINAL_APPROVED",
    "REJECTED",
    "EXPIRED",
}


def assert_rent_reduction(data: Dict[str, Any]) -> None:
    _check_common_fields(data)
    assert data["status"] in _RR_STATUSES
    assert isinstance(data["contract_id"], str)
    assert data["hardship_category"] in {
        "MAJOR_ILLNESS",
        "UNEMPLOYMENT",
        "DISABILITY",
        "ELDER_CARE",
    }
    assert isinstance(data["declared_hardship_income_cents"], int)
    assert isinstance(data["supporting_documents"], list)
    assert isinstance(data["provisional_discount_bps"], int)
    assert 0 <= data["provisional_discount_bps"] <= 10000
    if data.get("final_discount_bps") is not None:
        assert 0 <= data["final_discount_bps"] <= 10000


# ──────────────────────────────────────────────────────────
# AnnualReview
# ──────────────────────────────────────────────────────────


_AR_STATUSES = {"OPEN", "FINALIZED"}


def assert_annual_review(data: Dict[str, Any]) -> None:
    _check_common_fields(data)
    assert data["status"] in _AR_STATUSES
    assert isinstance(data["application_id"], str)
    assert isinstance(data["review_period_index"], int)
    assert data["review_period_index"] >= 0
    assert isinstance(data["exit_triggered"], bool)
    if data.get("re_eligibility") is not None:
        assert data["re_eligibility"] in {"ELIGIBLE", "INELIGIBLE"}


# ──────────────────────────────────────────────────────────
# SyncEvent (append-only — only id + created_at per PRD §2.4)
# ──────────────────────────────────────────────────────────


_SYNC_EVENT_TYPES = {
    "CIVIL_AFFAIRS_HOUSEHOLD",
    "PUBLIC_SECURITY_IDENTITY",
    "TAX_INCOME_ASSETS",
    "SOCIAL_SECURITY_INCOME",
    "PAYMENT_DEPOSIT",
    "PAYMENT_RENT",
    "AUDIT_ELIGIBILITY_CHANGE",
    "AUDIT_ALLOCATION_DECISION",
}


def assert_sync_event(data: Dict[str, Any]) -> None:
    _check_common_fields(data, append_only=True)
    # PRD §2.4: SyncEvent carries only id and created_at — updated_at and version absent.
    assert "updated_at" not in data, (
        "SyncEvent is append-only (PRD §2.4); updated_at must not be present"
    )
    assert "version" not in data, (
        "SyncEvent is append-only (PRD §2.4); version must not be present"
    )
    assert data["event_type"] in _SYNC_EVENT_TYPES
    assert data["subject_type"] in {"APPLICATION", "ALLOCATION", "CONTRACT", "RENT_REDUCTION"}
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["payload"], dict)
    assert isinstance(data["emitted_period"], int)


# ──────────────────────────────────────────────────────────
# Round half-up (PRD §2.7) — exposed so tests can compute expected values.
# ──────────────────────────────────────────────────────────


def round_half_up(value: float) -> int:
    """PRD §2.7: round half up to the nearest cent — fractional part of exactly 0.5
    rounds away from zero (toward the larger cent). This matches Python's decimal
    ROUND_HALF_UP, NOT the built-in `round` (which uses banker's rounding).
    """
    if value >= 0:
        return int(value + 0.5)
    return -int(-value + 0.5)


# ──────────────────────────────────────────────────────────
# Domain invariant checkers
# ──────────────────────────────────────────────────────────


def assert_application_score_components(application: Dict[str, Any]) -> None:
    """When status >= SCORED, queue_score must be a non-negative integer per PRD §3.3."""
    if application.get("status") in {"DRAFT", "UNDER_REVIEW"}:
        assert (
            application.get("queue_score") is None
        ), "PRD §3.3: queue_score is null while application is in DRAFT or UNDER_REVIEW"
    else:
        assert isinstance(
            application.get("queue_score"), int
        ), "PRD §3.3: queue_score must be a non-negative integer"
        assert application["queue_score"] >= 0
