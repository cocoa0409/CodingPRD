"""Domain assertions: resource shape checks and business invariant checks.

Two families of helper live here.

``assert_<entity>()`` verifies the field set and field types of one resource,
including the common-field contract of PRD §2.5 -- the ten mutable resources
carry ``id``, ``created_at``, ``updated_at`` and ``version``, while the five
append-only resources carry only ``id`` and ``created_at`` and must not expose
``updated_at`` or ``version`` at all.

``assert_<invariant>()`` verifies a computed rule of PRD §3: the risk score and
its tier, the readiness variants, the rollout ladder ceiling and soak bands, the
staleness debt and its hygiene tier, the canary rounding chain, and the evidence
packet index chain.
"""

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BLAST_RADIUS_POINTS,
    CLEANUP_ENFORCED_FLOOR,
    CLEANUP_OVERDUE_FLOOR,
    COMPLETENESS_INDEX_MAX,
    DEPENDENCY_POINTS_CAP,
    DEPENDENCY_POINTS_PER_DEPTH,
    ERROR_COMPONENT_MULTIPLIER,
    ERROR_COMPONENT_WEIGHT,
    EVIDENCE_ITEM_WEIGHTS,
    LADDER_MAX_PCT,
    LADDER_MIN_CEILING_PCT,
    LADDER_MULTIPLIER,
    LATENCY_COMPONENT_MULTIPLIER,
    LATENCY_COMPONENT_WEIGHT,
    MIGRATION_POINTS,
    RISK_SCORE_MAX,
    RISK_SCORE_MIN,
    RISK_TIER_CRITICAL_FLOOR,
    RISK_TIER_HIGH_FLOOR,
    RISK_TIER_MEDIUM_FLOOR,
    SIZE_POINTS_CAP,
    SIZE_POINTS_PER_HUNDRED_LINES,
    SOAK_BAND_LOW_TARGET_PCT,
    SOAK_BAND_MID_TARGET_PCT,
    SOAK_MINUTES_HIGH,
    SOAK_MINUTES_LOW,
    SOAK_MINUTES_MID,
    SPREAD_POINTS_CAP,
    SPREAD_POINTS_PER_SUBSYSTEM,
    STALE_DEBT_CAP,
    WAIVER_CAP_DEFAULT,
    WAIVER_CAP_TIERS,
)
from .types import (
    CanaryVerdict,
    CleanupState,
    RiskClass,
)

