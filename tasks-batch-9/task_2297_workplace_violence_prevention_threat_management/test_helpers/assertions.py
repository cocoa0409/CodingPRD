"""Domain assertions expressed in the language of the requirements."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .constants import (
    MONEY_TOLERANCE,
    PENALTY_BAND_ADEQUATE_MIN,
    PENALTY_BAND_STRONG_MIN,
    READY_THRESHOLD_OPEN,
    READY_THRESHOLD_RESTRICTED,
    REQUIRED_LOG_ELEMENT_COUNT,
)

# --------------------------------------------------------------------------
# Numeric helpers
# --------------------------------------------------------------------------


def assert_two_decimal_value(actual: Any, expected: float, label: str = "value") -> None:
    """A derived numeric rounded half-up to two decimal places."""
    assert actual is not None, f"{label} must not be null"
    assert actual == pytest.approx(expected, abs=MONEY_TOLERANCE), (
        f"{label} should be {expected}, got {actual}"
    )


def assert_integer_points(actual: Any, expected: int, label: str = "points") -> None:
    """Severity points are integers compared exactly."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer, got {actual!r}"
    )
    assert actual == expected, f"{label} should be {expected}, got {actual}"


# --------------------------------------------------------------------------
# Common resource properties
# --------------------------------------------------------------------------


def assert_common_fields(row: Dict[str, Any], expected_version: Optional[int] = None) -> None:
    """A resource carrying id, created_at, updated_at and version."""
    assert is_valid_uuid(row["id"]), f"id must be a UUID string, got {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), f"bad created_at {row['created_at']!r}"
    assert is_iso8601_timestamp(row["updated_at"]), f"bad updated_at {row['updated_at']!r}"
    assert isinstance(row["version"], int), "version must be an integer"
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"version should be {expected_version}, got {row['version']}"
        )


def assert_log_entry_has_no_version_block(entry: Dict[str, Any]) -> None:
    """A violent incident log entry carries id and created_at only."""
    assert is_valid_uuid(entry["id"]), f"id must be a UUID string, got {entry['id']!r}"
    assert is_iso8601_timestamp(entry["created_at"]), f"bad created_at {entry['created_at']!r}"
    assert "updated_at" not in entry, "a log entry must not carry updated_at"
    assert "version" not in entry, "a log entry must not carry version"


# --------------------------------------------------------------------------
# Prevention plan
# --------------------------------------------------------------------------


def assert_plan_state(
    plan: Dict[str, Any],
    status: Optional[str] = None,
    compliance_posture: Optional[str] = None,
    inspection_ready: Optional[bool] = None,
) -> None:
    if status is not None:
        assert plan["status"] == status, f"plan status should be {status}, got {plan['status']}"
    if compliance_posture is not None:
        assert plan["compliance_posture"] == compliance_posture, (
            f"compliance_posture should be {compliance_posture}, got {plan['compliance_posture']}"
        )
    if inspection_ready is not None:
        assert plan["inspection_ready"] is inspection_ready, (
            f"inspection_ready should be {inspection_ready}, got {plan['inspection_ready']}"
        )


def assert_plan_metrics(
    plan: Dict[str, Any],
    hazard_coverage_pct: Optional[float] = None,
    training_compliance_pct: Optional[float] = None,
    log_completeness_pct: Optional[float] = None,
    drills_completed_12mo: Optional[int] = None,
    unmitigated_hazard_count: Optional[int] = None,
    overdue_action_count: Optional[int] = None,
) -> None:
    if hazard_coverage_pct is not None:
        assert_two_decimal_value(plan["hazard_coverage_pct"], hazard_coverage_pct, "hazard_coverage_pct")
    if training_compliance_pct is not None:
        assert_two_decimal_value(
            plan["training_compliance_pct"], training_compliance_pct, "training_compliance_pct"
        )
    if log_completeness_pct is not None:
        assert_two_decimal_value(
            plan["log_completeness_pct"], log_completeness_pct, "log_completeness_pct"
        )
    if drills_completed_12mo is not None:
        assert plan["drills_completed_12mo"] == drills_completed_12mo, (
            f"drills_completed_12mo should be {drills_completed_12mo}, got {plan['drills_completed_12mo']}"
        )
    if unmitigated_hazard_count is not None:
        assert plan["unmitigated_hazard_count"] == unmitigated_hazard_count, (
            f"unmitigated_hazard_count should be {unmitigated_hazard_count}, "
            f"got {plan['unmitigated_hazard_count']}"
        )
    if overdue_action_count is not None:
        assert plan["overdue_action_count"] == overdue_action_count, (
            f"overdue_action_count should be {overdue_action_count}, got {plan['overdue_action_count']}"
        )


