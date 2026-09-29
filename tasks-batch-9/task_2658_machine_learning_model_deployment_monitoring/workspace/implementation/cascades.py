"""Recomputed ledgers, counters and the multi-hop cascades."""

from decimal import Decimal

import calc
import db
from db import dec, q2

OPEN_TRIGGER_STATES = ("PROPOSED", "ACKNOWLEDGED", "IN_PROGRESS")
SAMPLE_HOLDING_STATES = ("SCHEDULED", "COLLECTING", "PROMOTED")


# =========================================================================
# endpoint_traffic_ledger
# =========================================================================
def recompute_endpoint_ledger(endpoint):
    total = Decimal(0)
    for deployment in db.rows("deployments"):
        if (deployment["serving_endpoint_id"] == endpoint["id"]
                and deployment["rollout_state"] in calc.LEDGER_STATES):
            total += dec(deployment["traffic_pct"])
    endpoint["allocated_traffic_pct"] = q2(total)
    return endpoint["allocated_traffic_pct"]


# =========================================================================
# evaluation_sample_ledger
# =========================================================================
def recompute_sample_budget(version):
    if version is None:
        return None
    reserved = 0
    for evaluation in db.rows("challenger_evaluations"):
        if (evaluation["challenger_version_id"] == version["id"]
                and evaluation["status"] in SAMPLE_HOLDING_STATES):
            reserved += int(evaluation["reserved_samples"])
    version["evaluation_sample_budget"] = int(version["evaluation_sample_quota"]) - reserved
    return version["evaluation_sample_budget"]


# =========================================================================
# dataset_dependency_counter
# =========================================================================
def recompute_dependent_version_count(dataset):
    if dataset is None:
        return None
    count = 0
    for version in db.rows("model_versions"):
        if (version["training_dataset_id"] == dataset["id"]
                and version["approval_state"] != "REJECTED"):
            count += 1
    dataset["dependent_version_count"] = count
    return count


# =========================================================================
# open retraining trigger counter
# =========================================================================
def recompute_open_trigger_count(model):
    if model is None:
        return None
    count = 0
    for trigger in db.rows("retraining_triggers"):
        if (trigger["model_id"] == model["id"]
                and trigger["status"] in OPEN_TRIGGER_STATES):
            count += 1
    model["open_retraining_trigger_count"] = count
    return count


# =========================================================================
# ramp ledger rows
# =========================================================================
def append_ramp_step(deployment, from_pct, to_pct, delta_pct, reason,
                     step_index=None, health_state=None):
    row = db.insert("traffic_ramp_steps", {
        "deployment_id": deployment["id"],
        "step_index": deployment["ramp_step_index"] if step_index is None else step_index,
        "from_traffic_pct": q2(from_pct),
        "to_traffic_pct": q2(to_pct),
        "delta_pct": q2(delta_pct),
        "reason": reason,
        "health_state_at_step": health_state or deployment["health_state"],
        "clock_at_step": db.now(),
    }, common=False)
    recompute_cumulative(deployment)
    return row


def deployment_steps(deployment_id):
    return db.sorted_created([r for r in db.rows("traffic_ramp_steps")
                              if r["deployment_id"] == deployment_id])


def recompute_cumulative(deployment):
    total = Decimal(0)
    for row in deployment_steps(deployment["id"]):
        total += dec(row["delta_pct"])
    deployment["cumulative_ramp_delta_pct"] = q2(total)
    return deployment["cumulative_ramp_delta_pct"]


# =========================================================================
# lookups
# =========================================================================
def latest_skew_check(model_version_id=None, deployment_id=None):
    candidates = []
    for check in db.rows("skew_checks"):
        if model_version_id is not None and check["model_version_id"] != model_version_id:
            continue
        if deployment_id is not None and check["deployment_id"] != deployment_id:
            continue
        candidates.append(check)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["checked_at"], r["created_at"], r["_seq"]),
                    reverse=True)
    return candidates[0]


def deployment_incidents(deployment_id, statuses, exclude_id=None):
    out = []
    for incident in db.rows("prediction_incidents"):
        if incident["deployment_id"] != deployment_id:
            continue
        if exclude_id is not None and incident["id"] == exclude_id:
            continue
        if incident["status"] in statuses:
            out.append(incident)
    return out


def latest_performance_window(deployment_id):
    candidates = [w for w in db.rows("monitoring_windows")
                  if w["deployment_id"] == deployment_id
                  and w["window_kind"] == "PERFORMANCE"]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (r["window_end"], r["created_at"], r["_seq"]),
                    reverse=True)
    return candidates[0]


# =========================================================================
# challenger-evaluation drain hop
# =========================================================================
def end_collecting_evaluations(deployment, failure_key):
    affected = [e for e in db.rows("challenger_evaluations")
                if e["status"] == "COLLECTING"
                and (e["champion_deployment_id"] == deployment["id"]
                     or e["challenger_deployment_id"] == deployment["id"])]
    for evaluation in db.sorted_created(affected):
        evaluation["status"] = "INCONCLUSIVE"
        failures = list(evaluation.get("criteria_failures") or [])
        if failure_key not in failures:
            failures.append(failure_key)
        evaluation["criteria_failures"] = sorted(failures)
        db.touch(evaluation)
        challenger_version = db.get("model_versions", evaluation["challenger_version_id"])
        if challenger_version is not None:
            recompute_sample_budget(challenger_version)
            db.touch(challenger_version)


