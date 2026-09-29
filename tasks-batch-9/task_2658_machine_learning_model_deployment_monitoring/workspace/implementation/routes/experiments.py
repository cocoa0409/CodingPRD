"""Champion-challenger evaluation, incident response, revalidation and ops."""

from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import db
import middleware as mw
import response
from db import dec, q2
from errors import ApiError
from middleware import ALL_ROLES, MA, MLE, PA, RE
from routes.registry import body_fk, need, require_present

bp = Blueprint("experiments", __name__)

EVALUATION_TERMINAL = ("PROMOTED", "REJECTED")
INCIDENT_SOURCES = ("MANUAL", "DRIFT", "SKEW", "LATENCY")
INCIDENT_SEVERITIES = ("SEV3", "SEV2", "SEV1")
RECURRENCE_CEILING = 2


def _metric_map(payload, field):
    """PRD 2.7 band 5 — ERR_INVALID_METRIC_SET in preference to
    ERR_INVALID_REQUEST."""
    if not mw.present(payload, field):
        raise ApiError("ERR_INVALID_METRIC_SET")
    value = payload[field]
    if not isinstance(value, dict):
        raise ApiError("ERR_INVALID_METRIC_SET")
    if sorted(value.keys()) != sorted(calc.METRIC_ORDER):
        raise ApiError("ERR_INVALID_METRIC_SET")
    for reading in value.values():
        if isinstance(reading, bool) or not isinstance(reading, (int, float)):
            raise ApiError("ERR_INVALID_METRIC_SET")
    return value


# =========================================================================
# Champion-challenger evaluations
# =========================================================================
@bp.post("/models/<model_id>/challenger-evaluations")
def schedule_evaluation(model_id):
    user_id, _ = mw.auth(RE, PA)
    model = need("models", model_id, "ERR_MODEL_NOT_FOUND")
    payload = mw.body()

    champion = body_fk(payload, "champion_deployment_id", "deployments",
                       "ERR_DEPLOYMENT_NOT_FOUND")
    challenger = body_fk(payload, "challenger_deployment_id", "deployments",
                         "ERR_DEPLOYMENT_NOT_FOUND")

    require_present(payload, "champion_deployment_id", "challenger_deployment_id",
                    "reserved_samples", "evaluation_ends_at",
                    "expected_model_version")
    mw.vstr(payload, "champion_deployment_id")
    mw.vstr(payload, "challenger_deployment_id")
    reserved = mw.vint(payload, "reserved_samples", minimum=1)
    ends_at = mw.vdt(payload, "evaluation_ends_at")
    champion_metrics = _metric_map(payload, "champion_metrics")
    challenger_metrics = _metric_map(payload, "challenger_metrics")
    expected = mw.vint(payload, "expected_model_version")

    if ends_at <= db.now():
        raise ApiError("ERR_INVALID_INTERVAL")

    if expected != model["version"]:
        raise ApiError("ERR_STALE_MODEL_VERSION")

    champion_version = db.get("model_versions", champion["model_version_id"])
    challenger_version = db.get("model_versions", challenger["model_version_id"])
    if (champion_version is None or challenger_version is None
            or champion_version["model_id"] != model["id"]
            or challenger_version["model_id"] != model["id"]):
        raise ApiError("ERR_CHALLENGER_MODEL_MISMATCH")

    for other in db.rows("challenger_evaluations"):
        if (other["model_id"] == model["id"]
                and other["status"] in ("SCHEDULED", "COLLECTING")):
            raise ApiError("ERR_ACTIVE_EVALUATION_EXISTS")
    if challenger["pattern"] != "SHADOW" or champion["pattern"] != "REALTIME":
        raise ApiError("ERR_CHALLENGER_NOT_SHADOW")
    if model["registry_status"] != "ACTIVE":
        raise ApiError("ERR_MODEL_ARCHIVED")

    if reserved > int(challenger_version["evaluation_sample_budget"]):
        raise ApiError("ERR_SAMPLE_BUDGET_EXCEEDED")

    row = db.insert("challenger_evaluations", {
        "model_id": model["id"],
        "champion_deployment_id": champion["id"],
        "challenger_deployment_id": challenger["id"],
        "challenger_version_id": challenger_version["id"],
        "reserved_samples": reserved,
        "evaluation_ends_at": ends_at,
        "extension_count": 0,
        "champion_metrics": champion_metrics,
        "challenger_metrics": challenger_metrics,
        "metric_lines": None,
        "promotion_score": None,
        "labeled_prediction_count": None,
        "criteria_failures": [],
        "status": "SCHEDULED",
        "created_by_user_id": user_id,
    })
    cascades.recompute_sample_budget(challenger_version)
    db.touch(challenger_version)
    db.touch(model)
    return response.created(db.public(row))


