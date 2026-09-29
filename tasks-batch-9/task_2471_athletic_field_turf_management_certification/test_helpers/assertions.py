"""Per-entity shape assertions and domain invariant checkers."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_valid_uuid,
)

from .constants import DAYS_PER_YEAR

# ---------------------------------------------------------------------------
# Instant handling
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a trailing `Z` and any
    number of fractional digits."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """Compare two ISO 8601 UTC instants by value rather than by spelling.

    Timestamps are emitted with three fractional digits, so a literal string
    comparison against `2026-08-03T00:00:00Z` would fail on formatting alone.
    """
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def shift_instant(instant: str, **delta: float) -> str:
    """Return `instant` moved by the given `timedelta` keyword arguments."""
    moved = parse_instant(instant) + timedelta(**delta)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_between(start: str, end: str) -> float:
    """Fractional hours from `start` to `end`."""
    return (parse_instant(end) - parse_instant(start)).total_seconds() / 3600.0


def expected_age_years(installed_on_date: str, current_utc: str) -> float:
    """Whole and fractional days between installation and now, over 365.25."""
    installed = parse_instant(
        installed_on_date if "T" in installed_on_date else f"{installed_on_date}T00:00:00Z"
    )
    days = (parse_instant(current_utc) - installed).total_seconds() / 86400.0
    return round(days / DAYS_PER_YEAR + 1e-9, 2)


# ---------------------------------------------------------------------------
# Common properties
# ---------------------------------------------------------------------------

_VERSIONED_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(resource: Dict[str, Any], entity_label: str) -> None:
    """Nine of the ten resource kinds carry `created_at`, `updated_at` and `version`."""
    for key in _VERSIONED_COMMON_FIELDS:
        assert key in resource, f"{entity_label} is missing `{key}`"
    assert is_valid_uuid(resource["id"]), f"{entity_label}.id is not a UUID: {resource['id']!r}"
    assert_timestamp_format(resource["created_at"])
    assert_timestamp_format(resource["updated_at"])
    assert isinstance(resource["version"], int), f"{entity_label}.version must be an integer"
    assert resource["version"] >= 1, f"{entity_label}.version must start at 1"


def assert_version(resource: Dict[str, Any], expected: int, entity_label: str = "resource") -> None:
    """Assert an exact `version`, which increases by exactly 1 per mutation."""
    assert resource.get("version") == expected, (
        f"{entity_label}.version expected {expected}, got {resource.get('version')}"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_field(field: Dict[str, Any]) -> Dict[str, Any]:
    """Assert the shape of a `Field` representation."""
    assert_common_fields(field, "Field")
    for key in (
        "name",
        "surface_type",
        "installed_on_date",
        "expected_life_years",
        "area_sq_ft",
        "sanctioned_level",
        "age_years",
        "warranty_status",
        "play_status",
        "certification_status",
        "admin_closure_active",
        "open_mandatory_remediation_count",
        "open_advisory_remediation_count",
        "open_certification_packet_count",
        "open_replacement_plan_count",
        "unsafe_cancellation_count",
        "cumulative_wear_units",
        "usage_hours_ytd",
        "rest_debt_hours",
        "nitrogen_applied_ytd_lb_per_1000_sq_ft",
        "condition_index_agronomic",
    ):
        assert key in field, f"Field is missing `{key}`"
    assert field["surface_type"] in ("NATURAL_GRASS", "SYNTHETIC_TURF")
    assert field["warranty_status"] in ("NONE", "ACTIVE", "EXPIRED")
    assert field["play_status"] in (
        "OPEN",
        "RESTRICTED",
        "CLOSED_ADMIN",
        "CLOSED_UNSAFE",
        "RETIRED",
    )
    assert field["certification_status"] in (
        "NOT_CERTIFIED",
        "PENDING_REVIEW",
        "CERTIFIED",
        "EXPIRED",
    )
    if field["surface_type"] == "NATURAL_GRASS":
        assert field.get("infill_depth_mm") is None, (
            "a natural grass field carries no `infill_depth_mm`"
        )
    return field


def assert_staff_member(staff: Dict[str, Any]) -> Dict[str, Any]:
    """Assert the shape of a `StaffMember` representation."""
    assert_common_fields(staff, "StaffMember")
    assert "full_name" in staff and isinstance(staff["full_name"], str)
    assert isinstance(staff.get("roles"), list) and staff["roles"], (
        "StaffMember.roles must be a non-empty array"
    )
    assert staff.get("employment_status") in ("ACTIVE", "INACTIVE")
    return staff


def assert_maintenance_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """Assert the shape of a `MaintenanceTask` representation."""
    assert_common_fields(task, "MaintenanceTask")
    for key in (
        "field_id",
        "assigned_staff_member_id",
        "task_type",
        "surface_class",
        "scheduled_start_utc",
        "scheduled_end_utc",
        "planned_for_certification_window",
        "recovery_credit_hours",
        "status",
    ):
        assert key in task, f"MaintenanceTask is missing `{key}`"
    assert task["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert task["surface_class"] in ("NATURAL_GRASS", "SYNTHETIC_TURF")
    return task


def assert_safety_assessment(assessment: Dict[str, Any]) -> Dict[str, Any]:
    """Assert the shape of a `SafetyAssessment` representation."""
    assert_common_fields(assessment, "SafetyAssessment")
    for key in (
        "field_id",
        "inspector_staff_member_id",
        "assessment_type",
        "assessed_at_utc",
        "result",
        "status",
    ):
        assert key in assessment, f"SafetyAssessment is missing `{key}`"
    assert assessment["assessment_type"] in (
        "IMPACT_ATTENUATION",
        "GOAL_ANCHORING",
        "STRIPING_LAYOUT",
    )
    assert assessment["status"] in ("RECORDED", "SUPERSEDED", "VOIDED")
    assert assessment["result"] in ("PASS", "ADVISORY", "FAIL")
    if assessment["assessment_type"] == "IMPACT_ATTENUATION":
        assert assessment.get("declared_result") is None, (
            "an impact test carries no `declared_result`"
        )
    else:
        assert assessment.get("gmax_mean_value") is None, (
            "a non-instrumented inspection carries no `gmax_mean_value`"
        )
        assert assessment["result"] in ("PASS", "FAIL"), (
            "a non-instrumented inspection is never ADVISORY"
        )
    return assessment


def assert_remediation_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """Assert the shape of a `RemediationOrder` representation."""
    assert_common_fields(order, "RemediationOrder")
    for key in (
        "field_id",
        "source_assessment_id",
        "severity",
        "status",
        "opened_at_utc",
        "rejection_count",
    ):
        assert key in order, f"RemediationOrder is missing `{key}`"
    assert order["severity"] in ("MANDATORY", "ADVISORY")
    assert order["status"] in (
        "OPEN",
        "VERIFICATION_SUBMITTED",
        "CLOSED_VERIFIED",
        "CANCELLED",
    )
    return order


def assert_usage_booking(booking: Dict[str, Any]) -> Dict[str, Any]:
    """Assert the shape of a `UsageBooking` representation."""
    assert_common_fields(booking, "UsageBooking")
    for key in (
        "field_id",
        "requested_by_staff_member_id",
        "activity_type",
        "window_start_utc",
        "window_end_utc",
        "expected_participant_count",
        "status",
    ):
        assert key in booking, f"UsageBooking is missing `{key}`"
    assert booking["activity_type"] in ("PRACTICE", "GAME", "TOURNAMENT", "COMMUNITY")
    assert booking["status"] in (
        "SCHEDULED",
        "CONFIRMED",
        "PLAYED",
        "RAINED_OUT",
        "CANCELLED_LATE",
        "CANCELLED_UNSAFE",
    )
    return booking


def assert_usage_ledger_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """A ledger entry is immutable: it carries only `id` and `created_at`."""
    assert "id" in entry and is_valid_uuid(entry["id"]), "UsageLedgerEntry.id is not a UUID"
    assert "created_at" in entry, "UsageLedgerEntry is missing `created_at`"
    assert_timestamp_format(entry["created_at"])
    assert "updated_at" not in entry, "a ledger entry has no `updated_at`"
    assert "version" not in entry, "a ledger entry has no `version`"
    for key in (
        "field_id",
        "entry_type",
        "wear_units_delta",
        "running_balance_after",
        "effective_at_utc",
        "note",
    ):
        assert key in entry, f"UsageLedgerEntry is missing `{key}`"
    assert entry["entry_type"] in (
        "PLAY_WEAR",
        "LATE_CANCEL_WEAR",
        "RAIN_OUT_RELIEF",
        "RECOVERY_CREDIT",
        "UNSAFE_CANCELLATION",
    )
    return entry


def assert_certification_packet(packet: Dict[str, Any]) -> Dict[str, Any]:
    """Assert the shape of a `CertificationPacket` representation."""
    assert_common_fields(packet, "CertificationPacket")
    for key in (
        "field_id",
        "governing_assessment_id",
        "competition_season_label",
        "status",
        "return_count",
    ):
        assert key in packet, f"CertificationPacket is missing `{key}`"
    assert packet["status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "RETURNED",
        "SUPERSEDED",
    )
    return packet


def assert_capital_budget(budget: Dict[str, Any]) -> Dict[str, Any]:
    """Assert the shape of a `CapitalBudget` representation."""
    assert_common_fields(budget, "CapitalBudget")
    for key in (
        "fiscal_year",
        "total_authorized_amount_cents",
        "committed_amount_cents",
        "available_amount_cents",
        "lock_threshold_amount_cents",
        "status",
    ):
        assert key in budget, f"CapitalBudget is missing `{key}`"
    assert budget["status"] in ("OPEN", "LOCKED")
    for key in (
        "total_authorized_amount_cents",
        "committed_amount_cents",
        "available_amount_cents",
        "lock_threshold_amount_cents",
    ):
        assert isinstance(budget[key], int), f"CapitalBudget.{key} must be integer cents"
    return budget


def assert_replacement_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Assert the shape of a `ReplacementPlan` representation."""
    assert_common_fields(plan, "ReplacementPlan")
    for key in (
        "field_id",
        "capital_budget_id",
        "target_surface_type",
        "area_sq_ft",
        "priority_basis",
        "planned_install_year",
        "base_construction_cents",
        "disposal_cents",
        "pre_contingency_subtotal_cents",
        "contingency_rate",
        "contingency_cents",
        "plan_funding_amount_cents",
        "replacement_priority_score",
        "funding_status",
        "disposal_status",
    ):
        assert key in plan, f"ReplacementPlan is missing `{key}`"
    assert plan["funding_status"] in (
        "DRAFT",
        "SUBMITTED",
        "APPROVED",
        "DEFERRED",
        "REJECTED",
        "RESCINDED",
    )
    assert plan["disposal_status"] in (
        "NOT_APPLICABLE",
        "PENDING",
        "MANIFESTED",
        "COMPLETED",
    )
    return plan


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def assert_two_decimals(value: Any, expected: float, label: str) -> None:
    """Compare a two-decimal derived quantity."""
    assert value is not None, f"{label}: expected {expected}, got null"
    assert value == pytest.approx(expected, abs=0.01), (
        f"{label}: expected {expected}, got {value}"
    )