# ---------------------------------------------------------------------------
# Instant comparison
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant the API rendered or the PRD pinned."""
    assert isinstance(value, str) and value.strip(), f"not a timestamp: {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant(actual: Any, expected: str, label: str = "timestamp") -> None:
    """Assert a timestamp field carries exactly the PRD-pinned instant.

    The PRD pins the *instant* every stamped, echoed or derived timestamp
    carries and fixes the rendered fractional precision only for
    ``api_request_timestamp`` (§2.2) and ``created_at`` (§2.5).  Every other
    timestamp is therefore compared as an instant, so ``2026-08-08T00:00:00Z``
    and ``2026-08-08T00:00:00.000Z`` are the same answer.
    """
    assert actual is not None, f"{label} is null, expected {expected}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"expected {label} {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Common-field helpers (PRD §2.5)
# ---------------------------------------------------------------------------

MUTABLE_COMMON_FIELDS = ("id", "created_at", "updated_at", "version")
APPEND_ONLY_COMMON_FIELDS = ("id", "created_at")


def assert_common_fields(resource: Dict[str, Any]) -> None:
    """The full common quartet, present on the ten mutable resources."""
    for field in MUTABLE_COMMON_FIELDS:
        assert field in resource, f"missing common field '{field}': {resource}"
    assert is_valid_uuid(resource["id"]), f"id must be a bare UUID: {resource['id']}"
    assert is_iso8601_timestamp(resource["created_at"]), resource["created_at"]
    assert is_iso8601_timestamp(resource["updated_at"]), resource["updated_at"]
    assert isinstance(resource["version"], int) and resource["version"] >= 1


def assert_append_only_common_fields(resource: Dict[str, Any]) -> None:
    """Only ``id`` and ``created_at``; ``updated_at`` and ``version`` absent."""
    for field in APPEND_ONLY_COMMON_FIELDS:
        assert field in resource, f"missing common field '{field}': {resource}"
    assert is_valid_uuid(resource["id"]), f"id must be a bare UUID: {resource['id']}"
    assert is_iso8601_timestamp(resource["created_at"]), resource["created_at"]
    assert "updated_at" not in resource, (
        f"append-only resource must not expose updated_at: {resource}"
    )
    assert "version" not in resource, (
        f"append-only resource must not expose version: {resource}"
    )


def assert_no_version_field(resource: Dict[str, Any]) -> None:
    """Alias used by tests asserting immutability of a junction row."""
    assert "version" not in resource, f"unexpected version field: {resource}"
    assert "updated_at" not in resource, f"unexpected updated_at field: {resource}"


# ---------------------------------------------------------------------------
# Resource shape assertions
# ---------------------------------------------------------------------------


def assert_release_train(train: Dict[str, Any]) -> None:
    assert_common_fields(train)
    for field in (
        "name",
        "cadence_days",
        "code_freeze_lead_hours",
        "stabilization_hours",
        "risk_budget_points",
        "max_concurrent_stabilizing",
        "phase",
        "freeze_exception_count",
        "open_release_count",
    ):
        assert field in train, f"release train missing '{field}': {train}"
    assert train["phase"] in ("ACTIVE", "FROZEN")
    assert "frozen_at" in train
    assert isinstance(train["freeze_exception_count"], int)
    assert isinstance(train["open_release_count"], int)


def assert_environment(environment: Dict[str, Any]) -> None:
    assert_common_fields(environment)
    for field in (
        "name",
        "tier",
        "deploy_window_start_hour_utc",
        "deploy_window_end_hour_utc",
        "cooldown_minutes",
        "requires_compliance_evidence",
        "active_deployment_count",
    ):
        assert field in environment, f"environment missing '{field}': {environment}"
    assert environment["tier"] in ("DEV", "STAGING", "PROD")
    assert 0 <= environment["deploy_window_start_hour_utc"] <= 23
    assert 1 <= environment["deploy_window_end_hour_utc"] <= 24
    assert (
        environment["deploy_window_end_hour_utc"]
        > environment["deploy_window_start_hour_utc"]
    )
    assert isinstance(environment["requires_compliance_evidence"], bool)
    assert "blackout_start_at" in environment
    assert "blackout_end_at" in environment
    assert "last_deployment_end_at" in environment


def assert_release(release: Dict[str, Any]) -> None:
    assert_common_fields(release)
    for field in (
        "release_train_id",
        "version_label",
        "cut_at",
        "freeze_at",
        "stabilization_end_at",
        "phase",
        "readiness_score_projected",
        "readiness_score_attested",
        "rollback_plan_confirmed",
        "evidence_packet_required",
        "freeze_exception_approved",
        "committed_change_count",
        "verified_change_count",
        "risk_budget_consumed_points",
    ):
        assert field in release, f"release missing '{field}': {release}"
    assert release["phase"] in (
        "OPEN",
        "FROZEN",
        "CUT",
        "STABILIZING",
        "RELEASED",
        "ROLLED_BACK",
    )
    assert_point_scale(release["readiness_score_projected"])
    if release["readiness_score_attested"] is not None:
        assert_point_scale(release["readiness_score_attested"])
    assert isinstance(release["rollback_plan_confirmed"], bool)
    assert isinstance(release["evidence_packet_required"], bool)
    assert isinstance(release["freeze_exception_approved"], bool)


def assert_change_request(change: Dict[str, Any]) -> None:
    assert_common_fields(change)
    for field in (
        "release_id",
        "title",
        "author_user_id",
        "lines_changed",
        "touched_subsystem_count",
        "has_schema_migration",
        "declared_blast_radius",
        "state",
        "risk_score_preliminary",
        "risk_score_final",
        "risk_class",
        "dependency_depth",
        "approval_technical_count",
        "approval_compliance_count",
        "approval_cab_count",
        "deployment_verified",
    ):
        assert field in change, f"change request missing '{field}': {change}"
    assert change["declared_blast_radius"] in ("INTERNAL", "SINGLE_TENANT", "GLOBAL")
    assert change["state"] in (
        "DRAFT",
        "RISK_CLASSIFIED",
        "CAB_REVIEW",
        "APPROVED",
        "BLOCKED_BY_DEPENDENCY",
        "MERGED",
        "DEPLOYED",
        "DEFERRED",
        "WITHDRAWN",
        "REJECTED",
    )
    if change["risk_score_preliminary"] is not None:
        assert_point_scale(change["risk_score_preliminary"])
    if change["risk_score_final"] is not None:
        assert_point_scale(change["risk_score_final"])
    if change["risk_class"] is not None:
        assert change["risk_class"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(change["dependency_depth"], int)


def assert_feature_flag(flag: Dict[str, Any]) -> None:
    assert_common_fields(flag)
    for field in (
        "key",
        "owner_user_id",
        "created_by_user_id",
        "expires_at",
        "permanent",
        "state",
        "cleanup_state",
        "current_exposure_pct",
        "applied_step_count",
        "kill_switch_engaged",
        "stale_debt_points",
    ):
        assert field in flag, f"feature flag missing '{field}': {flag}"
    assert flag["state"] in (
        "DRAFT",
        "ACTIVE_ROLLING_OUT",
        "PAUSED",
        "FULLY_ROLLED_OUT",
        "ARCHIVED",
    )
    assert flag["cleanup_state"] in ("COMPLIANT", "WARNING", "OVERDUE", "ENFORCED")
    assert isinstance(flag["permanent"], bool)
    assert isinstance(flag["kill_switch_engaged"], bool)
    assert 0 <= float(flag["current_exposure_pct"]) <= 100
    assert 0 <= flag["stale_debt_points"] <= STALE_DEBT_CAP
    assert "last_sweep_at" in flag
    assert "archived_at" in flag


def assert_rollout_step(step: Dict[str, Any]) -> None:
    assert_common_fields(step)
    for field in (
        "feature_flag_id",
        "step_index",
        "target_pct",
        "previous_exposure_pct",
        "soak_minutes",
        "state",
        "soak_started_at",
        "applied_at",
    ):
        assert field in step, f"rollout step missing '{field}': {step}"
    assert step["state"] in ("PLANNED", "SOAKING", "APPLIED", "ABORTED", "VOIDED")
    assert step["step_index"] >= 1
    assert "deployment_id" in step


def assert_deployment(deployment: Dict[str, Any]) -> None:
    assert_common_fields(deployment)
    for field in (
        "release_id",
        "environment_id",
        "window_start_at",
        "window_end_at",
        "strategy",
        "canary_pct",
        "min_sample_count",
        "abort_error_rate_pct",
        "abort_latency_p95_ms",
        "delivery_state",
        "verification_state",
    ):
        assert field in deployment, f"deployment missing '{field}': {deployment}"
    assert deployment["strategy"] in ("CANARY", "ALL_AT_ONCE", "BLUE_GREEN")
    assert deployment["delivery_state"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "CANARY_SOAK",
        "COMPLETED",
        "ABORTED",
        "ROLLED_BACK",
    )
    assert deployment["verification_state"] in (
        "PENDING",
        "PASSING",
        "FAILING",
        "INCONCLUSIVE",
        "WAIVED",
    )
    assert "completed_at" in deployment
    assert "rolled_back_at" in deployment
    assert deployment["window_end_at"] > deployment["window_start_at"]


def assert_incident(incident: Dict[str, Any]) -> None:
    assert_common_fields(incident)
    for field in (
        "release_train_id",
        "title",
        "severity",
        "detected_at",
        "reporter_user_id",
        "state",
        "decision",
        "decided_at",
        "linked_release_id",
        "linked_deployment_id",
    ):
        assert field in incident, f"incident missing '{field}': {incident}"
    assert incident["severity"] in ("SEV1", "SEV2", "SEV3", "SEV4")
    assert incident["state"] in ("OPEN", "DECIDED")
    if incident["decision"] is not None:
        assert incident["decision"] in ("ROLLBACK", "FORWARD_FIX", "NO_ACTION")


def assert_release_note_document(note: Dict[str, Any]) -> None:
    assert_common_fields(note)
    for field in (
        "release_id",
        "audience",
        "state",
        "generated_at",
        "published_at",
        "included_change_ids",
        "entry_count",
        "excluded_change_count",
    ):
        assert field in note, f"release notes missing '{field}': {note}"
    assert note["audience"] in ("CUSTOMER", "INTERNAL")
    assert note["state"] in ("DRAFT", "PUBLISHED")
    assert isinstance(note["included_change_ids"], list)
    assert note["entry_count"] == len(note["included_change_ids"])
    assert note["excluded_change_count"] >= 0


def assert_evidence_packet(packet: Dict[str, Any]) -> None:
    assert_common_fields(packet)
    for field in (
        "release_id",
        "state",
        "base_index",
        "waiver_credit_points",
        "completeness_index",
        "waiver_count",
        "waivers",
        "missing_items",
        "sealed_at",
        "sealed_by_user_id",
    ):
        assert field in packet, f"evidence packet missing '{field}': {packet}"
    assert packet["state"] in ("DRAFT", "SEALED", "SUPERSEDED")
    assert_point_scale(packet["base_index"])
    assert isinstance(packet["waivers"], list)
    assert packet["waiver_count"] == len(packet["waivers"])
    assert isinstance(packet["missing_items"], list)
    for code in packet["missing_items"]:
        assert code in EVIDENCE_ITEM_WEIGHTS, f"unknown evidence item code {code}"
    assert 0 <= float(packet["completeness_index"]) <= COMPLETENESS_INDEX_MAX


def assert_change_dependency(dependency: Dict[str, Any]) -> None:
    assert_append_only_common_fields(dependency)
    for field in ("from_change_id", "to_change_id"):
        assert field in dependency, f"dependency missing '{field}': {dependency}"


def assert_approval(approval: Dict[str, Any]) -> None:
    assert_append_only_common_fields(approval)
    for field in (
        "change_request_id",
        "kind",
        "decision",
        "approver_user_id",
        "pinned_risk_score",
        "pinned_change_version",
    ):
        assert field in approval, f"approval missing '{field}': {approval}"
    assert approval["kind"] in ("TECHNICAL", "COMPLIANCE", "CAB")
    assert approval["decision"] in ("APPROVE", "REJECT")


def assert_change_flag_link(link: Dict[str, Any]) -> None:
    assert_append_only_common_fields(link)
    for field in ("change_request_id", "feature_flag_id", "guard_kind"):
        assert field in link, f"flag link missing '{field}': {link}"
    assert link["guard_kind"] in ("GATES_ENTIRE_CHANGE", "PARTIAL")


def assert_canary_evaluation(evaluation: Dict[str, Any]) -> None:
    assert_append_only_common_fields(evaluation)
    for field in (
        "deployment_id",
        "window_start_at",
        "window_end_at",
        "sample_count",
        "error_rate_pct_rounded",
        "latency_p95_ms",
        "weighted_health_score",
        "verdict",
        "abort_triggered",
    ):
        assert field in evaluation, f"canary evaluation missing '{field}': {evaluation}"
    assert evaluation["verdict"] in ("PASS", "FAIL", "INCONCLUSIVE")
    assert isinstance(evaluation["abort_triggered"], bool)
    assert evaluation["sample_count"] >= 0


def assert_health_signal(signal: Dict[str, Any]) -> None:
    assert_append_only_common_fields(signal)
    for field in (
        "deployment_id",
        "observed_at",
        "cohort",
        "request_count",
        "error_count",
        "latency_p95_ms",
    ):
        assert field in signal, f"health signal missing '{field}': {signal}"
    assert signal["cohort"] in ("CANARY", "BASELINE")
    assert signal["request_count"] >= 1
    assert 0 <= signal["error_count"] <= signal["request_count"]
    assert signal["latency_p95_ms"] >= 0


# ---------------------------------------------------------------------------
# Numeric conventions (PRD §2.6)
# ---------------------------------------------------------------------------


def assert_point_scale(value: Any) -> None:
    """Integer point scales are whole numbers with a floor of 0 and a ceiling of 100."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"point scale must be an integer, got {value!r}"
    )
    assert 0 <= value <= 100, f"point scale out of range: {value}"