def assert_readiness(
    plan: Dict[str, Any],
    subtotal: Optional[float] = None,
    penalty_band: Optional[str] = None,
    penalty_points: Optional[float] = None,
    score: Optional[float] = None,
    inspection_ready: Optional[bool] = None,
) -> None:
    """The four readiness steps as they appear on the plan row."""
    if subtotal is not None:
        assert_two_decimal_value(plan["readiness_subtotal"], subtotal, "readiness_subtotal")
    if penalty_band is not None:
        assert plan["readiness_penalty_band"] == penalty_band, (
            f"readiness_penalty_band should be {penalty_band}, got {plan['readiness_penalty_band']}"
        )
    if penalty_points is not None:
        assert_two_decimal_value(
            plan["readiness_penalty_points"], penalty_points, "readiness_penalty_points"
        )
    if score is not None:
        assert_two_decimal_value(plan["readiness_score"], score, "readiness_score")
    if inspection_ready is not None:
        assert plan["inspection_ready"] is inspection_ready, (
            f"inspection_ready should be {inspection_ready}, got {plan['inspection_ready']}"
        )


def assert_penalty_band_from_rounded_subtotal(plan: Dict[str, Any]) -> None:
    """The band is selected from the rounded subtotal, never from the final score."""
    subtotal = plan["readiness_subtotal"]
    if subtotal >= PENALTY_BAND_STRONG_MIN:
        expected = "STRONG"
    elif subtotal >= PENALTY_BAND_ADEQUATE_MIN:
        expected = "ADEQUATE"
    else:
        expected = "WEAK"
    assert plan["readiness_penalty_band"] == expected, (
        f"a subtotal of {subtotal} bands as {expected}, got {plan['readiness_penalty_band']}"
    )


def assert_readiness_threshold_applied(plan: Dict[str, Any]) -> None:
    """Frozen plans are never ready; restricted plans need 85.00 and open plans 75.00."""
    posture = plan["compliance_posture"]
    score = plan["readiness_score"]
    if posture == "FROZEN":
        assert plan["inspection_ready"] is False, "a FROZEN plan is never inspection ready"
    elif posture == "RESTRICTED":
        assert plan["inspection_ready"] is (score >= READY_THRESHOLD_RESTRICTED), (
            f"a RESTRICTED plan at {score} should compare against {READY_THRESHOLD_RESTRICTED}"
        )
    else:
        assert plan["inspection_ready"] is (score >= READY_THRESHOLD_OPEN), (
            f"an OPEN plan at {score} should compare against {READY_THRESHOLD_OPEN}"
        )


# --------------------------------------------------------------------------
# Hazard assessment
# --------------------------------------------------------------------------


def assert_hazard_assessment(
    assessment: Dict[str, Any],
    hazard_score: Optional[float] = None,
    control_tier: Optional[str] = None,
    score_variant: Optional[str] = None,
    status: Optional[str] = None,
    mitigation_verified: Optional[bool] = None,
) -> None:
    if hazard_score is not None:
        assert_two_decimal_value(assessment["hazard_score"], hazard_score, "hazard_score")
    if control_tier is not None:
        assert assessment["control_tier"] == control_tier, (
            f"control_tier should be {control_tier}, got {assessment['control_tier']}"
        )
    if score_variant is not None:
        assert assessment["score_variant"] == score_variant, (
            f"score_variant should be {score_variant}, got {assessment['score_variant']}"
        )
    if status is not None:
        assert assessment["status"] == status, (
            f"assessment status should be {status}, got {assessment['status']}"
        )
    if mitigation_verified is not None:
        assert assessment["mitigation_verified"] is mitigation_verified, (
            f"mitigation_verified should be {mitigation_verified}, got {assessment['mitigation_verified']}"
        )


# --------------------------------------------------------------------------
# Incident report
# --------------------------------------------------------------------------


def assert_severity(
    report: Dict[str, Any],
    severity_points: int,
    severity_class: str,
    log_required: Optional[bool] = None,
) -> None:
    assert_integer_points(report["severity_points"], severity_points, "severity_points")
    assert report["severity_class"] == severity_class, (
        f"severity_class should be {severity_class}, got {report['severity_class']}"
    )
    if log_required is not None:
        assert report["log_required"] is log_required, (
            f"log_required should be {log_required}, got {report['log_required']}"
        )


