"""Request payload factories.

Each factory returns a valid minimal-plus-defaults body for one create or
transition endpoint, with ``**overrides`` for the field a test wants to vary.
Optional inputs are omitted unless supplied, so that tests asserting PRD default
values can rely on the factory not silently sending the default explicitly.
"""

from typing import Any, Dict, Optional

from .constants import (
    CANARY_ABORT_ERROR_RATE_PCT,
    CANARY_ABORT_LATENCY_P95_MS,
    CANARY_MIN_SAMPLE_COUNT,
    CANARY_PCT,
    FLAG_EXPIRES_AT,
    RELEASE_CUT_AT,
    RELEASE_VERSION_LABEL,
    TRAIN_CADENCE_DAYS,
    TRAIN_CODE_FREEZE_LEAD_HOURS,
    TRAIN_NAME,
    TRAIN_RISK_BUDGET_POINTS,
    TRAIN_STABILIZATION_HOURS,
)
from .test_users import ENGINEER_USER_ID
from .types import (
    ApprovalDecision,
    ApprovalKind,
    DeclaredBlastRadius,
    Cohort,
    DeployStrategy,
    EnvironmentTier,
    FlagLinkGuardKind,
    IncidentSeverity,
    NoteAudience,
    TrainFreezeAction,
)


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel ``...`` (meaning "omit")."""
    return {k: v for k, v in payload.items() if v is not ...}


# ---------------------------------------------------------------------------
# Release trains (PRD §3.1)
# ---------------------------------------------------------------------------


def make_release_train_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": TRAIN_NAME,
        "cadence_days": TRAIN_CADENCE_DAYS,
        "code_freeze_lead_hours": TRAIN_CODE_FREEZE_LEAD_HOURS,
        "stabilization_hours": TRAIN_STABILIZATION_HOURS,
        "risk_budget_points": TRAIN_RISK_BUDGET_POINTS,
    }
    payload.update(overrides)
    return _clean(payload)


def make_freeze_state_payload(action: str = TrainFreezeAction.FREEZE, **overrides: Any):
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Environments (PRD §3.7)
# ---------------------------------------------------------------------------


def make_environment_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": "prod-us",
        "tier": EnvironmentTier.PROD,
        "deploy_window_start_hour_utc": 2,
        "deploy_window_end_hour_utc": 6,
    }
    payload.update(overrides)
    return _clean(payload)


def make_staging_environment_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": "staging-eu",
        "tier": EnvironmentTier.STAGING,
        "deploy_window_start_hour_utc": 0,
        "deploy_window_end_hour_utc": 24,
        "cooldown_minutes": 0,
    }
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Releases (PRD §3.2)
# ---------------------------------------------------------------------------


def make_release_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "version_label": RELEASE_VERSION_LABEL,
        "cut_at": RELEASE_CUT_AT,
    }
    payload.update(overrides)
    return _clean(payload)


def make_cut_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return _clean(payload)


def make_freeze_exception_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"justification": "audit-approved hotfix window"}
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Change requests (PRD §3.3)
# ---------------------------------------------------------------------------


def make_change_request_payload(**overrides: Any) -> Dict[str, Any]:
    """A MEDIUM-tier change by default: 100 lines, 2 subsystems, no migration."""
    payload = {
        "title": "Refactor checkout pipeline",
        "summary_internal": "Rework the checkout pipeline internals.",
        "lines_changed": 100,
        "touched_subsystem_count": 2,
        "has_schema_migration": False,
        "declared_blast_radius": DeclaredBlastRadius.INTERNAL,
    }
    payload.update(overrides)
    return _clean(payload)


def make_low_risk_change_payload(**overrides: Any) -> Dict[str, Any]:
    """Scores below 25 and therefore auto-approves on submit."""
    payload = {
        "title": "Fix copy typo",
        "summary_internal": "Correct a typo in the confirmation screen.",
        "lines_changed": 40,
        "touched_subsystem_count": 1,
        "has_schema_migration": False,
        "declared_blast_radius": DeclaredBlastRadius.INTERNAL,
    }
    payload.update(overrides)
    return _clean(payload)


def make_high_risk_change_payload(**overrides: Any) -> Dict[str, Any]:
    """Scores in the HIGH band: 250 lines, 3 subsystems, migration, single tenant."""
    payload = {
        "title": "Split orders table",
        "summary_internal": "Partition the orders table and backfill.",
        "lines_changed": 250,
        "touched_subsystem_count": 3,
        "has_schema_migration": True,
        "declared_blast_radius": DeclaredBlastRadius.SINGLE_TENANT,
    }
    payload.update(overrides)
    return _clean(payload)


def make_critical_risk_change_payload(**overrides: Any) -> Dict[str, Any]:
    """Scores at or above 70 and therefore routes to CAB_REVIEW."""
    payload = {
        "title": "Global tenancy migration",
        "summary_internal": "Move every tenant onto the shared schema.",
        "lines_changed": 700,
        "touched_subsystem_count": 6,
        "has_schema_migration": True,
        "declared_blast_radius": DeclaredBlastRadius.GLOBAL,
        "rollback_plan": "restore snapshot",
        "rollback_tested": True,
    }
    payload.update(overrides)
    return _clean(payload)


def make_dependency_payload(to_change_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_change_id": to_change_id}
    payload.update(overrides)
    return _clean(payload)


def make_flag_link_payload(
    feature_flag_id: str,
    guard_kind: str = FlagLinkGuardKind.PARTIAL,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "feature_flag_id": feature_flag_id,
        "guard_kind": guard_kind,
    }
    payload.update(overrides)
    return _clean(payload)


def make_approval_payload(
    kind: str = ApprovalKind.TECHNICAL,
    decision: str = ApprovalDecision.APPROVE,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"kind": kind, "decision": decision}
    payload.update(overrides)
    return _clean(payload)


def make_withdraw_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Feature flags and rollout steps (PRD §3.5)
# ---------------------------------------------------------------------------


def make_feature_flag_payload(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "key": "checkout-v2",
        "owner_user_id": ENGINEER_USER_ID,
        "expires_at": FLAG_EXPIRES_AT,
    }
    payload.update(overrides)
    return _clean(payload)


def make_rollout_step_payload(
    expected_feature_flag_version: int,
    target_pct: float = 5,
    soak_minutes: int = 30,
    deployment_id: Optional[str] = ...,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "target_pct": target_pct,
        "soak_minutes": soak_minutes,
        "expected_feature_flag_version": expected_feature_flag_version,
        "deployment_id": deployment_id,
    }
    payload.update(overrides)
    return _clean(payload)


def make_pause_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Deployments, health samples and canary analysis (PRD §3.7)
# ---------------------------------------------------------------------------


def make_deployment_payload(
    environment_id: str,
    window_start_at: str = "2026-08-11T02:00:00Z",
    window_end_at: str = "2026-08-11T04:00:00Z",
    strategy: str = DeployStrategy.ALL_AT_ONCE,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "environment_id": environment_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "strategy": strategy,
        "abort_error_rate_pct": CANARY_ABORT_ERROR_RATE_PCT,
        "abort_latency_p95_ms": CANARY_ABORT_LATENCY_P95_MS,
    }
    payload.update(overrides)
    return _clean(payload)


def make_canary_deployment_payload(
    environment_id: str,
    window_start_at: str = "2026-08-11T02:00:00Z",
    window_end_at: str = "2026-08-11T04:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "environment_id": environment_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "strategy": DeployStrategy.CANARY,
        "abort_error_rate_pct": CANARY_ABORT_ERROR_RATE_PCT,
        "abort_latency_p95_ms": CANARY_ABORT_LATENCY_P95_MS,
        "canary_pct": CANARY_PCT,
        "min_sample_count": CANARY_MIN_SAMPLE_COUNT,
    }
    payload.update(overrides)
    return _clean(payload)


def make_health_signal_payload(
    observed_at: str,
    request_count: int,
    error_count: int,
    latency_p95_ms: int,
    cohort: str = Cohort.CANARY,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "observed_at": observed_at,
        "cohort": cohort,
        "request_count": request_count,
        "error_count": error_count,
        "latency_p95_ms": latency_p95_ms,
    }
    payload.update(overrides)
    return _clean(payload)


def make_canary_evaluation_payload(
    window_start_at: str, window_end_at: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    payload.update(overrides)
    return _clean(payload)


def make_complete_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Incidents (PRD §3.8)
# ---------------------------------------------------------------------------


def make_incident_payload(
    release_train_id: str,
    detected_at: str,
    severity: str = IncidentSeverity.SEV1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title": "Checkout error spike",
        "severity": severity,
        "detected_at": detected_at,
        "release_train_id": release_train_id,
    }
    payload.update(overrides)
    return _clean(payload)


def make_incident_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return _clean(payload)


# ---------------------------------------------------------------------------
# Release notes and evidence packets (PRD §3.9)
# ---------------------------------------------------------------------------


def make_release_notes_payload(
    audience: str = NoteAudience.CUSTOMER, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"audience": audience}
    payload.update(overrides)
    return _clean(payload)


def make_evidence_packet_payload(
    expected_release_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_release_version": expected_release_version}
    payload.update(overrides)
    return _clean(payload)


def make_waiver_payload(item_code: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "item_code": item_code,
        "justification": "documented gap accepted by compliance",
    }
    payload.update(overrides)
    return _clean(payload)