def round_half_up(value: float, places: int) -> float:
    """Round half away from zero, the convention PRD §2.6 pins for fractions."""
    factor = 10**places
    scaled = value * factor
    # Nudge to defeat binary representation error before flooring the .5 case up.
    return math.floor(scaled + 0.5 + 1e-9) / factor


def assert_rounded_to(value: Any, expected: float, places: int) -> None:
    assert abs(float(value) - expected) < 10 ** (-places) / 2, (
        f"expected {expected} at {places} decimal places, got {value}"
    )


# ---------------------------------------------------------------------------
# Risk scoring invariants (PRD §3.3)
# ---------------------------------------------------------------------------


def expected_risk_score(
    lines_changed: int,
    touched_subsystem_count: int,
    has_schema_migration: bool,
    declared_blast_radius: str,
    dependency_depth: int = 0,
    rollback_plan: Optional[str] = None,
    rollback_tested: bool = False,
    flag_guard_kind: Optional[str] = None,
) -> int:
    """Reproduce the pinned risk arithmetic: raw terms, then credits, then clamp."""
    size = min(
        math.ceil(lines_changed / 100) * SIZE_POINTS_PER_HUNDRED_LINES, SIZE_POINTS_CAP
    )
    spread = min(
        touched_subsystem_count * SPREAD_POINTS_PER_SUBSYSTEM, SPREAD_POINTS_CAP
    )
    migration = MIGRATION_POINTS if has_schema_migration else 0
    blast = BLAST_RADIUS_POINTS[declared_blast_radius]
    depth = min(
        dependency_depth * DEPENDENCY_POINTS_PER_DEPTH, DEPENDENCY_POINTS_CAP
    )
    raw = size + spread + migration + blast + depth

    if rollback_plan is not None and rollback_tested:
        rollback_credit = -10
    elif rollback_plan is not None:
        rollback_credit = -5
    else:
        rollback_credit = 0

    if flag_guard_kind == "GATES_ENTIRE_CHANGE":
        flag_credit = -15
    elif flag_guard_kind == "PARTIAL":
        flag_credit = -5
    else:
        flag_credit = 0

    credit = rollback_credit if abs(rollback_credit) >= abs(flag_credit) else flag_credit
    return max(RISK_SCORE_MIN, min(RISK_SCORE_MAX, raw + credit))