@bp.get("/challenger-evaluations/<evaluation_id>")
def get_evaluation(evaluation_id):
    mw.auth(*ALL_ROLES)
    row = need("challenger_evaluations", evaluation_id,
               "ERR_CHALLENGER_EVALUATION_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/challenger-evaluations")
def list_evaluations():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("challenger_evaluations"), {
        "model_id": ("model_id", "str"),
        "champion_deployment_id": ("champion_deployment_id", "str"),
        "challenger_deployment_id": ("challenger_deployment_id", "str"),
        "challenger_version_id": ("challenger_version_id", "str"),
        "status": ("status", "str"),
    })
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


def _arm_liveness(evaluation):
    challenger = db.get("deployments", evaluation["challenger_deployment_id"])
    champion = db.get("deployments", evaluation["champion_deployment_id"])
    if challenger is None or challenger["rollout_state"] not in calc.SERVING_STATES:
        raise ApiError("ERR_CHALLENGER_NOT_SERVING")
    if champion is None or champion["rollout_state"] != "LIVE":
        raise ApiError("ERR_CHAMPION_NOT_LIVE")
    return champion, challenger


@bp.post("/challenger-evaluations/<evaluation_id>/start")
def start_evaluation(evaluation_id):
    mw.auth(RE, PA)
    row = need("challenger_evaluations", evaluation_id,
               "ERR_CHALLENGER_EVALUATION_NOT_FOUND")
    if row["status"] in EVALUATION_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")
    if row["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    _arm_liveness(row)

    row["status"] = "COLLECTING"
    db.touch(row)
    challenger_version = db.get("model_versions", row["challenger_version_id"])
    cascades.recompute_sample_budget(challenger_version)
    return response.ok(db.public(row))


@bp.post("/challenger-evaluations/<evaluation_id>/conclude")
def conclude_evaluation(evaluation_id):
    mw.auth(RE, PA)
    row = need("challenger_evaluations", evaluation_id,
               "ERR_CHALLENGER_EVALUATION_NOT_FOUND")
    payload = mw.body()
    require_present(payload, "labeled_prediction_count")
    labeled = mw.vint(payload, "labeled_prediction_count", minimum=0)

    if row["status"] in EVALUATION_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")
    if row["status"] != "COLLECTING":
        raise ApiError("ERR_INVALID_STATE")
    if row["evaluation_ends_at"] > db.now():
        raise ApiError("ERR_EVALUATION_NOT_MATURE")
    _, challenger = _arm_liveness(row)
    if labeled == 0:
        raise ApiError("ERR_NO_LABELED_PREDICTIONS")

    lines, score = calc.promotion_score(row["champion_metrics"],
                                        row["challenger_metrics"])
    failures = []
    if score < calc.PROMOTION_SCORE_MIN:
        failures.append("SCORE_BELOW_MIN")
    if labeled < calc.MIN_LABELED_PREDICTIONS:
        failures.append("INSUFFICIENT_LABELS")
    latency_gap = (dec(row["challenger_metrics"]["LATENCY"])
                   - dec(row["champion_metrics"]["LATENCY"]))
    if latency_gap > calc.LATENCY_REGRESSION_MS:
        failures.append("LATENCY_REGRESSION")
    if challenger["health_state"] != "HEALTHY":
        failures.append("CHALLENGER_UNHEALTHY")
    check = cascades.latest_skew_check(row["challenger_version_id"],
                                       row["challenger_deployment_id"])
    if check is not None and check["status"] in calc.FAILED_SKEW_STATES:
        failures.append("SKEW_CHECK_FAILED")
    if cascades.deployment_incidents(row["challenger_deployment_id"],
                                     calc.RAMP_BLOCKING_INCIDENTS):
        failures.append("OPEN_INCIDENT")
    failures = sorted(failures)

    row["metric_lines"] = lines
    row["promotion_score"] = score
    row["criteria_failures"] = failures
    row["labeled_prediction_count"] = labeled

    challenger_version = db.get("model_versions", row["challenger_version_id"])
    model = db.get("models", row["model_id"])

    if not failures:
        row["status"] = "PROMOTED"
        db.touch(row)
        if model is not None:
            model["champion_version_id"] = row["challenger_version_id"]
            model["champion_promoted_at"] = db.now()
            db.touch(model)
        cascades.recompute_sample_budget(challenger_version)
        return response.ok(db.public(row))

    if failures == ["INSUFFICIENT_LABELS"]:
        row["status"] = "INCONCLUSIVE"
    else:
        row["status"] = "REJECTED"
    db.touch(row)
    if challenger_version is not None:
        cascades.recompute_sample_budget(challenger_version)
        db.touch(challenger_version)
    return response.ok(db.public(row))


@bp.post("/challenger-evaluations/<evaluation_id>/extend")
def extend_evaluation(evaluation_id):
    mw.auth(RE, PA)
    row = need("challenger_evaluations", evaluation_id,
               "ERR_CHALLENGER_EVALUATION_NOT_FOUND")
    if row["status"] in EVALUATION_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")
    if row["status"] != "INCONCLUSIVE":
        raise ApiError("ERR_INVALID_STATE")
    if int(row["extension_count"]) >= calc.MAX_EVALUATION_EXTENSIONS:
        raise ApiError("ERR_MAX_EXTENSIONS_REACHED")
    if "DEPLOYMENT_DRAINED" in (row["criteria_failures"] or []):
        raise ApiError("ERR_CHALLENGER_NOT_SERVING")

    challenger_version = db.get("model_versions", row["challenger_version_id"])
    increased = int(row["reserved_samples"]) + calc.EXTENSION_SAMPLES
    budget = int(challenger_version["evaluation_sample_budget"]) \
        if challenger_version is not None else 0
    if increased > budget:
        raise ApiError("ERR_SAMPLE_BUDGET_EXCEEDED")

    row["extension_count"] = int(row["extension_count"]) + 1
    row["criteria_failures"] = []
    row["promotion_score"] = None
    row["metric_lines"] = None
    row["evaluation_ends_at"] = db.add_days(row["evaluation_ends_at"],
                                            calc.EXTENSION_DAYS)
    row["reserved_samples"] = increased
    row["status"] = "COLLECTING"
    db.touch(row)
    if challenger_version is not None:
        cascades.recompute_sample_budget(challenger_version)
        db.touch(challenger_version)
    return response.ok(db.public(row))


# =========================================================================
# Prediction incidents
# =========================================================================
@bp.post("/prediction-incidents")
def create_incident():
    mw.auth(RE, MLE, PA)
    payload = mw.body()
    deployment = body_fk(payload, "deployment_id", "deployments",
                         "ERR_DEPLOYMENT_NOT_FOUND")
    require_present(payload, "deployment_id", "summary")
    mw.vstr(payload, "deployment_id")
    summary = mw.vstr(payload, "summary", minlen=1, maxlen=300)
    source = mw.venum(payload, "source", INCIDENT_SOURCES, required=False,
                      default="MANUAL")
    severity = mw.venum(payload, "severity", INCIDENT_SEVERITIES, required=False,
                        default="SEV3")

    if deployment["rollout_state"] not in calc.SERVING_STATES:
        raise ApiError("ERR_DEPLOYMENT_NOT_SERVING")

    row = db.insert("prediction_incidents", {
        "deployment_id": deployment["id"],
        "model_version_id": deployment["model_version_id"],
        "drift_report_id": None,
        "source": source,
        "severity": severity,
        "summary": summary,
        "status": "OPEN",
        "fallback_engaged": False,
        "fallback_strategy_used": None,
        "manual_override_traffic_pct": None,
        "recurrence_count": 0,
        "opened_at": db.now(),
        "resolved_at": None,
    })
    return response.created(db.public(row))


@bp.get("/prediction-incidents/<incident_id>")
def get_incident(incident_id):
    mw.auth(*ALL_ROLES)
    row = need("prediction_incidents", incident_id,
               "ERR_PREDICTION_INCIDENT_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/prediction-incidents")
def list_incidents():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("prediction_incidents"), {
        "deployment_id": ("deployment_id", "str"),
        "model_version_id": ("model_version_id", "str"),
        "drift_report_id": ("drift_report_id", "str"),
        "source": ("source", "str"),
        "severity": ("severity", "str"),
        "status": ("status", "str"),
    })
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


