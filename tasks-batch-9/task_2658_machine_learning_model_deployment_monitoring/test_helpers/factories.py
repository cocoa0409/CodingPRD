"""Request-payload builders.

Every builder returns a fresh, complete, PRD-valid payload and accepts keyword
overrides so a test can vary exactly one field. Numeric fields are emitted as
JSON numbers, never as strings: the service reads `row_count` as an integer and
`max_traffic_pct` as a two-decimal number, so a quoted value would be a shape
violation rather than a legitimate input.

`build_*` helpers that need an identifier take it positionally; anything the
PRD declares optional is omitted unless a caller asks for it, so the
"omitted optional inputs apply declared defaults" behaviour is exercisable by
simply not passing the keyword.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    FEATURE_HASH_V1,
    FLAT_BIN_PROPORTIONS,
)

# Monotonic suffix so repeated calls inside one test never collide on a
# uniqueness constraint by accident.
_counter = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_counter):04d}"


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of ``OMIT`` removes the key entirely."""
    for key, value in overrides.items():
        if value is OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel meaning "leave this key out of the payload entirely"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


OMIT = _Omit()


# ─── Registry entries (PRD §3.1) ───


def build_model_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"fraud-scorer-{unique_suffix()}",
        "task_type": "CLASSIFICATION",
        "owner_team": "risk-ml",
        "revalidation_interval_days": 90,
    }
    return _apply(payload, overrides)


# ─── Training-data snapshots (PRD §3.2) ───


def build_training_dataset_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"snap-2026-07-{unique_suffix()}",
        "snapshot_uri": "s3://snaps/2026-07",
        "row_count": 1000000,
        "feature_hash": FEATURE_HASH_V1,
        "baseline_bin_proportions": list(FLAT_BIN_PROPORTIONS),
        "baseline_positive_rate": 0.30,
        "license_class": "INTERNAL",
        "pii_review_passed": True,
    }
    return _apply(payload, overrides)