def expected_risk_class(score: int) -> str:
    if score >= RISK_TIER_CRITICAL_FLOOR:
        return RiskClass.CRITICAL
    if score >= RISK_TIER_HIGH_FLOOR:
        return RiskClass.HIGH
    if score >= RISK_TIER_MEDIUM_FLOOR:
        return RiskClass.MEDIUM
    return RiskClass.LOW


def assert_risk_classification(change: Dict[str, Any], expected_score: int) -> None:
    """The pinned preliminary score and the tier the PRD derives from it agree."""
    assert change["risk_score_preliminary"] == expected_score, (
        f"expected risk_score_preliminary {expected_score}, "
        f"got {change['risk_score_preliminary']}"
    )
    assert change["risk_class"] == expected_risk_class(expected_score), (
        f"score {expected_score} should classify as "
        f"{expected_risk_class(expected_score)}, got {change['risk_class']}"
    )


def assert_approval_counters(
    change: Dict[str, Any], technical: int, compliance: int, cab: int
) -> None:
    assert change["approval_technical_count"] == technical
    assert change["approval_compliance_count"] == compliance
    assert change["approval_cab_count"] == cab


# ---------------------------------------------------------------------------
# Release ledger invariants (PRD §3.2, §2.10)
# ---------------------------------------------------------------------------