@bp.post("/prediction-incidents/<incident_id>/actions")
def incident_action(incident_id):
    mw.auth(RE, PA)
    incident = need("prediction_incidents", incident_id,
                    "ERR_PREDICTION_INCIDENT_NOT_FOUND")
    payload = mw.body()
    require_present(payload, "action")
    action = mw.venum(payload, "action", ("ENGAGE_FALLBACK", "MANUAL_OVERRIDE",
                                          "MONITOR", "RECUR", "RESOLVE"))
    mw.vstr(payload, "note", required=False)
    override = mw.vnum(payload, "override_traffic_pct", required=False,
                       minimum=0, maximum=100)
    if action == "MANUAL_OVERRIDE" and override is None:
        mw.bad("override_traffic_pct is required")

    deployment = db.get("deployments", incident["deployment_id"])
    endpoint = (db.get("serving_endpoints", deployment["serving_endpoint_id"])
                if deployment is not None else None)

    if incident["status"] == "RESOLVED":
        raise ApiError("ERR_TERMINAL_STATE")
    allowed = {
        "ENGAGE_FALLBACK": ("OPEN",),
        "MANUAL_OVERRIDE": ("OPEN",),
        "MONITOR": ("MITIGATING",),
        "RECUR": ("MONITORING",),
        "RESOLVE": ("MONITORING", "ESCALATED"),
    }[action]
    if incident["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE")

    if action == "ENGAGE_FALLBACK":
        if deployment is None or deployment["fallback_strategy"] == "NONE":
            raise ApiError("ERR_FALLBACK_NOT_CONFIGURED")
        if deployment["rollout_state"] not in calc.SERVING_STATES:
            raise ApiError("ERR_DEPLOYMENT_NOT_SERVING")
        incident["status"] = "MITIGATING"
        incident["fallback_engaged"] = True
        incident["fallback_strategy_used"] = deployment["fallback_strategy"]
        db.touch(incident)
        return response.ok(db.public(incident))

    if action == "MANUAL_OVERRIDE":
        if deployment is not None and deployment["manual_override_active"]:
            raise ApiError("ERR_MANUAL_OVERRIDE_ACTIVE")
        current = dec(deployment["traffic_pct"]) if deployment is not None else Decimal(0)
        if override >= current:
            raise ApiError("ERR_OVERRIDE_EXCEEDS_CURRENT_TRAFFIC")
        if deployment["rollout_state"] not in calc.SERVING_STATES:
            raise ApiError("ERR_DEPLOYMENT_NOT_SERVING")

        incident["status"] = "MITIGATING"
        incident["manual_override_traffic_pct"] = q2(override)
        db.touch(incident)

        deployment["manual_override_active"] = True
        deployment["override_traffic_pct"] = q2(override)
        deployment["traffic_pct"] = q2(override)
        cascades.append_ramp_step(deployment, current, override,
                                  q2(override) - current, "MANUAL_OVERRIDE")
        db.touch(deployment)
        if endpoint is not None:
            cascades.recompute_endpoint_ledger(endpoint)
            db.touch(endpoint)
        return response.ok(db.public(incident))

    if action == "MONITOR":
        incident["status"] = "MONITORING"
        db.touch(incident)
        return response.ok(db.public(incident))

    if action == "RECUR":
        incremented = int(incident["recurrence_count"]) + 1
        incident["recurrence_count"] = incremented
        if incremented < RECURRENCE_CEILING:
            incident["status"] = "MITIGATING"
        else:
            incident["status"] = "ESCALATED"
            incident["severity"] = "SEV1"
        db.touch(incident)
        return response.ok(db.public(incident))

    # RESOLVE
    incident["status"] = "RESOLVED"
    incident["resolved_at"] = db.now()
    override_value = incident["manual_override_traffic_pct"]
    db.touch(incident)

    if deployment is None:
        return response.ok(db.public(incident))

    touched_deployment = False
    if override_value is not None:
        restored = None
        for step in reversed(cascades.deployment_steps(deployment["id"])):
            if step["reason"] == "MANUAL_OVERRIDE":
                restored = dec(step["from_traffic_pct"])
                break
        if restored is None:
            restored = dec(deployment["traffic_pct"])
        deployment["manual_override_active"] = False
        deployment["override_traffic_pct"] = None
        deployment["traffic_pct"] = q2(restored)
        cascades.append_ramp_step(deployment, dec(override_value), restored,
                                  q2(restored) - dec(override_value),
                                  "OVERRIDE_RELEASE")
        touched_deployment = True
        if endpoint is not None:
            cascades.recompute_endpoint_ledger(endpoint)
            db.touch(endpoint)

    if deployment["health_state"] == "CRITICAL":
        blocking = cascades.deployment_incidents(
            deployment["id"], calc.CRITICAL_CLEAR_BLOCKING_INCIDENTS,
            exclude_id=incident["id"])
        if not blocking:
            deployment["health_state"] = "DEGRADED"
            touched_deployment = True

    if touched_deployment:
        db.touch(deployment)
    return response.ok(db.public(incident))


