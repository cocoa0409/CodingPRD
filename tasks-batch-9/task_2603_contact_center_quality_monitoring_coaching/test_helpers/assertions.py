"""Per-entity shape assertions and domain invariant checkers.

The shape assertions encode PRD 2.4: twelve of the thirteen resource types
carry `id`, `created_at`, `updated_at` and `version`, while the calibration
submission "carries only `id` and `created_at`, and both `updated_at` and
`version` are absent from its representation".
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import LIVE_SELECTION_STATUSES
from .types import (
    ALIGNMENTS,
    CALIBRATION_STATUSES,
    CHANNELS,
    COACHING_PLAN_STATUSES,
    COACHING_STATES,
    COACHING_TIERS,
    COMPLIANCE_RESULTS,
    CONSENT_STATUSES,
    DISPUTE_STATUSES,
    EXCLUSION_REASONS,
    FEEDBACK_STATUSES,
    FORM_STATUSES,
    PLAN_STATUSES,
    REVIEW_STATUSES,
    SELECTION_SOURCES,
    SELECTION_STATUSES,
    SESSION_STATUSES,
)

TOL = 0.01


# --------------------------------------------------------------------------
# Generic building blocks
# --------------------------------------------------------------------------
def assert_system_fields(row: Dict[str, Any], *, versioned: bool = True) -> None:
    """`id` is a UUID, timestamps are ISO 8601, `version` starts at one."""
    assert is_valid_uuid(row["id"]), "id must be a UUID with no type prefix: {}".format(row["id"])
    assert is_iso8601_timestamp(row["created_at"]), "created_at must be ISO 8601 UTC with three fractional digits"
    if versioned:
        assert is_iso8601_timestamp(row["updated_at"]), "updated_at must be ISO 8601 UTC with three fractional digits"
        assert isinstance(row["version"], int) and row["version"] >= 1


def assert_money(value: Any, expected: float) -> None:
    """A two-decimal decimal figure compared at its own precision."""
    assert value == pytest.approx(expected, abs=TOL), "expected {} got {}".format(expected, value)


def assert_two_decimals(value: Any) -> None:
    """The figure carries at most two decimal places."""
    assert value is not None
    rendered = "{:.10f}".format(float(value)).rstrip("0")
    if "." in rendered:
        fractional = rendered.split(".")[1]
        assert len(fractional) <= 2, "expected at most two decimal places, got {}".format(value)


def assert_enum(value: Any, allowed: Iterable[str], field: str) -> None:
    assert value in list(allowed), "{} must be one of {}, got {}".format(field, list(allowed), value)


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
def assert_evaluation_form(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert isinstance(row["name"], str) and 1 <= len(row["name"]) <= 120
    assert isinstance(row["version_label"], str) and 1 <= len(row["version_label"]) <= 20
    assert_enum(row["status"], FORM_STATUSES, "status")
    assert_enum(row["auto_fail_policy"], ["ZERO_TOTAL", "COMPLIANCE_SECTION_ZERO"], "auto_fail_policy")
    assert isinstance(row["min_compliance_item_score"], int) and row["min_compliance_item_score"] >= 1
    assert_two_decimals(row["behavior_weight_total"])
    assert isinstance(row["compliance_behavior_count"], int)
    assert isinstance(row["guidance_version"], int) and row["guidance_version"] >= 1
    assert "activated_at" in row and "retired_at" in row


def assert_form_behavior(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert is_valid_uuid(row["form_id"])
    assert isinstance(row["code"], str) and 2 <= len(row["code"]) <= 24
    assert isinstance(row["label"], str)
    assert_two_decimals(row["weight_pct"])
    assert isinstance(row["guidance_text"], str)
    assert isinstance(row["compliance_critical"], bool)
    assert isinstance(row["auto_fail_on_violation"], bool)
    assert row["max_points"] in (3, 4, 5)
    assert isinstance(row["allows_not_applicable"], bool)
    assert isinstance(row["guidance_version"], int) and row["guidance_version"] >= 1


def assert_agent(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert isinstance(row["external_ref"], str)
    assert isinstance(row["full_name"], str)
    assert isinstance(row["team_code"], str)
    assert is_iso8601_timestamp(row["hire_date"]) or isinstance(row["hire_date"], str)
    assert "quality_index_rolling" in row and "quality_index_period" in row
    assert isinstance(row["open_compliance_findings"], int)
    assert isinstance(row["consecutive_passing_evaluations"], int)
    assert_enum(row["coaching_state"], COACHING_STATES, "coaching_state")
    assert isinstance(row["recognition_points"], int)


def assert_evaluator(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert isinstance(row["full_name"], str)
    assert isinstance(row["max_open_assignments"], int) and 1 <= row["max_open_assignments"] <= 20
    assert_enum(row["calibration_status"], CALIBRATION_STATUSES, "calibration_status")
    assert isinstance(row["open_assignment_count"], int) and row["open_assignment_count"] >= 0
    assert "last_deviation_pct" in row


def assert_interaction(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert is_valid_uuid(row["agent_id"])
    assert_enum(row["channel"], CHANNELS, "channel")
    assert isinstance(row["duration_seconds"], int) and row["duration_seconds"] >= 0
    assert isinstance(row["required_disclosures"], list)
    assert isinstance(row["captured_disclosures"], list)
    assert isinstance(row["customer_flagged"], bool)
    assert "csat_score" in row
    assert isinstance(row["repeat_contact_within_72h"], bool)
    assert_enum(row["recording_consent_status"], CONSENT_STATUSES, "recording_consent_status")
    assert isinstance(row["compliance_hold"], bool)
    assert isinstance(row["sampled_count"], int) and row["sampled_count"] >= 0


def assert_analytics_scan(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert is_valid_uuid(row["interaction_id"])
    assert_two_decimals(row["silence_pct"])
    assert_two_decimals(row["sentiment_delta"])
    assert isinstance(row["flagged_categories"], list)
    assert_two_decimals(row["risk_score"])
    assert 0.00 <= float(row["risk_score"]) <= 100.00
    assert_enum(row["priority_tier"], ["P1", "P2", "P3"], "priority_tier")
    assert_enum(row["status"], ["CURRENT", "SUPERSEDED"], "status")


def assert_sample_plan(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert is_valid_uuid(row["form_id"])
    assert isinstance(row["per_agent_target_volume"], int)
    assert 1 <= row["per_agent_target_volume"] <= 50
    assert isinstance(row["source_mix"], dict)
    assert set(row["source_mix"].keys()) == {"random_pct", "targeted_pct", "customer_flagged_pct"}
    assert_enum(row["status"], PLAN_STATUSES, "status")
    assert "pinned_form_guidance_version" in row
    assert isinstance(row["selections_count"], int)
    assert isinstance(row["excluded_count"], int)
    assert isinstance(row["targeted_reserved_count"], int)
    assert isinstance(row["targeted_reserve_by_agent"], dict)
    assert isinstance(row["agent_volume_attainment"], dict)


def assert_sample_selection(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert is_valid_uuid(row["plan_id"])
    assert is_valid_uuid(row["interaction_id"])
    assert is_valid_uuid(row["agent_id"])
    assert_enum(row["source"], SELECTION_SOURCES, "source")
    assert_enum(row["status"], SELECTION_STATUSES, "status")
    assert "assigned_evaluator_id" in row
    assert "review_window_start" in row and "review_window_end" in row
    assert "exclusion_reason" in row
    if row["exclusion_reason"] is not None:
        assert_enum(row["exclusion_reason"], EXCLUSION_REASONS, "exclusion_reason")


def assert_evaluation(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert is_valid_uuid(row["selection_id"])
    assert is_valid_uuid(row["evaluator_id"])
    assert is_valid_uuid(row["form_id"])
    assert is_valid_uuid(row["agent_id"])
    assert isinstance(row["pinned_guidance_version"], int)
    assert isinstance(row["item_scores"], dict)
    assert "weighted_score" in row and "raw_weighted_score" in row
    assert "adjusted_weighted_score" in row
    assert isinstance(row["auto_fail_triggered"], bool)
    assert_enum(row["compliance_result"], COMPLIANCE_RESULTS, "compliance_result")
    assert_enum(row["review_status"], REVIEW_STATUSES, "review_status")
    assert_enum(row["feedback_status"], FEEDBACK_STATUSES, "feedback_status")
    assert "submitted_at" in row and "feedback_delivered_at" in row and "agreement" in row


def assert_dispute(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert is_valid_uuid(row["evaluation_id"])
    assert is_valid_uuid(row["agent_id"])
    assert isinstance(row["disputed_behavior_codes"], list) and row["disputed_behavior_codes"]
    assert isinstance(row["rationale"], str) and 10 <= len(row["rationale"]) <= 1000
    assert_enum(row["status"], DISPUTE_STATUSES, "status")
    assert "reviewer_evaluator_id" in row
    assert isinstance(row["round_count"], int) and 0 <= row["round_count"] <= 2
    assert "adjusted_item_scores" in row and "outcome_note" in row


def assert_calibration_session(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert is_valid_uuid(row["form_id"])
    assert is_valid_uuid(row["interaction_id"])
    assert isinstance(row["benchmark_item_scores"], dict)
    assert "benchmark_weighted_score" in row
    assert_enum(row["status"], SESSION_STATUSES, "status")
    assert isinstance(row["participant_count"], int)
    assert "variance_pct" in row and "mean_abs_deviation" in row
    assert isinstance(row["guidance_updates_applied"], int)


def assert_calibration_submission(row: Dict[str, Any]) -> None:
    """A calibration submission is immutable and versionless."""
    assert_system_fields(row, versioned=False)
    assert "updated_at" not in row, "a calibration submission carries no updated_at"
    assert "version" not in row, "a calibration submission carries no version"
    assert is_valid_uuid(row["session_id"])
    assert is_valid_uuid(row["evaluator_id"])
    assert isinstance(row["item_scores"], dict)
    assert "weighted_score" in row
    assert "deviation_pct" in row and "alignment" in row
    if row["alignment"] is not None:
        assert_enum(row["alignment"], ALIGNMENTS, "alignment")


def assert_coaching_plan(row: Dict[str, Any]) -> None:
    assert_system_fields(row)
    assert is_valid_uuid(row["agent_id"])
    assert is_valid_uuid(row["source_evaluation_id"])
    assert isinstance(row["assigned_supervisor_id"], str)
    assert_two_decimals(row["target_score"])
    assert_two_decimals(row["deficit_pct"])
    assert_enum(row["coaching_tier"], COACHING_TIERS, "coaching_tier")
    assert_enum(row["escalation_tier"], COACHING_TIERS, "escalation_tier")
    assert isinstance(row["required_session_count"], int)
    assert 1 <= row["required_session_count"] <= 8
    assert isinstance(row["completed_session_count"], int)
    assert is_iso8601_timestamp(row["due_at"]) or isinstance(row["due_at"], str)
    assert_enum(row["status"], COACHING_PLAN_STATUSES, "status")
    assert "escalation_note" in row


def assert_quality_summary(row: Dict[str, Any]) -> None:
    for field in (
        "quality_index_rolling",
        "quality_index_period",
        "evaluations_considered",
        "paired_sample_size",
        "csat_gap_paired",
        "csat_gap_all",
        "repeat_contact_rate",
    ):
        assert field in row, "quality summary must report {}".format(field)
    assert isinstance(row["evaluations_considered"], int)
    assert isinstance(row["paired_sample_size"], int)


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_attainment(
    plan: Dict[str, Any],
    agent_id: str,
    *,
    consumed: int,
    remaining: int,
    by_source: Optional[Dict[str, int]] = None,
) -> None:
    """One agent's entry inside `agent_volume_attainment`.

    PRD 3.4 publishes the three figures "per agent inside
    `agent_volume_attainment` as an object with `consumed`, `remaining` and a
    `by_source` breakdown keyed by `RANDOM`, `TARGETED` and
    `CUSTOMER_FLAGGED`".
    """
    attainment = plan["agent_volume_attainment"]
    assert agent_id in attainment, "agent {} missing from agent_volume_attainment".format(agent_id)
    entry = attainment[agent_id]
    assert entry["consumed"] == consumed, "consumed: expected {} got {}".format(consumed, entry["consumed"])
    assert entry["remaining"] == remaining, "remaining: expected {} got {}".format(remaining, entry["remaining"])
    assert set(entry["by_source"].keys()) == {"RANDOM", "TARGETED", "CUSTOMER_FLAGGED"}
    if by_source is not None:
        for source, count in by_source.items():
            assert entry["by_source"][source] == count, (
                "by_source[{}]: expected {} got {}".format(source, count, entry["by_source"][source])
            )


def assert_quota_identity(plan: Dict[str, Any], agent_id: str) -> None:
    """The conservation identity of PRD 3.4.

    "for every plan and agent, `consumed` plus `remaining` equals
    `per_agent_target_volume` plus that agent's reserve".
    """
    entry = plan["agent_volume_attainment"][agent_id]
    reserve = plan["targeted_reserve_by_agent"].get(agent_id, 0)
    assert entry["consumed"] + entry["remaining"] == plan["per_agent_target_volume"] + reserve, (
        "consumed {} + remaining {} must equal per_agent_target_volume {} + reserve {}".format(
            entry["consumed"], entry["remaining"], plan["per_agent_target_volume"], reserve
        )
    )


def assert_plan_counters(
    plan: Dict[str, Any],
    *,
    selections_count: int,
    excluded_count: int,
    targeted_reserved_count: Optional[int] = None,
) -> None:
    """The plan-level counters of PRD 3.4."""
    assert plan["selections_count"] == selections_count, (
        "selections_count: expected {} got {}".format(selections_count, plan["selections_count"])
    )
    assert plan["excluded_count"] == excluded_count, (
        "excluded_count: expected {} got {}".format(excluded_count, plan["excluded_count"])
    )
    if targeted_reserved_count is not None:
        assert plan["targeted_reserved_count"] == targeted_reserved_count, (
            "targeted_reserved_count: expected {} got {}".format(
                targeted_reserved_count, plan["targeted_reserved_count"]
            )
        )


def assert_selection_counters_match_rows(plan: Dict[str, Any], selections: List[Dict[str, Any]]) -> None:
    """`selections_count` and `excluded_count` reconcile against the rows.

    PRD 3.4: "`selections_count` is the number of selections of the plan in
    status `SELECTED`, `ASSIGNED` or `EVALUATED`; `excluded_count` is the
    number in status `EXCLUDED`".
    """
    live = [s for s in selections if s["status"] in LIVE_SELECTION_STATUSES]
    excluded = [s for s in selections if s["status"] == "EXCLUDED"]
    assert plan["selections_count"] == len(live)
    assert plan["excluded_count"] == len(excluded)


def assert_evaluator_load(evaluator: Dict[str, Any], expected_open: int) -> None:
    """PRD 3.2 defines `open_assignment_count` as the number of ASSIGNED rows."""
    assert evaluator["open_assignment_count"] == expected_open, (
        "open_assignment_count: expected {} got {}".format(expected_open, evaluator["open_assignment_count"])
    )


def assert_evaluator_load_matches_rows(evaluator: Dict[str, Any], selections: List[Dict[str, Any]]) -> None:
    """The load ledger reconciles against the selection rows that name it."""
    expected = [
        s
        for s in selections
        if s.get("assigned_evaluator_id") == evaluator["id"] and s["status"] == "ASSIGNED"
    ]
    assert evaluator["open_assignment_count"] == len(expected), (
        "open_assignment_count {} does not reconcile with {} ASSIGNED selections".format(
            evaluator["open_assignment_count"], len(expected)
        )
    )


def assert_released_selection(selection: Dict[str, Any]) -> None:
    """A released selection carries no evaluator and no window bounds."""
    assert selection["assigned_evaluator_id"] is None, "assigned_evaluator_id must be cleared"
    assert selection["review_window_start"] is None, "review_window_start must be cleared"
    assert selection["review_window_end"] is None, "review_window_end must be cleared"


def assert_excluded_selection(selection: Dict[str, Any], reason: str) -> None:
    """An excluded selection records its reason and releases its evaluator."""
    assert selection["status"] == "EXCLUDED"
    assert selection["exclusion_reason"] == reason, (
        "exclusion_reason: expected {} got {}".format(reason, selection["exclusion_reason"])
    )
    assert_released_selection(selection)


def assert_scores(
    evaluation: Dict[str, Any],
    *,
    weighted_score: Any = ...,
    raw_weighted_score: Any = ...,
    adjusted_weighted_score: Any = ...,
    auto_fail_triggered: Any = ...,
    compliance_result: Any = ...,
) -> None:
    """The score triple and the verdict of one evaluation."""
    if weighted_score is not ...:
        if weighted_score is None:
            assert evaluation["weighted_score"] is None, "weighted_score must be null"
        else:
            assert_money(evaluation["weighted_score"], weighted_score)
    if raw_weighted_score is not ...:
        if raw_weighted_score is None:
            assert evaluation["raw_weighted_score"] is None, "raw_weighted_score must be null"
        else:
            assert_money(evaluation["raw_weighted_score"], raw_weighted_score)
    if adjusted_weighted_score is not ...:
        if adjusted_weighted_score is None:
            assert evaluation["adjusted_weighted_score"] is None, "adjusted_weighted_score must be null"
        else:
            assert_money(evaluation["adjusted_weighted_score"], adjusted_weighted_score)
    if auto_fail_triggered is not ...:
        assert evaluation["auto_fail_triggered"] is auto_fail_triggered
    if compliance_result is not ...:
        assert evaluation["compliance_result"] == compliance_result, (
            "compliance_result: expected {} got {}".format(compliance_result, evaluation["compliance_result"])
        )


def assert_parallel_state(evaluation: Dict[str, Any], review_status: str, feedback_status: str) -> None:
    """Both dimensions of the parallel state machine of PRD 3.5."""
    assert evaluation["review_status"] == review_status, (
        "review_status: expected {} got {}".format(review_status, evaluation["review_status"])
    )
    assert evaluation["feedback_status"] == feedback_status, (
        "feedback_status: expected {} got {}".format(feedback_status, evaluation["feedback_status"])
    )


def assert_agent_index(
    agent: Dict[str, Any],
    *,
    rolling: Any = ...,
    period: Any = ...,
    open_compliance_findings: Any = ...,
    consecutive_passing_evaluations: Any = ...,
    coaching_state: Any = ...,
    recognition_points: Any = ...,
) -> None:
    """The agent's derived standing figures."""
    if rolling is not ...:
        if rolling is None:
            assert agent["quality_index_rolling"] is None, "quality_index_rolling must be null"
        else:
            assert_money(agent["quality_index_rolling"], rolling)
    if period is not ...:
        if period is None:
            assert agent["quality_index_period"] is None, "quality_index_period must be null"
        else:
            assert_money(agent["quality_index_period"], period)
    if open_compliance_findings is not ...:
        assert agent["open_compliance_findings"] == open_compliance_findings, (
            "open_compliance_findings: expected {} got {}".format(
                open_compliance_findings, agent["open_compliance_findings"]
            )
        )
    if consecutive_passing_evaluations is not ...:
        assert agent["consecutive_passing_evaluations"] == consecutive_passing_evaluations, (
            "consecutive_passing_evaluations: expected {} got {}".format(
                consecutive_passing_evaluations, agent["consecutive_passing_evaluations"]
            )
        )
    if coaching_state is not ...:
        assert agent["coaching_state"] == coaching_state, (
            "coaching_state: expected {} got {}".format(coaching_state, agent["coaching_state"])
        )
    if recognition_points is not ...:
        assert agent["recognition_points"] == recognition_points