def assert_release_ledger(
    release: Dict[str, Any],
    committed_change_count: int,
    risk_budget_consumed_points: int,
) -> None:
    assert release["committed_change_count"] == committed_change_count, (
        f"expected committed_change_count {committed_change_count}, "
        f"got {release['committed_change_count']}"
    )
    assert release["risk_budget_consumed_points"] == risk_budget_consumed_points, (
        f"expected risk_budget_consumed_points {risk_budget_consumed_points}, "
        f"got {release['risk_budget_consumed_points']}"
    )


def assert_readiness_variants(
    release: Dict[str, Any], projected: int, attested: Optional[int]
) -> None:
    assert release["readiness_score_projected"] == projected, (
        f"expected readiness_score_projected {projected}, "
        f"got {release['readiness_score_projected']}"
    )
    assert release["readiness_score_attested"] == attested, (
        f"expected readiness_score_attested {attested}, "
        f"got {release['readiness_score_attested']}"
    )


# ---------------------------------------------------------------------------
# Rollout ladder invariants (PRD §3.5)
# ---------------------------------------------------------------------------


def expected_ladder_ceiling(current_exposure_pct: float) -> float:
    """min(100, max(5, 3 x current exposure)) -- the highest admissible target."""
    return min(
        LADDER_MAX_PCT,
        max(LADDER_MIN_CEILING_PCT, LADDER_MULTIPLIER * float(current_exposure_pct)),
    )


