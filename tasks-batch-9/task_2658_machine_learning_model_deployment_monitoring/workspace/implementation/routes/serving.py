"""Serving clusters, deployments, the traffic ramp and the ramp ledger."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import db
import middleware as mw
import response
from db import dec, q2
from errors import ApiError
from middleware import ALL_ROLES, PA, RE
from routes.registry import body_fk, need, require_present

bp = Blueprint("serving", __name__)

OPERATIONAL_STATES = ("OPEN", "FROZEN", "DRAINED")
PATTERNS = ("BATCH", "REALTIME", "SHADOW")
FALLBACK_STRATEGIES = ("NONE", "PREVIOUS_CHAMPION", "STATIC_DEFAULT", "RULE_BASED")
DEPLOYMENT_TERMINAL = ("ROLLED_BACK", "RETIRED")
RAMP_REASONS = ("RAMP_STEP", "ROLLBACK_RELEASE", "DRAIN_RELEASE", "MANUAL_OVERRIDE",
                "OVERRIDE_RELEASE")


# =========================================================================
# Serving clusters
# =========================================================================
@bp.post("/serving-endpoints")
def create_endpoint():
    mw.auth(PA, RE)
    payload = mw.body()
    require_present(payload, "name", "region", "serving_feature_spec_hash")
    name = mw.vstr(payload, "name", minlen=1, maxlen=120)
    region = mw.vstr(payload, "region", minlen=1, maxlen=40)
    spec_hash = mw.vstr(payload, "serving_feature_spec_hash", minlen=1, maxlen=80)
    max_traffic = mw.vnum(payload, "max_traffic_pct", required=False, minimum=1,
                          maximum=100, default=Decimal("100"))
    cooldown = mw.vint(payload, "deploy_cooldown_minutes", required=False,
                       minimum=0, maximum=240, default=30)

    for existing in db.rows("serving_endpoints"):
        if existing["name"] == name and existing["region"] == region:
            raise ApiError("ERR_DUPLICATE_SERVING_ENDPOINT_NAME")

    row = db.insert("serving_endpoints", {
        "name": name,
        "region": region,
        "serving_feature_spec_hash": spec_hash,
        "max_traffic_pct": q2(max_traffic),
        "allocated_traffic_pct": q2(0),
        "operational_state": "OPEN",
        "deploy_cooldown_minutes": cooldown,
    })
    return response.created(db.public(row))


@bp.get("/serving-endpoints/<serving_endpoint_id>")
def get_endpoint(serving_endpoint_id):
    mw.auth(*ALL_ROLES)
    row = need("serving_endpoints", serving_endpoint_id,
               "ERR_SERVING_ENDPOINT_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/serving-endpoints")
def list_endpoints():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("serving_endpoints"), {
        "region": ("region", "str"),
        "operational_state": ("operational_state", "str"),
    })
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


@bp.post("/serving-endpoints/<serving_endpoint_id>/operational-state")
def set_operational_state(serving_endpoint_id):
    mw.auth(PA, RE)
    row = need("serving_endpoints", serving_endpoint_id,
               "ERR_SERVING_ENDPOINT_NOT_FOUND")
    payload = mw.body()
    require_present(payload, "operational_state")
    state = mw.venum(payload, "operational_state", OPERATIONAL_STATES)
    row["operational_state"] = state
    db.touch(row)
    return response.ok(db.public(row))


# =========================================================================
# Deployments
# =========================================================================
@bp.post("/deployments")
def create_deployment():
    user_id, _ = mw.auth(RE)
    payload = mw.body()

    version = body_fk(payload, "model_version_id", "model_versions",
                      "ERR_MODEL_VERSION_NOT_FOUND")
    endpoint = body_fk(payload, "serving_endpoint_id", "serving_endpoints",
                       "ERR_SERVING_ENDPOINT_NOT_FOUND")

    require_present(payload, "model_version_id", "serving_endpoint_id", "pattern",
                    "serve_from", "serve_until", "expected_serving_endpoint_version")
    mw.vstr(payload, "model_version_id")
    mw.vstr(payload, "serving_endpoint_id")
    pattern = mw.venum(payload, "pattern", PATTERNS)
    serve_from = mw.vdt(payload, "serve_from")
    serve_until = mw.vdt(payload, "serve_until")
    expected = mw.vint(payload, "expected_serving_endpoint_version")
    fallback = mw.venum(payload, "fallback_strategy", FALLBACK_STRATEGIES,
                        required=False, default="NONE")

    if serve_until <= serve_from:
        raise ApiError("ERR_INVALID_INTERVAL")

    if expected != endpoint["version"]:
        raise ApiError("ERR_STALE_SERVING_ENDPOINT_VERSION")

    if version["approval_state"] != "APPROVED":
        raise ApiError("ERR_VERSION_NOT_APPROVED")
    if endpoint["operational_state"] != "OPEN":
        raise ApiError("ERR_SERVING_ENDPOINT_NOT_OPEN")
    if endpoint["serving_feature_spec_hash"] != version["feature_spec_hash"]:
        raise ApiError("ERR_FEATURE_SPEC_MISMATCH")

    cooldown = timedelta(minutes=int(endpoint["deploy_cooldown_minutes"]))
    for other in db.rows("deployments"):
        if other["serving_endpoint_id"] != endpoint["id"]:
            continue
        if other["pattern"] != pattern:
            continue
        if other["rollout_state"] in DEPLOYMENT_TERMINAL:
            continue
        clear = (serve_from >= other["serve_until"] + cooldown
                 or serve_until <= other["serve_from"])
        if not clear:
            raise ApiError("ERR_SERVE_WINDOW_CONFLICT")

    checkpoints = calc.RAMP_CHECKPOINTS[pattern]
    row = db.insert("deployments", {
        "model_version_id": version["id"],
        "serving_endpoint_id": endpoint["id"],
        "pattern": pattern,
        "serve_from": serve_from,
        "serve_until": serve_until,
        "rollout_state": "PENDING",
        "health_state": "HEALTHY",
        "traffic_pct": q2(0),
        "ramp_step_index": 0,
        "target_traffic_pct": q2(checkpoints[-1]),
        "cumulative_ramp_delta_pct": q2(0),
        "fallback_strategy": fallback,
        "manual_override_active": False,
        "override_traffic_pct": None,
        "health_score_provisional": None,
        "health_score_final": None,
        "rolled_back_at": None,
        "created_by_user_id": user_id,
    })
    cascades.recompute_endpoint_ledger(endpoint)
    db.touch(endpoint)
    return response.created(db.public(row))


@bp.get("/deployments/<deployment_id>")
def get_deployment(deployment_id):
    mw.auth(*ALL_ROLES)
    row = need("deployments", deployment_id, "ERR_DEPLOYMENT_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/deployments")
def list_deployments():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("deployments"), {
        "model_version_id": ("model_version_id", "str"),
        "serving_endpoint_id": ("serving_endpoint_id", "str"),
        "pattern": ("pattern", "str"),
        "rollout_state": ("rollout_state", "str"),
        "health_state": ("health_state", "str"),
    })
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


def _promote_champion(deployment):
    version = db.get("model_versions", deployment["model_version_id"])
    if version is None:
        return
    model = db.get("models", version["model_id"])
    if model is None:
        return
    model["champion_version_id"] = version["id"]
    model["champion_promoted_at"] = db.now()
    db.touch(model)


def _ramp_safety_gates(deployment, endpoint, allow_capacity=True):
    """Bands 11, 12 and 14 of the ladder, in ladder order."""
    if deployment["health_state"] == "CRITICAL":
        raise ApiError("ERR_HEALTH_CRITICAL_BLOCKED")
    if cascades.deployment_incidents(deployment["id"],
                                     calc.RAMP_BLOCKING_INCIDENTS):
        raise ApiError("ERR_OPEN_INCIDENT_BLOCKS_ACTION")
    check = cascades.latest_skew_check(deployment["model_version_id"],
                                       deployment["id"])
    if check is not None and check["status"] in calc.FAILED_SKEW_STATES:
        raise ApiError("ERR_SKEW_CHECK_FAILED")
    version = db.get("model_versions", deployment["model_version_id"])
    if version is None or version["approval_state"] != "APPROVED":
        raise ApiError("ERR_VERSION_NOT_APPROVED")
    if endpoint is None or endpoint["operational_state"] != "OPEN":
        raise ApiError("ERR_SERVING_ENDPOINT_NOT_OPEN")
    if deployment["serve_until"] <= db.now():
        raise ApiError("ERR_SERVE_WINDOW_EXPIRED")


@bp.post("/deployments/<deployment_id>/ramp")
def ramp_deployment(deployment_id):
    mw.auth(RE)
    deployment = need("deployments", deployment_id, "ERR_DEPLOYMENT_NOT_FOUND")
    endpoint = db.get("serving_endpoints", deployment["serving_endpoint_id"])

    if deployment["rollout_state"] in DEPLOYMENT_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")
    if deployment["rollout_state"] not in ("PENDING", "RAMPING", "LIVE"):
        raise ApiError("ERR_INVALID_STATE")
    checkpoints = calc.RAMP_CHECKPOINTS[deployment["pattern"]]
    if deployment["ramp_step_index"] >= len(checkpoints):
        raise ApiError("ERR_RAMP_ALREADY_COMPLETE")
    if deployment["manual_override_active"]:
        raise ApiError("ERR_MANUAL_OVERRIDE_ACTIVE")

    _ramp_safety_gates(deployment, endpoint)

    health_at_step = deployment["health_state"]
    step_index = deployment["ramp_step_index"]
    from_traffic = dec(deployment["traffic_pct"])
    _, granted, new_traffic, advance = calc.ramp_plan(deployment, endpoint)

    deployment["traffic_pct"] = new_traffic
    if deployment["rollout_state"] == "PENDING":
        deployment["rollout_state"] = "RAMPING"
    if advance:
        deployment["ramp_step_index"] = step_index + 1
    reached_live = deployment["ramp_step_index"] >= len(checkpoints)
    if reached_live:
        deployment["rollout_state"] = "LIVE"

    cascades.append_ramp_step(deployment, from_traffic, new_traffic, granted,
                              "RAMP_STEP", step_index=step_index,
                              health_state=health_at_step)
    db.touch(deployment)
    cascades.recompute_endpoint_ledger(endpoint)
    db.touch(endpoint)

    if reached_live and deployment["pattern"] == "REALTIME":
        _promote_champion(deployment)

    return response.ok(db.public(deployment))


@bp.post("/deployments/<deployment_id>/rollout-action")
def rollout_action(deployment_id):
    mw.auth(RE, PA)
    deployment = need("deployments", deployment_id, "ERR_DEPLOYMENT_NOT_FOUND")
    payload = mw.body()
    require_present(payload, "action")
    action = mw.venum(payload, "action", ("HOLD", "RESUME", "ROLLBACK", "RETIRE"))
    mw.vstr(payload, "note", required=False)

    endpoint = db.get("serving_endpoints", deployment["serving_endpoint_id"])
    state = deployment["rollout_state"]
    if state in DEPLOYMENT_TERMINAL:
        raise ApiError("ERR_TERMINAL_STATE")

    allowed = {
        "HOLD": ("RAMPING",),
        "RESUME": ("HELD",),
        "ROLLBACK": ("RAMPING", "HELD", "LIVE"),
        "RETIRE": ("PENDING", "LIVE", "DRAINING"),
    }[action]
    if state not in allowed:
        raise ApiError("ERR_INVALID_STATE")

    if action == "HOLD":
        deployment["rollout_state"] = "HELD"
        db.touch(deployment)
        return response.ok(db.public(deployment))

    if action == "RESUME":
        if deployment["manual_override_active"]:
            raise ApiError("ERR_MANUAL_OVERRIDE_ACTIVE")
        _ramp_safety_gates(deployment, endpoint)
        deployment["rollout_state"] = "RAMPING"
        db.touch(deployment)
        return response.ok(db.public(deployment))

    if action == "ROLLBACK":
        previous = dec(deployment["traffic_pct"])
        deployment["rollout_state"] = "ROLLED_BACK"
        deployment["traffic_pct"] = q2(0)
        deployment["rolled_back_at"] = db.now()
        cascades.append_ramp_step(deployment, previous, Decimal(0), -previous,
                                  "ROLLBACK_RELEASE",
                                  step_index=deployment["ramp_step_index"])
        deployment["ramp_step_index"] = 0
        db.touch(deployment)
        if endpoint is not None:
            cascades.recompute_endpoint_ledger(endpoint)
            db.touch(endpoint)
        version = db.get("model_versions", deployment["model_version_id"])
        if version is not None:
            model = db.get("models", version["model_id"])
            if model is not None and model["champion_version_id"] == version["id"]:
                model["champion_version_id"] = version["parent_version_id"]
                model["champion_promoted_at"] = db.now()
                db.touch(model)
        cascades.end_collecting_evaluations(deployment, "DEPLOYMENT_ROLLED_BACK")
        return response.ok(db.public(deployment))

    # RETIRE
    previous = dec(deployment["traffic_pct"])
    deployment["rollout_state"] = "RETIRED"
    deployment["traffic_pct"] = q2(0)
    if previous != 0:
        cascades.append_ramp_step(deployment, previous, Decimal(0), -previous,
                                  "DRAIN_RELEASE",
                                  step_index=deployment["ramp_step_index"])
    db.touch(deployment)
    if endpoint is not None:
        cascades.recompute_endpoint_ledger(endpoint)
        db.touch(endpoint)
    return response.ok(db.public(deployment))


@bp.get("/deployments/<deployment_id>/health")
def deployment_health(deployment_id):
    mw.auth(*ALL_ROLES)
    deployment = need("deployments", deployment_id, "ERR_DEPLOYMENT_NOT_FOUND")
    variant = request_variant()
    window = cascades.latest_performance_window(deployment["id"])
    data = {
        "deployment_id": deployment["id"],
        "health_state": deployment["health_state"],
        "score_variant": variant,
        "health_score": None,
        "baseline_delta_pct": None,
        "monitoring_window_id": None,
        "prediction_count": None,
        "labeled_prediction_count": None,
    }
    if window is not None:
        version = db.get("model_versions", window["model_version_id"])
        score, delta = calc.health_score(window, version, variant)
        data["health_score"] = db.dec_out(score)
        data["baseline_delta_pct"] = db.dec_out(delta)
        data["monitoring_window_id"] = window["id"]
        data["prediction_count"] = window["prediction_count"]
        data["labeled_prediction_count"] = window["labeled_prediction_count"]
    return response.ok(data)


def request_variant():
    from flask import request
    raw = request.args.get("score_variant")
    if raw is None or raw == "":
        return "PROVISIONAL"
    if raw not in ("PROVISIONAL", "FINAL"):
        mw.bad("score_variant is not a permitted value")
    return raw


# =========================================================================
# Ramp ledger
# =========================================================================
@bp.get("/deployments/<deployment_id>/ramp-steps")
def list_deployment_ramp_steps(deployment_id):
    mw.auth(*ALL_ROLES)
    need("deployments", deployment_id, "ERR_DEPLOYMENT_NOT_FOUND")
    limit, offset = mw.pagination()
    items = [r for r in db.rows("traffic_ramp_steps")
             if r["deployment_id"] == deployment_id]
    items = mw.qfilter(items, {"reason": ("reason", "str")})
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)


@bp.get("/traffic-ramp-steps/<ramp_step_id>")
def get_ramp_step(ramp_step_id):
    mw.auth(*ALL_ROLES)
    row = need("traffic_ramp_steps", ramp_step_id, "ERR_TRAFFIC_RAMP_STEP_NOT_FOUND")
    return response.ok(db.public(row))


@bp.get("/traffic-ramp-steps")
def list_ramp_steps():
    mw.auth(*ALL_ROLES)
    limit, offset = mw.pagination()
    items = mw.qfilter(db.rows("traffic_ramp_steps"), {
        "deployment_id": ("deployment_id", "str"),
        "reason": ("reason", "str"),
    })
    items = db.sorted_created(items)
    total = len(items)
    return response.listing([db.public(r) for r in mw.page(items, limit, offset)],
                            limit, offset, total)