# =========================================================================
# Revalidation tasks
# =========================================================================
@bp.get("/revalidation-tasks/<revalidation_task_id>")
def get_task(revalidation_task_id):
    mw.auth(*ALL_ROLES)
    row = need("revalidation_tasks", revalidation_task_id,
               "ERR_REVALIDATION_TASK_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/revalidation-tasks")
def list_tasks():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("revalidation_tasks"), {
        "model_version_id": ("model_version_id", "str"),
        "status": ("status", "str"),
    })
    items = sorted(items, key=lambda r: (r["due_at"], r["created_at"], r["_seq"]))
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


@bp.post("/revalidation-tasks/<revalidation_task_id>/disposition")
def dispose_task(revalidation_task_id):
    user_id, _ = mw.auth(MA, PA)
    task = need("revalidation_tasks", revalidation_task_id,
                "ERR_REVALIDATION_TASK_NOT_FOUND")
    payload = mw.body()
    require_present(payload, "action")
    action = mw.venum(payload, "action", ("START_REVIEW", "PASS", "FAIL"))
    findings = mw.vstr(payload, "findings", required=False, minlen=1, maxlen=500)
    if action in ("PASS", "FAIL") and findings is None:
        mw.bad("findings is required")

    if task["status"] in ("PASSED", "FAILED"):
        raise ApiError("ERR_TERMINAL_STATE")
    allowed = {
        "START_REVIEW": ("DUE",),
        "PASS": ("IN_REVIEW",),
        "FAIL": ("IN_REVIEW",),
    }[action]
    if task["status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE")

    version = db.get("model_versions", task["model_version_id"])

    if action == "START_REVIEW":
        if version is not None and user_id == version["decided_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        task["status"] = "IN_REVIEW"
        task["reviewer_user_id"] = user_id
        db.touch(task)
        return response.ok(db.public(task))

    if user_id != task["reviewer_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    task["findings"] = findings
    task["decided_at"] = db.now()

    if action == "PASS":
        task["status"] = "PASSED"
        db.touch(task)
        if version is not None:
            model = db.get("models", version["model_id"])
            version["revalidation_due_at"] = cascades.revalidation_due(model,
                                                                        db.now())
            db.touch(version)
        return response.ok(db.public(task))

    task["status"] = "FAILED"
    db.touch(task)
    cascades.revalidation_fail_cascade(version)
    return response.ok(db.public(task))


# =========================================================================
# Operational namespace
# =========================================================================
@bp.post("/_clock/set_current_utc")
def set_clock():
    mw.auth(PA)
    payload = mw.body()
    require_present(payload, "current_utc")
    current = mw.vdt(payload, "current_utc")
    if current <= db.now():
        raise ApiError("ERR_CLOCK_REGRESSION")
    previous = db.set_clock(current)
    return response.ok({
        "current_utc": db.fmt_dt(current),
        "previous_utc": db.fmt_dt(previous),
    })


@bp.post("/_ops/revalidation-sweep")
def revalidation_sweep():
    mw.auth(PA)
    now = db.now()

    candidates = [v for v in db.rows("model_versions")
                  if v["approval_state"] == "APPROVED"
                  and v["revalidation_due_at"] is not None]
    evaluated_count = len(candidates)

    due = [v for v in candidates if v["revalidation_due_at"] <= now]
    due.sort(key=lambda r: (r["revalidation_due_at"], r["created_at"], r["_seq"]))

    created_count = 0
    skipped_existing_count = 0
    for version in due:
        existing = [t for t in db.rows("revalidation_tasks")
                    if t["model_version_id"] == version["id"]
                    and t["status"] in ("DUE", "IN_REVIEW")]
        if existing:
            skipped_existing_count += 1
            continue
        db.insert("revalidation_tasks", {
            "model_version_id": version["id"],
            "due_at": version["revalidation_due_at"],
            "status": "DUE",
            "reviewer_user_id": None,
            "findings": None,
            "decided_at": None,
            "swept_at": now,
        })
        created_count += 1

    staled_trigger_count = 0
    stale_candidates = [t for t in db.rows("retraining_triggers")
                        if t["status"] in ("ACKNOWLEDGED", "IN_PROGRESS")
                        and t["stale_after"] is not None
                        and t["stale_after"] <= now]
    for trigger in db.sorted_created(stale_candidates):
        trigger["status"] = "STALE"
        db.touch(trigger)
        model = db.get("models", trigger["model_id"])
        if model is not None:
            cascades.recompute_open_trigger_count(model)
            db.touch(model)
        staled_trigger_count += 1

    return response.ok({
        "evaluated_count": evaluated_count,
        "created_count": created_count,
        "skipped_existing_count": skipped_existing_count,
        "staled_trigger_count": staled_trigger_count,
    })