def assert_one_decimal(value: Any, expected: float, label: str) -> None:
    """Compare a one-decimal measurement such as `gmax_mean_value`."""
    assert value is not None, f"{label}: expected {expected}, got null"
    assert value == pytest.approx(expected, abs=0.05), (
        f"{label}: expected {expected}, got {value}"
    )


def assert_play_posture(field: Dict[str, Any], expected: str) -> None:
    """Assert the derived play posture, quoting the counters that drive it."""
    assert field.get("play_status") == expected, (
        f"play_status expected {expected}, got {field.get('play_status')} "
        f"(retired_at={field.get('retired_at')}, "
        f"mandatory={field.get('open_mandatory_remediation_count')}, "
        f"admin_closure_active={field.get('admin_closure_active')}, "
        f"rest_debt_hours={field.get('rest_debt_hours')}, "
        f"advisory={field.get('open_advisory_remediation_count')})"
    )


def assert_certification_posture(field: Dict[str, Any], expected: str) -> None:
    """Assert the derived certification posture."""
    assert field.get("certification_status") == expected, (
        f"certification_status expected {expected}, "
        f"got {field.get('certification_status')} "
        f"(certified_until_utc={field.get('certified_until_utc')})"
    )


def assert_wear_ledger_conserved(field: Dict[str, Any], entries: List[Dict[str, Any]]) -> None:
    """`cumulative_wear_units` equals the sum of `wear_units_delta` over the
    field's entries, with no status filter of any kind."""
    mine = [e for e in entries if e.get("field_id") == field["id"]]
    total = round(sum(float(e["wear_units_delta"]) for e in mine) + 1e-9, 2)
    assert_two_decimals(
        field.get("cumulative_wear_units"), total, "Field.cumulative_wear_units"
    )