def assert_summary_figures(
    summary: Dict[str, Any],
    *,
    rolling: Any = ...,
    period: Any = ...,
    evaluations_considered: Any = ...,
    paired_sample_size: Any = ...,
    csat_gap_paired: Any = ...,
    csat_gap_all: Any = ...,
    repeat_contact_rate: Any = ...,
) -> None:
    """The seven figures of the per-agent quality summary of PRD 3.9."""
    pairs = [
        ("quality_index_rolling", rolling),
        ("quality_index_period", period),
        ("csat_gap_paired", csat_gap_paired),
        ("csat_gap_all", csat_gap_all),
        ("repeat_contact_rate", repeat_contact_rate),
    ]
    for field, expected in pairs:
        if expected is ...:
            continue
        if expected is None:
            assert summary[field] is None, "{} must be null, got {}".format(field, summary[field])
        else:
            assert summary[field] is not None, "{} must not be null".format(field)
            assert_money(summary[field], expected)
    if evaluations_considered is not ...:
        assert summary["evaluations_considered"] == evaluations_considered, (
            "evaluations_considered: expected {} got {}".format(
                evaluations_considered, summary["evaluations_considered"]
            )
        )
    if paired_sample_size is not ...:
        assert summary["paired_sample_size"] == paired_sample_size, (
            "paired_sample_size: expected {} got {}".format(paired_sample_size, summary["paired_sample_size"])
        )


def assert_ordered_by(rows: List[Dict[str, Any]], field: str, descending: bool = False) -> None:
    """A list page honours the ordering the PRD declares for it."""
    values = [row[field] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, "expected ordering by {} {}: {}".format(
        field, "descending" if descending else "ascending", values
    )


def assert_version(row: Dict[str, Any], expected: int) -> None:
    assert row["version"] == expected, "version: expected {} got {}".format(expected, row["version"])


def _normalise_instant(value: str) -> str:
    """Strip fractional digits so two renderings of one instant compare equal."""
    text = str(value).replace("Z", "+00:00")
    if "." in text:
        head, tail = text.split(".", 1)
        offset = ""
        for marker in ("+", "-"):
            idx = tail.find(marker)
            if idx > 0:
                offset = tail[idx:]
                break
        text = head + offset
    if text.endswith("+00:00"):
        text = text[: -len("+00:00")]
    return text


def assert_instant(value: Any, expected_iso: str) -> None:
    """Two UTC instants are the same second, whatever the fractional rendering."""
    assert value is not None, "expected instant {}, got null".format(expected_iso)
    assert _normalise_instant(value) == _normalise_instant(expected_iso), (
        "expected instant {} got {}".format(expected_iso, value)
    )