# =========================================================================
# deployment draining hop (snapshot revocation / revalidation failure)
# =========================================================================
def drain_deployments_for_version(version, failure_key):
    affected = [d for d in db.rows("deployments")
                if d["model_version_id"] == version["id"]
                and d["rollout_state"] in calc.SERVING_STATES]
    for deployment in db.sorted_created(affected):
        previous = dec(deployment["traffic_pct"])
        deployment["rollout_state"] = "DRAINING"
        deployment["traffic_pct"] = q2(0)
        append_ramp_step(deployment, previous, Decimal(0), -previous, "DRAIN_RELEASE")
        db.touch(deployment)
        endpoint = db.get("serving_endpoints", deployment["serving_endpoint_id"])
        if endpoint is not None:
            recompute_endpoint_ledger(endpoint)
            db.touch(endpoint)
        end_collecting_evaluations(deployment, failure_key)


def block_version(version, blocked_reason, clear_due_at=False):
    version["approval_state"] = "BLOCKED"
    version["blocked_reason"] = blocked_reason
    if clear_due_at:
        version["revalidation_due_at"] = None
    db.touch(version)
    drain_deployments_for_version(version, "DEPLOYMENT_DRAINED")


# =========================================================================
# retraining trigger raise (drift breach / failing skew check)
# =========================================================================
def raise_trigger(model, drift_report=None, skew_check=None):
    if drift_report is not None:
        evidence_version = db.get("model_versions", drift_report["model_version_id"])
    elif skew_check is not None:
        evidence_version = db.get("model_versions", skew_check["model_version_id"])
    else:
        evidence_version = None

    urgency = calc.retraining_urgency(drift_report, skew_check, evidence_version,
                                      db.now())
    trigger = db.insert("retraining_triggers", {
        "model_id": model["id"] if model is not None else None,
        "drift_report_id": drift_report["id"] if drift_report is not None else None,
        "skew_check_id": skew_check["id"] if skew_check is not None else None,
        "retrained_version_id": None,
        "base_urgency": urgency["base_urgency"],
        "escalation_tier_bonus_pct": urgency["escalation_tier_bonus_pct"],
        "total_urgency": urgency["total_urgency"],
        "priority_band": urgency["priority_band"],
        "retrain_required": urgency["retrain_required"],
        "status": "PROPOSED",
        "acknowledged_by_user_id": None,
        "dismissed_reason": None,
        "stale_after": urgency["stale_after"],
    })
    if model is not None:
        recompute_open_trigger_count(model)
        db.touch(model)
    return trigger


# =========================================================================
# drift breach cascade (up to five hops)
# =========================================================================
def drift_breach_cascade(report, deployment, severity):
    report["status"] = "BREACHED"

    version = db.get("model_versions", report["model_version_id"])
    model = db.get("models", version["model_id"]) if version is not None else None

    # hop 2 — the retraining trigger
    skew_check = latest_skew_check(deployment_id=deployment["id"]) if deployment else None
    raise_trigger(model, drift_report=report, skew_check=skew_check)

    if deployment is None:
        return

    mutated = False
    # hop 3 — the health dimension
    if severity == "WARN":
        if deployment["health_state"] == "HEALTHY":
            deployment["health_state"] = "DEGRADED"
            mutated = True
    else:
        if deployment["health_state"] in ("HEALTHY", "DEGRADED"):
            deployment["health_state"] = "CRITICAL"
            mutated = True

    if severity == "CRITICAL":
        # hop 4 — the automatic hold
        if deployment["rollout_state"] == "RAMPING":
            deployment["rollout_state"] = "HELD"
            mutated = True

    if mutated:
        db.touch(deployment)

    if severity == "CRITICAL":
        # hop 5 — the auto-raised incident
        db.insert("prediction_incidents", {
            "deployment_id": deployment["id"],
            "model_version_id": deployment["model_version_id"],
            "drift_report_id": report["id"],
            "source": "DRIFT",
            "severity": "SEV2",
            "summary": "AUTO: critical drift breach",
            "status": "OPEN",
            "fallback_engaged": False,
            "fallback_strategy_used": None,
            "manual_override_traffic_pct": None,
            "recurrence_count": 0,
            "opened_at": db.now(),
            "resolved_at": None,
        })


# =========================================================================
# snapshot revocation cascade (four hops)
# =========================================================================
def revoke_cascade(dataset):
    affected = [v for v in db.rows("model_versions")
                if v["training_dataset_id"] == dataset["id"]
                and v["approval_state"] == "APPROVED"]
    for version in db.sorted_created(affected):
        block_version(version, "TRAINING_DATA_REVOKED")
    recompute_dependent_version_count(dataset)


# =========================================================================
# revalidation failure cascade (four hops)
# =========================================================================
def revalidation_fail_cascade(version):
    if version is not None and version["approval_state"] == "APPROVED":
        block_version(version, "REVALIDATION_FAILED", clear_due_at=True)


# =========================================================================
# revalidation schedule
# =========================================================================
def revalidation_due(model, anchor):
    interval = int(model["revalidation_interval_days"]) if model else 90
    return db.add_days(anchor, interval)