def assert_running_balance_replays(entries: List[Dict[str, Any]]) -> None:
    """Replaying a field's ledger in `effective_at_utc` then `created_at` order
    must reproduce the `running_balance_after` column exactly."""
    ordered = sorted(
        entries, key=lambda e: (parse_instant(e["effective_at_utc"]), parse_instant(e["created_at"]))
    )
    balance = 0.0
    for entry in ordered:
        balance = round(balance + float(entry["wear_units_delta"]) + 1e-9, 2)
        assert_two_decimals(
            entry.get("running_balance_after"),
            balance,
            f"running_balance_after on the {entry.get('entry_type')} entry",
        )


def assert_capital_conserved(budget: Dict[str, Any]) -> None:
    """`available_amount_cents` plus `committed_amount_cents` must always equal
    `total_authorized_amount_cents`."""
    assert (
        budget["available_amount_cents"] + budget["committed_amount_cents"]
        == budget["total_authorized_amount_cents"]
    ), (
        f"capital not conserved: available={budget['available_amount_cents']} "
        f"+ committed={budget['committed_amount_cents']} "
        f"!= total={budget['total_authorized_amount_cents']}"
    )


def assert_committed_matches_approved_plans(
    budget: Dict[str, Any], plans: List[Dict[str, Any]]
) -> None:
    """`committed_amount_cents` equals the sum of `plan_funding_amount_cents`
    over the budget's `APPROVED` plans; every other funding status contributes
    nothing."""
    approved = [
        p
        for p in plans
        if p.get("capital_budget_id") == budget["id"] and p.get("funding_status") == "APPROVED"
    ]
    expected = sum(int(p["plan_funding_amount_cents"]) for p in approved)
    assert budget["committed_amount_cents"] == expected, (
        f"committed_amount_cents expected {expected} from "
        f"{len(approved)} approved plan(s), got {budget['committed_amount_cents']}"
    )


def assert_budget_lock_consistent(budget: Dict[str, Any]) -> None:
    """The lock comparison is inclusive: at or above the threshold is LOCKED."""
    expected = (
        "LOCKED"
        if budget["committed_amount_cents"] >= budget["lock_threshold_amount_cents"]
        else "OPEN"
    )
    assert budget["status"] == expected, (
        f"budget status expected {expected} for committed="
        f"{budget['committed_amount_cents']} against threshold="
        f"{budget['lock_threshold_amount_cents']}, got {budget['status']}"
    )
