"""Observation windows, drift reports, skew checks and retraining triggers."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import db
import middleware as mw
import response
from db import dec, q2, q4
from errors import ApiError
from middleware import ALL_ROLES, MLE, PA, RE
from routes.registry import body_fk, need, require_present

bp = Blueprint("monitoring", __name__)

WINDOW_KINDS = ("PERFORMANCE", "DISTRIBUTION", "LATENCY")
DRIFT_KINDS = ("DATA_DRIFT", "CONCEPT_DRIFT")
BASELINE_MODES = ("TRAINING_BASELINE", "ROLLING_BASELINE")
TRIGGER_TERMINAL = ("SATISFIED", "DISMISSED", "STALE")
ROLLING_WINDOW_LIMIT = 3


# =========================================================================
# Observation windows
# =========================================================================
@bp.post("/monitoring-windows")
def create_window():
    mw.auth(MLE, RE)
    payload = mw.body()

    deployment = body_fk(payload, "deployment_id", "deployments",
                         "ERR_DEPLOYMENT_NOT_FOUND")
    version = body_fk(payload, "model_version_id", "model_versions",
                      "ERR_MODEL_VERSION_NOT_FOUND")

    require_present(payload, "deployment_id", "model_version_id", "window_kind",
                    "window_start", "window_end", "prediction_count",
                    "labeled_prediction_count", "correct_labeled_count",
                    "positive_rate", "p95_latency_ms", "observed_bin_proportions")
    mw.vstr(payload, "deployment_id")
    mw.vstr(payload, "model_version_id")

    # specialised shape codes take precedence over ERR_INVALID_REQUEST
    bins = mw.bin_proportions(payload, "observed_bin_proportions")
    prediction_count = mw.vint(payload, "prediction_count", minimum=0)
    labeled = mw.vint(payload, "labeled_prediction_count", minimum=0)
    correct = mw.vint(payload, "correct_labeled_count", minimum=0)
    if labeled > prediction_count or correct > labeled:
        raise ApiError("ERR_LABEL_COUNT_INCONSISTENT")

    window_kind = mw.venum(payload, "window_kind", WINDOW_KINDS)
    window_start = mw.vdt(payload, "window_start")
    window_end = mw.vdt(payload, "window_end")
    positive_rate = mw.vnum(payload, "positive_rate", minimum=0, maximum=1)
    p95 = mw.vint(payload, "p95_latency_ms", minimum=1)

    if window_end <= window_start:
        raise ApiError("ERR_INVALID_INTERVAL")

    if deployment["model_version_id"] != version["id"]:
        raise ApiError("ERR_WINDOW_VERSION_MISMATCH")

    siblings = [w for w in db.rows("monitoring_windows")
                if w["deployment_id"] == deployment["id"]
                and w["window_kind"] == window_kind]
    for other in siblings:
        if other["status"] == "OPEN":
            raise ApiError("ERR_DUPLICATE_OPEN_WINDOW")
    for other in siblings:
        if (window_start <= other["window_end"]
                and other["window_start"] <= window_end):
            raise ApiError("ERR_MONITORING_WINDOW_OVERLAP")

    if deployment["rollout_state"] not in calc.SERVING_STATES:
        raise ApiError("ERR_DEPLOYMENT_NOT_SERVING")

    row = db.insert("monitoring_windows", {
        "deployment_id": deployment["id"],
        "model_version_id": version["id"],
        "window_kind": window_kind,
        "window_start": window_start,
        "window_end": window_end,
        "prediction_count": prediction_count,
        "labeled_prediction_count": labeled,
        "correct_labeled_count": correct,
        "positive_rate": positive_rate,
        "p95_latency_ms": p95,
        "observed_bin_proportions": bins,
        "status": "OPEN",
        "health_score": None,
        "health_score_variant": "PROVISIONAL",
        "baseline_delta_pct": None,
        "closed_at": None,
    })
    score, delta = calc.health_score(row, version, "PROVISIONAL")
    row["health_score"] = score
    row["baseline_delta_pct"] = delta

    deployment["health_score_provisional"] = score
    db.touch(deployment)
    return response.created(db.public(row))


@bp.get("/monitoring-windows/<window_id>")
def get_window(window_id):
    mw.auth(*ALL_ROLES)
    row = need("monitoring_windows", window_id, "ERR_MONITORING_WINDOW_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/monitoring-windows")
def list_windows():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("monitoring_windows"), {
        "deployment_id": ("deployment_id", "str"),
        "model_version_id": ("model_version_id", "str"),
        "window_kind": ("window_kind", "str"),
        "status": ("status", "str"),
    })
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


@bp.post("/monitoring-windows/<window_id>/close")
def close_window(window_id):
    mw.auth(MLE, RE)
    row = need("monitoring_windows", window_id, "ERR_MONITORING_WINDOW_NOT_FOUND")
    if row["status"] == "CLOSED":
        raise ApiError("ERR_TERMINAL_STATE")
    if row["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    if row["window_end"] > db.now():
        raise ApiError("ERR_WINDOW_NOT_ENDED")

    version = db.get("model_versions", row["model_version_id"])
    score, delta = calc.health_score(row, version, "FINAL")
    row["status"] = "CLOSED"
    row["closed_at"] = db.now()
    row["health_score_variant"] = "FINAL"
    row["health_score"] = score
    row["baseline_delta_pct"] = delta
    db.touch(row)

    deployment = db.get("deployments", row["deployment_id"])
    if deployment is not None:
        if row["window_kind"] == "PERFORMANCE":
            deployment["health_score_final"] = score
            if (deployment["health_state"] == "DEGRADED"
                    and score >= calc.HEALTH_RECOVERY_MIN):
                deployment["health_state"] = "HEALTHY"
        db.touch(deployment)
    return response.ok(db.public(row))


# =========================================================================
# Drift reports
# =========================================================================
def _expected_bins(window, baseline_mode, version):
    """Returns (expected_bins, baseline_dataset_id, effective_mode, used_count)."""
    dataset_id = version["training_dataset_id"] if version is not None else None

    if baseline_mode == "ROLLING_BASELINE":
        pool = [w for w in db.rows("monitoring_windows")
                if w["deployment_id"] == window["deployment_id"]
                and w["window_kind"] == "DISTRIBUTION"
                and w["status"] == "CLOSED"
                and w["id"] != window["id"]]
        pool.sort(key=lambda r: (r["window_end"], r["created_at"], r["_seq"]),
                  reverse=True)
        taken = pool[:ROLLING_WINDOW_LIMIT]
        if taken:
            expected = []
            for index in range(5):
                total = Decimal(0)
                for candidate in taken:
                    total += dec(candidate["observed_bin_proportions"][index])
                expected.append(q4(total / Decimal(len(taken))))
            return expected, None, "ROLLING_BASELINE", len(taken)

    dataset = db.get("training_datasets", dataset_id) if dataset_id else None
    raw = list(dataset["baseline_bin_proportions"]) if dataset is not None else [
        Decimal("0.2")] * 5
    return [q4(dec(v)) for v in raw], dataset_id, "TRAINING_BASELINE", 0


@bp.post("/drift-reports")
def create_drift_report():
    mw.auth(MLE, RE)
    payload = mw.body()

    window = body_fk(payload, "monitoring_window_id", "monitoring_windows",
                     "ERR_MONITORING_WINDOW_NOT_FOUND")
    require_present(payload, "monitoring_window_id", "drift_kind", "baseline_mode")
    mw.vstr(payload, "monitoring_window_id")
    drift_kind = mw.venum(payload, "drift_kind", DRIFT_KINDS)
    baseline_mode = mw.venum(payload, "baseline_mode", BASELINE_MODES)

    if window["status"] != "CLOSED":
        raise ApiError("ERR_WINDOW_NOT_CLOSED")

    version = db.get("model_versions", window["model_version_id"])
    expected, dataset_id, effective, used = _expected_bins(window, baseline_mode,
                                                            version)
    index = calc.drift_index(window["observed_bin_proportions"], expected)
    severity = calc.drift_severity(index)

    row = db.insert("drift_reports", {
        "monitoring_window_id": window["id"],
        "model_version_id": window["model_version_id"],
        "baseline_dataset_id": dataset_id,
        "drift_kind": drift_kind,
        "baseline_mode": baseline_mode,
        "effective_baseline_mode": effective,
        "expected_bin_proportions": expected,
        "windows_used_count": used,
        "drift_index": index,
        "severity": severity,
        "status": "COMPUTED",
    })

    if severity != "NONE":
        deployment = db.get("deployments", window["deployment_id"])
        cascades.drift_breach_cascade(row, deployment, severity)
    return response.created(db.public(row))


@bp.get("/drift-reports/<drift_report_id>")
def get_drift_report(drift_report_id):
    mw.auth(*ALL_ROLES)
    row = need("drift_reports", drift_report_id, "ERR_DRIFT_REPORT_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/drift-reports")
def list_drift_reports():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("drift_reports"), {
        "monitoring_window_id": ("monitoring_window_id", "str"),
        "model_version_id": ("model_version_id", "str"),
        "baseline_dataset_id": ("baseline_dataset_id", "str"),
        "drift_kind": ("drift_kind", "str"),
        "severity": ("severity", "str"),
        "status": ("status", "str"),
    })
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


# =========================================================================
# Skew checks
# =========================================================================
def _feature_stats(payload, field, require_non_empty):
    if not mw.present(payload, field):
        raise ApiError("ERR_INVALID_FEATURE_STATS")
    value = payload[field]
    if not isinstance(value, dict):
        raise ApiError("ERR_INVALID_FEATURE_STATS")
    if require_non_empty and not value:
        raise ApiError("ERR_INVALID_FEATURE_STATS")
    for entry in value.values():
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_FEATURE_STATS")
        mean = entry.get("mean")
        if isinstance(mean, bool) or not isinstance(mean, (int, float)):
            raise ApiError("ERR_INVALID_FEATURE_STATS")
    return value


@bp.post("/skew-checks")
def create_skew_check():
    mw.auth(MLE, RE)
    payload = mw.body()

    version = body_fk(payload, "model_version_id", "model_versions",
                      "ERR_MODEL_VERSION_NOT_FOUND")
    deployment = body_fk(payload, "deployment_id", "deployments",
                         "ERR_DEPLOYMENT_NOT_FOUND")
    require_present(payload, "model_version_id", "deployment_id")
    mw.vstr(payload, "model_version_id")
    mw.vstr(payload, "deployment_id")
    training_stats = _feature_stats(payload, "training_feature_stats", True)
    serving_stats = _feature_stats(payload, "serving_feature_stats", False)

    if deployment["model_version_id"] != version["id"]:
        raise ApiError("ERR_SKEW_DEPLOYMENT_MISMATCH")
    if deployment["rollout_state"] not in calc.SERVING_STATES:
        raise ApiError("ERR_DEPLOYMENT_NOT_SERVING")

    max_ratio, max_feature, missing, status = calc.skew_evaluation(training_stats,
                                                                   serving_stats)
    row = db.insert("skew_checks", {
        "model_version_id": version["id"],
        "deployment_id": deployment["id"],
        "training_dataset_id": version["training_dataset_id"],
        "training_feature_stats": training_stats,
        "serving_feature_stats": serving_stats,
        "max_skew_ratio": max_ratio,
        "max_skew_feature": max_feature,
        "missing_features": missing,
        "status": status,
        "checked_at": db.now(),
    })

    if status in calc.FAILED_SKEW_STATES:
        model = db.get("models", version["model_id"])
        cascades.raise_trigger(model, drift_report=None, skew_check=row)
    return response.created(db.public(row))


@bp.get("/skew-checks/<skew_check_id>")
def get_skew_check(skew_check_id):
    mw.auth(*ALL_ROLES)
    row = need("skew_checks", skew_check_id, "ERR_SKEW_CHECK_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/skew-checks")
def list_skew_checks():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("skew_checks"), {
        "model_version_id": ("model_version_id", "str"),
        "deployment_id": ("deployment_id", "str"),
        "training_dataset_id": ("training_dataset_id", "str"),
        "status": ("status", "str"),
    })
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


# =========================================================================
# Retraining triggers
# =========================================================================
@bp.get("/retraining-triggers/<retraining_trigger_id>")
def get_trigger(retraining_trigger_id):
    mw.auth(*ALL_ROLES)
    row = need("retraining_triggers", retraining_trigger_id,
               "ERR_RETRAINING_TRIGGER_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/retraining-triggers")
def list_triggers():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("retraining_triggers"), {
        "model_id": ("model_id", "str"),
        "drift_report_id": ("drift_report_id", "str"),
        "skew_check_id": ("skew_check_id", "str"),
        "retrained_version_id": ("retrained_version_id", "str"),
        "status": ("status", "str"),
        "priority_band": ("priority_band", "str"),
    })
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


def _lineage_anchor(trigger):
    """The version a retrained artifact must descend from."""
    report = db.get("drift_reports", trigger["drift_report_id"]) \
        if trigger["drift_report_id"] else None
    if report is not None:
        return report["model_version_id"]
    check = db.get("skew_checks", trigger["skew_check_id"]) \
        if trigger["skew_check_id"] else None
    if check is not None:
        return check["model_version_id"]
    return None


@bp.post("/retraining-triggers/<retraining_trigger_id>/disposition")
def dispose_trigger(retraining_trigger_id):
    user_id, _ = mw.auth(MLE, PA)
    trigger = need("retraining_triggers", retraining_trigger_id,
                   "ERR_RETRAINING_TRIGGER_NOT_FOUND")
    payload = mw.body()

    linked = body_fk(payload, "retrained_version_id", "model_versions",
                     "ERR_MODEL_VERSION_NOT_FOUND")
    require_present(payload, "action")
    action = mw.venum(payload, "action",
                      ("ACKNOWLEDGE", "DISMISS", "LINK_VERSION"))
    dismissed_reason = mw.vstr(payload, "dismissed_reason", required=False,
                               minlen=1, maxlen=500)
    if mw.present(payload, "retrained_version_id"):
        mw.vstr(payload, "retrained_version_id")
    if action == "DISMISS" and dismissed_reason is None:
        mw.bad("dismissed_reason is required")
    if action == "LINK_VERSION" and linked is None:
        mw.bad("retrained_version_id is required")

    if trigger["status"] in TRIGGER_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")
    allowed = {
        "ACKNOWLEDGE": ("PROPOSED",),
        "DISMISS": ("PROPOSED",),
        "LINK_VERSION": ("ACKNOWLEDGED", "IN_PROGRESS"),
    }[action]
    if trigger["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE")

    model = db.get("models", trigger["model_id"])

    if action == "ACKNOWLEDGE":
        trigger["status"] = "ACKNOWLEDGED"
        trigger["acknowledged_by_user_id"] = user_id
        db.touch(trigger)
        report = db.get("drift_reports", trigger["drift_report_id"]) \
            if trigger["drift_report_id"] else None
        if report is not None and report["status"] == "BREACHED":
            report["status"] = "ACKNOWLEDGED"
            db.touch(report)
        if model is not None:
            cascades.recompute_open_trigger_count(model)
            db.touch(model)
        return response.ok(db.public(trigger))

    if action == "DISMISS":
        if trigger["retrain_required"]:
            raise ApiError("ERR_RETRAIN_REQUIRED")
        trigger["status"] = "DISMISSED"
        trigger["dismissed_reason"] = dismissed_reason
        db.touch(trigger)
        if model is not None:
            cascades.recompute_open_trigger_count(model)
            db.touch(model)
        return response.ok(db.public(trigger))

    # LINK_VERSION
    if trigger["status"] == "IN_PROGRESS":
        if linked["id"] != trigger["retrained_version_id"]:
            raise ApiError("ERR_RETRAINED_VERSION_LINEAGE_INVALID")
        if linked["approval_state"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE")
        trigger["status"] = "SATISFIED"
        db.touch(trigger)
        if model is not None:
            cascades.recompute_open_trigger_count(model)
            db.touch(model)
        return response.ok(db.public(trigger))

    anchor = _lineage_anchor(trigger)
    if linked["model_id"] != trigger["model_id"]:
        raise ApiError("ERR_RETRAINED_VERSION_LINEAGE_INVALID")
    if anchor is None or linked["parent_version_id"] != anchor:
        raise ApiError("ERR_RETRAINED_VERSION_LINEAGE_INVALID")

    trigger["retrained_version_id"] = linked["id"]
    trigger["status"] = ("SATISFIED" if linked["approval_state"] == "APPROVED"
                         else "IN_PROGRESS")
    db.touch(trigger)
    if model is not None:
        cascades.recompute_open_trigger_count(model)
        db.touch(model)
    return response.ok(db.public(trigger))