def build_dataset_decision_payload(
    decision: str = "APPROVE", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    return _apply(payload, overrides)


def build_revocation_payload(
    reason: str = "Licence withdrawn by the data provider", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"revocation_reason": reason}
    return _apply(payload, overrides)


# ─── Artifact versions (PRD §3.3) ───

FULL_DOC_SECTIONS = [
    "INTENDED_USE",
    "TRAINING_DATA",
    "EVALUATION",
    "LIMITATIONS",
]
FULL_REPRO_ARTIFACTS = [
    "TRAINING_CODE_COMMIT",
    "ENV_LOCKFILE_DIGEST",
    "RANDOM_SEED",
    "FEATURE_SPEC_HASH",
]


def build_model_version_payload(
    model_id: str, training_dataset_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model_id": model_id,
        "training_dataset_id": training_dataset_id,
        "semver": "1.0.0",
        "artifact_digest": "sha256:aaa",
        "feature_spec_hash": FEATURE_HASH_V1,
        "baseline_accuracy": 0.82,
        "baseline_positive_rate": 0.30,
        "baseline_p95_latency_ms": 200,
        "doc_sections": list(FULL_DOC_SECTIONS),
        "repro_artifacts": list(FULL_REPRO_ARTIFACTS),
        "evaluation_sample_quota": 5000,
    }
    return _apply(payload, overrides)


def build_documentation_payload(
    doc_sections: Optional[List[str]] = None,
    repro_artifacts: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "doc_sections": list(FULL_DOC_SECTIONS)
        if doc_sections is None
        else list(doc_sections),
        "repro_artifacts": list(FULL_REPRO_ARTIFACTS)
        if repro_artifacts is None
        else list(repro_artifacts),
    }
    return _apply(payload, overrides)


def build_version_decision_payload(
    decision: str = "APPROVE", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    return _apply(payload, overrides)


# ─── Serving clusters (PRD §3.4) ───


def build_serving_endpoint_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"rt-cluster-{unique_suffix()}",
        "region": "us-east-1",
        "serving_feature_spec_hash": FEATURE_HASH_V1,
        "max_traffic_pct": 100.00,
        "deploy_cooldown_minutes": 30,
    }
    return _apply(payload, overrides)


def build_operational_state_payload(
    operational_state: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"operational_state": operational_state}
    return _apply(payload, overrides)


# ─── Deployments (PRD §3.4) ───


def build_deployment_payload(
    model_version_id: str,
    serving_endpoint_id: str,
    expected_serving_endpoint_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model_version_id": model_version_id,
        "serving_endpoint_id": serving_endpoint_id,
        "pattern": "REALTIME",
        "serve_from": "2026-08-01T00:00:00Z",
        "serve_until": "2026-08-31T00:00:00Z",
        "expected_serving_endpoint_version": expected_serving_endpoint_version,
        "fallback_strategy": "PREVIOUS_CHAMPION",
    }
    return _apply(payload, overrides)


def build_rollout_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    return _apply(payload, overrides)


# ─── Observation windows (PRD §3.5) ───


def build_monitoring_window_payload(
    deployment_id: str, model_version_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "deployment_id": deployment_id,
        "model_version_id": model_version_id,
        "window_kind": "PERFORMANCE",
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-02T00:00:00Z",
        "prediction_count": 10000,
        "labeled_prediction_count": 2000,
        "correct_labeled_count": 1700,
        "positive_rate": 0.32,
        "p95_latency_ms": 240,
        "observed_bin_proportions": [0.10, 0.15, 0.20, 0.25, 0.30],
    }
    return _apply(payload, overrides)


# ─── Drift reports (PRD §3.6) ───


def build_drift_report_payload(
    monitoring_window_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "monitoring_window_id": monitoring_window_id,
        "drift_kind": "DATA_DRIFT",
        "baseline_mode": "TRAINING_BASELINE",
    }
    return _apply(payload, overrides)


# ─── Skew checks (PRD §3.6) ───


def build_skew_check_payload(
    model_version_id: str,
    deployment_id: str,
    training_feature_stats: Optional[Dict[str, Any]] = None,
    serving_feature_stats: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model_version_id": model_version_id,
        "deployment_id": deployment_id,
        "training_feature_stats": {
            "amount": {"mean": 0.8000},
            "tenure_days": {"mean": 30.0000},
            "zscore": {"mean": 1.0000},
        }
        if training_feature_stats is None
        else training_feature_stats,
        "serving_feature_stats": {
            "amount": {"mean": 0.8000},
            "tenure_days": {"mean": 30.0000},
            "zscore": {"mean": 1.0000},
        }
        if serving_feature_stats is None
        else serving_feature_stats,
    }
    return _apply(payload, overrides)


# ─── Retraining triggers (PRD §3.6) ───


def build_trigger_disposition_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    return _apply(payload, overrides)


# ─── Champion-challenger evaluations (PRD §3.7) ───

CHAMPION_METRICS = {
    "ACCURACY_PROXY": 0.8200,
    "CALIBRATION": 0.9100,
    "LATENCY": 180.0,
    "COST": 0.00420,
}
CHALLENGER_METRICS = {
    "ACCURACY_PROXY": 0.8570,
    "CALIBRATION": 0.9230,
    "LATENCY": 171.0,
    "COST": 0.00390,
}


def build_evaluation_payload(
    champion_deployment_id: str,
    challenger_deployment_id: str,
    expected_model_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "champion_deployment_id": champion_deployment_id,
        "challenger_deployment_id": challenger_deployment_id,
        "reserved_samples": 1000,
        "evaluation_ends_at": "2026-08-15T00:00:00Z",
        "champion_metrics": dict(CHAMPION_METRICS),
        "challenger_metrics": dict(CHALLENGER_METRICS),
        "expected_model_version": expected_model_version,
    }
    return _apply(payload, overrides)


def build_conclude_payload(
    labeled_prediction_count: int = 1000, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "labeled_prediction_count": labeled_prediction_count
    }
    return _apply(payload, overrides)


# ─── Prediction incidents (PRD §3.8) ───


def build_incident_payload(deployment_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "deployment_id": deployment_id,
        "summary": "Latency spike on the realtime path",
    }
    return _apply(payload, overrides)


def build_incident_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    return _apply(payload, overrides)


# ─── Periodic revalidation (PRD §3.9) ───


def build_revalidation_disposition_payload(
    action: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    return _apply(payload, overrides)


# ─── Logical clock (PRD §3.9) ───


def build_clock_payload(current_utc: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"current_utc": current_utc}
    return _apply(payload, overrides)


# ─── Distribution helpers ───


def bins_summing_to(values: List[float]) -> List[float]:
    """Return the list unchanged; named so intent is legible at call sites."""
    return list(values)