def assert_report_dimensions(
    report: Dict[str, Any],
    triage_status: Optional[str] = None,
    retaliation_status: Optional[str] = None,
) -> None:
    """The triage and retaliation dimensions advance independently."""
    if triage_status is not None:
        assert report["triage_status"] == triage_status, (
            f"triage_status should be {triage_status}, got {report['triage_status']}"
        )
    if retaliation_status is not None:
        assert report["retaliation_status"] == retaliation_status, (
            f"retaliation_status should be {retaliation_status}, got {report['retaliation_status']}"
        )


# --------------------------------------------------------------------------
# Threat case
# --------------------------------------------------------------------------


def assert_case_state(
    case: Dict[str, Any],
    status: Optional[str] = None,
    assessment_round: Optional[int] = None,
    quorum_met: Optional[bool] = None,
    ballot_count_current_round: Optional[int] = None,
    open_action_count: Optional[int] = None,
) -> None:
    if status is not None:
        assert case["status"] == status, f"case status should be {status}, got {case['status']}"
    if assessment_round is not None:
        assert case["assessment_round"] == assessment_round, (
            f"assessment_round should be {assessment_round}, got {case['assessment_round']}"
        )
    if quorum_met is not None:
        assert case["quorum_met"] is quorum_met, (
            f"quorum_met should be {quorum_met}, got {case['quorum_met']}"
        )
    if ballot_count_current_round is not None:
        assert case["ballot_count_current_round"] == ballot_count_current_round, (
            f"ballot_count_current_round should be {ballot_count_current_round}, "
            f"got {case['ballot_count_current_round']}"
        )
    if open_action_count is not None:
        assert case["open_action_count"] == open_action_count, (
            f"open_action_count should be {open_action_count}, got {case['open_action_count']}"
        )


def assert_risk_scores(
    case: Dict[str, Any],
    interim: Optional[float] = None,
    consensus: Optional[float] = None,
    risk_band: Optional[str] = None,
    disposition: Optional[str] = None,
) -> None:
    if interim is not None:
        assert_two_decimal_value(case["interim_risk_score"], interim, "interim_risk_score")
    if consensus is not None:
        assert_two_decimal_value(case["consensus_risk_score"], consensus, "consensus_risk_score")
    if risk_band is not None:
        assert case["risk_band"] == risk_band, (
            f"risk_band should be {risk_band}, got {case['risk_band']}"
        )
    if disposition is not None:
        assert case["disposition"] == disposition, (
            f"disposition should be {disposition}, got {case['disposition']}"
        )


def assert_protection(
    case: Dict[str, Any],
    coverage_gap_hours: Optional[float] = None,
    protection_status: Optional[str] = None,
) -> None:
    if coverage_gap_hours is not None:
        assert_two_decimal_value(case["coverage_gap_hours"], coverage_gap_hours, "coverage_gap_hours")
    if protection_status is not None:
        assert case["protection_status"] == protection_status, (
            f"protection_status should be {protection_status}, got {case['protection_status']}"
        )


def assert_seat_ballot(
    seat: Dict[str, Any],
    ballot_value: Optional[str] = None,
    ballot_round: Optional[int] = None,
    ballot_weight: Optional[float] = None,
    ballot_share: Optional[float] = None,
) -> None:
    if ballot_value is not None:
        assert seat["ballot_value"] == ballot_value, (
            f"ballot_value should be {ballot_value}, got {seat['ballot_value']}"
        )
    if ballot_round is not None:
        assert seat["ballot_round"] == ballot_round, (
            f"ballot_round should be {ballot_round}, got {seat['ballot_round']}"
        )
    if ballot_weight is not None:
        assert seat["ballot_weight"] == pytest.approx(ballot_weight, abs=0.0005), (
            f"ballot_weight should be {ballot_weight}, got {seat['ballot_weight']}"
        )
    if ballot_share is not None:
        assert_two_decimal_value(seat["ballot_share"], ballot_share, "ballot_share")


def assert_seat_ballot_cleared(seat: Dict[str, Any]) -> None:
    """Reassessment and recusal clear every ballot field on the seat."""
    for field in (
        "ballot_value",
        "ballot_round",
        "ballot_weight",
        "ballot_share",
        "ballot_submitted_at",
        "rationale",
    ):
        assert seat[field] is None, f"{field} should be cleared, got {seat[field]!r}"