def expected_required_soak_minutes(target_pct: float) -> int:
    if float(target_pct) > SOAK_BAND_MID_TARGET_PCT:
        return SOAK_MINUTES_HIGH
    if float(target_pct) > SOAK_BAND_LOW_TARGET_PCT:
        return SOAK_MINUTES_MID
    return SOAK_MINUTES_LOW


def assert_ladder_target_admissible(current_exposure_pct: float, target_pct: float):
    ceiling = expected_ladder_ceiling(current_exposure_pct)
    assert float(target_pct) > float(current_exposure_pct), (
        f"target {target_pct} must exceed current exposure {current_exposure_pct}"
    )
    assert float(target_pct) <= ceiling, (
        f"target {target_pct} exceeds ceiling {ceiling}"
    )


def assert_exposure_restored(flag: Dict[str, Any], expected_pct: float) -> None:
    assert float(flag["current_exposure_pct"]) == float(expected_pct), (
        f"expected current_exposure_pct restored to {expected_pct}, "
        f"got {flag['current_exposure_pct']}"
    )


# ---------------------------------------------------------------------------
# Staleness invariants (PRD §3.6)
# ---------------------------------------------------------------------------


def expected_cleanup_state_from_debt(debt: int) -> str:
    if debt >= CLEANUP_ENFORCED_FLOOR:
        return CleanupState.ENFORCED
    if debt >= CLEANUP_OVERDUE_FLOOR:
        return CleanupState.OVERDUE
    if debt > 0:
        return CleanupState.WARNING
    return CleanupState.COMPLIANT


def assert_stale_debt(flag: Dict[str, Any], debt: int, cleanup_state: str) -> None:
    assert flag["stale_debt_points"] == debt, (
        f"expected stale_debt_points {debt}, got {flag['stale_debt_points']}"
    )
    assert flag["cleanup_state"] == cleanup_state, (
        f"expected cleanup_state {cleanup_state}, got {flag['cleanup_state']}"
    )


def assert_sweep_summary(summary: Dict[str, Any], **expected: int) -> None:
    """Assert the named counters of the sweep summary object of PRD §3.6."""
    for field in (
        "evaluated_count",
        "warning_count",
        "overdue_count",
        "enforced_count",
        "paused_flag_count",
        "voided_step_count",
        "aborted_step_count",
    ):
        assert field in summary, f"sweep summary missing '{field}': {summary}"
    for field, value in expected.items():
        assert summary[field] == value, (
            f"expected sweep {field} {value}, got {summary[field]}"
        )


# ---------------------------------------------------------------------------
# Canary invariants (PRD §3.7)
# ---------------------------------------------------------------------------


def expected_weighted_error_rate(rows: List[Dict[str, int]]) -> float:
    """Per-row rate rounded half up to one place FIRST, then request-weighted mean."""
    sample_count = sum(row["request_count"] for row in rows)
    if sample_count == 0:
        return 0.0
    weighted_sum = 0.0
    for row in rows:
        per_row = round_half_up(
            row["error_count"] / row["request_count"] * 100.0, 1
        )
        weighted_sum += per_row * row["request_count"]
    return round_half_up(weighted_sum / sample_count, 2)


