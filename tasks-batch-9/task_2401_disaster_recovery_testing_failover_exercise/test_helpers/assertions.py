"""Domain assertions layered on top of the framework validators."""

from datetime import datetime
from typing import Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import SCORE_TOLERANCE

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def _as_instant(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def assert_instant(actual, expected: str) -> None:
    """Compare two ISO 8601 UTC instants irrespective of fractional-second digits."""
    assert actual is not None, f"expected the instant {expected}, got None"
    assert _as_instant(actual) == _as_instant(expected), (
        f"expected the instant {expected}, got {actual}"
    )


def assert_common_fields(entity: dict, expected_version: Optional[int] = None) -> None:
    """Every entity but the replication log carries id, created_at, updated_at, version."""
    for field in COMMON_FIELDS:
        assert field in entity, f"missing common field {field}"
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"])
    assert is_iso8601_timestamp(entity["updated_at"])
    assert isinstance(entity["version"], int) and entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version


def assert_append_only_row(row: dict) -> None:
    """A replication observation carries only id and created_at, never updated_at/version."""
    assert is_valid_uuid(row["id"])
    assert is_iso8601_timestamp(row["created_at"])
    assert "updated_at" not in row, "append-only row must not carry updated_at"
    assert "version" not in row, "append-only row must not carry version"


def assert_score(actual, expected: float) -> None:
    """Two-decimal scores compare with a hundredth of tolerance."""
    assert actual == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"expected score {expected}, got {actual}"
    )


def assert_posture(group: dict, posture: str, posture_reason: str) -> None:
    assert group["posture"] == posture, f"posture was {group['posture']}"
    assert group["posture_reason"] == posture_reason, (
        f"posture_reason was {group['posture_reason']}"
    )


def assert_projection(group: dict, minutes: int, sequence: Optional[list] = None) -> None:
    assert group["projected_recovery_minutes"] == minutes
    if sequence is not None:
        assert group["recovery_sequence"] == sequence


def assert_runbook_state(
    runbook: dict,
    status: str,
    stale_reason: Optional[str] = None,
    readiness_score: Optional[float] = None,
) -> None:
    assert runbook["status"] == status, f"runbook status was {runbook['status']}"
    if stale_reason is not None:
        assert runbook["stale_reason"] == stale_reason
    if readiness_score is not None:
        assert_score(runbook["readiness_score"], readiness_score)


def assert_axes(
    exercise: dict,
    execution_state: Optional[str] = None,
    data_state: Optional[str] = None,
    failback_state: Optional[str] = None,
    closure_reason: Optional[str] = None,
) -> None:
    if execution_state is not None:
        assert exercise["execution_state"] == execution_state, (
            f"execution_state was {exercise['execution_state']}"
        )
    if data_state is not None:
        assert exercise["data_state"] == data_state
    if failback_state is not None:
        assert exercise["failback_state"] == failback_state
    if closure_reason is not None:
        assert exercise["closure_reason"] == closure_reason


def assert_impact_scores(
    exercise: dict,
    provisional: float,
    production: float,
    required_approval_level: str,
) -> None:
    assert_score(exercise["provisional_impact_score"], provisional)
    assert_score(exercise["production_impact_score"], production)
    assert exercise["required_approval_level"] == required_approval_level


def assert_objectives(exercise: dict, rto_minutes: int, rpo_minutes: int) -> None:
    assert exercise["rto_objective_minutes"] == rto_minutes
    assert exercise["rpo_objective_minutes"] == rpo_minutes


def assert_achieved(
    exercise: dict,
    achieved_rto_minutes: Optional[int] = None,
    achieved_rpo_minutes: Optional[int] = None,
    rto_met: Optional[bool] = None,
    rpo_met: Optional[bool] = None,
) -> None:
    if achieved_rto_minutes is not None:
        assert exercise["achieved_rto_minutes"] == achieved_rto_minutes
    if achieved_rpo_minutes is not None:
        assert exercise["achieved_rpo_minutes"] == achieved_rpo_minutes
    if rto_met is not None:
        assert exercise["rto_met"] is rto_met
    if rpo_met is not None:
        assert exercise["rpo_met"] is rpo_met


def assert_reserved_capacity(site: dict, reserved: int) -> None:
    assert site["reserved_capacity_units"] == reserved, (
        f"reserved_capacity_units was {site['reserved_capacity_units']}"
    )


def assert_finding_state(
    finding: dict,
    state: str,
    retest_failure_count: Optional[int] = None,
    escalated: Optional[bool] = None,
) -> None:
    assert finding["state"] == state, f"finding state was {finding['state']}"
    if retest_failure_count is not None:
        assert finding["retest_failure_count"] == retest_failure_count
    if escalated is not None:
        assert finding["escalated"] is escalated


def assert_step_validation(
    step: dict, validation_status: str, last_validated_at: Optional[str] = None
) -> None:
    assert step["validation_status"] == validation_status
    if last_validated_at is not None:
        assert_instant(step["last_validated_at"], last_validated_at)


def assert_pagination_meta(
    meta: dict, total_count: int, limit: int, offset: int, has_more: bool
) -> None:
    assert meta["total_count"] == total_count
    assert meta["limit"] == limit
    assert meta["offset"] == offset
    assert meta["has_more"] is has_more