# --------------------------------------------------------------------------
# Case actions and conserved counters
# --------------------------------------------------------------------------


def assert_case_action(
    action: Dict[str, Any],
    status: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    auto_generated: Optional[bool] = None,
    late_flag: Optional[bool] = None,
) -> None:
    if status is not None:
        assert action["status"] == status, (
            f"action status should be {status}, got {action['status']}"
        )
    if duration_minutes is not None:
        assert action["duration_minutes"] == duration_minutes, (
            f"duration_minutes should be {duration_minutes}, got {action['duration_minutes']}"
        )
    if auto_generated is not None:
        assert action["auto_generated"] is auto_generated, (
            f"auto_generated should be {auto_generated}, got {action['auto_generated']}"
        )
    if late_flag is not None:
        assert action["late_flag"] is late_flag, (
            f"late_flag should be {late_flag}, got {action['late_flag']}"
        )


def assert_escort_ledger(employee: Dict[str, Any], expected_minutes: int) -> None:
    """The escort-minute ledger is conserved: what a write adds, a later write removes."""
    assert employee["escort_committed_minutes"] == expected_minutes, (
        f"escort_committed_minutes should be {expected_minutes}, "
        f"got {employee['escort_committed_minutes']}"
    )


def assert_restriction_counters(
    work_area: Dict[str, Any], subject: Dict[str, Any], expected_area: int, expected_subject: int
) -> None:
    """Both restriction counters move together and return to where they started."""
    assert work_area["restricted_employee_count"] == expected_area, (
        f"restricted_employee_count should be {expected_area}, "
        f"got {work_area['restricted_employee_count']}"
    )
    assert subject["active_restriction_count"] == expected_subject, (
        f"active_restriction_count should be {expected_subject}, "
        f"got {subject['active_restriction_count']}"
    )


# --------------------------------------------------------------------------
# Violent incident log
# --------------------------------------------------------------------------


def assert_log_elements_present(entry: Dict[str, Any], expected_count: int) -> None:
    """required_element_count_present counts the eight regulatory elements."""
    assert entry["required_element_count_present"] == expected_count, (
        f"required_element_count_present should be {expected_count}, "
        f"got {entry['required_element_count_present']}"
    )
    assert expected_count <= REQUIRED_LOG_ELEMENT_COUNT


def assert_auto_appended_entry_is_partial(entry: Dict[str, Any]) -> None:
    """The auto-appended entry carries six elements, leaving the two narratives null."""
    assert_log_elements_present(entry, 6)
    assert entry["consequence_narrative"] is None, "consequence_narrative should still be null"
    assert entry["controls_summary"] is None, "controls_summary should still be null"


# --------------------------------------------------------------------------
# Sweep counters
# --------------------------------------------------------------------------

SWEEP_COUNTER_NAMES = (
    "training_expired_count",
    "drills_missed_count",
    "protective_activated_count",
    "protective_expired_count",
    "actions_overdue_count",
    "log_retention_expired_count",
    "plans_review_due_count",
    "plans_rescored_count",
)


def assert_sweep_counters(data: Dict[str, Any], strict: bool = False, **expected: int) -> None:
    """Assert the named sweep counters; with ``strict`` every unnamed counter must be zero."""
    for name in SWEEP_COUNTER_NAMES:
        assert name in data, f"the sweep must report {name}"
    for name in SWEEP_COUNTER_NAMES:
        if name not in expected and not strict:
            continue
        want = expected.get(name, 0)
        assert data[name] == want, f"{name} should be {want}, got {data[name]}"


# --------------------------------------------------------------------------
# Listings
# --------------------------------------------------------------------------


def assert_list_contains_exactly(response: Any, expected_ids: Iterable[str]) -> List[Dict[str, Any]]:
    """A filtered list holds exactly the expected rows, and total_count agrees."""
    data, meta = validate_paginated(response)
    wanted = list(expected_ids)
    assert meta["total_count"] == len(wanted), (
        f"total_count should be {len(wanted)}, got {meta['total_count']}"
    )
    assert [row["id"] for row in data] == wanted or sorted(row["id"] for row in data) == sorted(
        wanted
    ), f"listing should hold {wanted}, got {[row['id'] for row in data]}"
    return data


def assert_total_count(response: Any, expected: int) -> List[Dict[str, Any]]:
    data, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        f"total_count should be {expected}, got {meta['total_count']}"
    )
    return data


def assert_sorted_by_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows must be sorted by created_at ascending, got {stamps}"