def expected_weighted_health_score(
    error_rate_pct_rounded: float,
    latency_p95_ms: float,
    abort_error_rate_pct: float,
    abort_latency_p95_ms: float,
) -> float:
    error_component = max(
        0.0,
        100.0
        - ERROR_COMPONENT_MULTIPLIER * (error_rate_pct_rounded / abort_error_rate_pct),
    )
    latency_component = max(
        0.0,
        100.0
        - LATENCY_COMPONENT_MULTIPLIER * (latency_p95_ms / abort_latency_p95_ms),
    )
    return round_half_up(
        ERROR_COMPONENT_WEIGHT * error_component
        + LATENCY_COMPONENT_WEIGHT * latency_component,
        2,
    )


def assert_canary_numbers(
    evaluation: Dict[str, Any],
    sample_count: int,
    error_rate_pct_rounded: float,
    latency_p95_ms: int,
    weighted_health_score: float,
    verdict: str,
    abort_triggered: bool,
) -> None:
    assert evaluation["sample_count"] == sample_count, (
        f"expected sample_count {sample_count}, got {evaluation['sample_count']}"
    )
    assert_rounded_to(evaluation["error_rate_pct_rounded"], error_rate_pct_rounded, 2)
    assert int(evaluation["latency_p95_ms"]) == latency_p95_ms, (
        f"expected latency_p95_ms {latency_p95_ms}, got {evaluation['latency_p95_ms']}"
    )
    assert_rounded_to(
        evaluation["weighted_health_score"], weighted_health_score, 2
    )
    assert evaluation["verdict"] == verdict, (
        f"expected verdict {verdict}, got {evaluation['verdict']}"
    )
    assert evaluation["abort_triggered"] is abort_triggered, (
        f"expected abort_triggered {abort_triggered}, "
        f"got {evaluation['abort_triggered']}"
    )
    if verdict == CanaryVerdict.INCONCLUSIVE:
        assert float(evaluation["error_rate_pct_rounded"]) == 0
        assert int(evaluation["latency_p95_ms"]) == 0
        assert float(evaluation["weighted_health_score"]) == 0


def assert_deployment_dimensions(
    deployment: Dict[str, Any], delivery_state: str, verification_state: str
) -> None:
    assert deployment["delivery_state"] == delivery_state, (
        f"expected delivery_state {delivery_state}, got {deployment['delivery_state']}"
    )
    assert deployment["verification_state"] == verification_state, (
        f"expected verification_state {verification_state}, "
        f"got {deployment['verification_state']}"
    )


# ---------------------------------------------------------------------------
# Evidence packet invariants (PRD §3.9)
# ---------------------------------------------------------------------------


def expected_waiver_cap(base_index: int) -> int:
    """The cap tier is keyed on ``base_index`` only, never on the running total."""
    for floor, cap in WAIVER_CAP_TIERS:
        if base_index >= floor:
            return cap
    return WAIVER_CAP_DEFAULT


def expected_completeness_index(base_index: int, waived_item_codes: List[str]) -> float:
    raw_credit = round_half_up(
        sum(EVIDENCE_ITEM_WEIGHTS[code] / 2 for code in waived_item_codes), 2
    )
    credit = min(raw_credit, expected_waiver_cap(base_index))
    return min(float(COMPLETENESS_INDEX_MAX), base_index + credit)


def assert_evidence_index(
    packet: Dict[str, Any],
    base_index: int,
    waiver_credit_points: float,
    completeness_index: float,
) -> None:
    assert packet["base_index"] == base_index, (
        f"expected base_index {base_index}, got {packet['base_index']}"
    )
    assert_rounded_to(packet["waiver_credit_points"], waiver_credit_points, 2)
    assert_rounded_to(packet["completeness_index"], completeness_index, 2)
    assert float(packet["waiver_credit_points"]) <= expected_waiver_cap(base_index), (
        "waiver credit must not exceed the cap tier selected from base_index"
    )


def assert_missing_items(packet: Dict[str, Any], expected_codes: List[str]) -> None:
    assert sorted(packet["missing_items"]) == sorted(expected_codes), (
        f"expected missing_items {sorted(expected_codes)}, "
        f"got {sorted(packet['missing_items'])}"
    )


# ---------------------------------------------------------------------------
# Envelope helper (PRD §2.2)
# ---------------------------------------------------------------------------


def assert_envelope_shape(body: Dict[str, Any], response_type: str) -> None:
    assert "meta" in body and "data" in body and "response_type" in body
    assert body["response_type"] == response_type
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
