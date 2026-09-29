"""Deployment windows, health ingestion, canary analysis and rollback."""

from datetime import datetime, timedelta, timezone

from flask import Blueprint, request

import db
import validate as v
from db import make, now, store, upd
from errors import fail
from middleware import ANY, authenticate
from response import array_response, object_response
from services import calc, cascade

bp = Blueprint("deployments", __name__)

LIVE_PHASES = ("CUT", "STABILIZING", "RELEASED")
OCCUPYING = ("SCHEDULED", "IN_PROGRESS", "CANARY_SOAK", "COMPLETED")


def _midnight(moment):
    return datetime(
        moment.year, moment.month, moment.day, tzinfo=timezone.utc
    )


def _window_geometry_ok(env, window_start_at, window_end_at):
    day = _midnight(window_start_at)
    permitted_start = day + timedelta(hours=env["deploy_window_start_hour_utc"])
    permitted_end = day + timedelta(hours=env["deploy_window_end_hour_utc"])
    return window_start_at >= permitted_start and window_end_at <= permitted_end


@bp.post("/releases/<release_id>/deployments")
def reserve_deployment(release_id):
    authenticate(("SRE",))
    body = v.get_body()
    environment_id = v.req_str(body, "environment_id", allow_blank=False)
    window_start_at = v.req_dt(body, "window_start_at")
    window_end_at = v.req_dt(body, "window_end_at")
    if window_end_at <= window_start_at:
        v.bad("window_end_at must be strictly after window_start_at")
    strategy = v.req_enum(body, "strategy", ("CANARY", "ALL_AT_ONCE", "BLUE_GREEN"))
    abort_error_rate_pct = v.req_num(body, "abort_error_rate_pct", exclusive_min=0)
    abort_latency_p95_ms = v.req_int(body, "abort_latency_p95_ms", minimum=1)
    canary_pct = v.opt_num(body, "canary_pct", default=5, exclusive_min=0, maximum=100)
    min_sample_count = v.opt_int(body, "min_sample_count", default=20, minimum=0)

    release = db.get_release(release_id)
    env = db.get_environment(environment_id)

    if release["phase"] not in LIVE_PHASES:
        fail(
            "ERR_RELEASE_PHASE_INVALID",
            "A deployment window may only be reserved for a cut release",
        )

    if not _window_geometry_ok(env, window_start_at, window_end_at):
        fail(
            "ERR_DEPLOY_WINDOW_VIOLATION",
            "The requested window falls outside the environment's permitted hours",
        )

    cooldown = timedelta(minutes=env["cooldown_minutes"])
    for other in db.by_creation(db.deployments_of_environment(environment_id)):
        if other["delivery_state"] in ("ABORTED", "ROLLED_BACK"):
            continue
        occupied_start = other["window_start_at"]
        occupied_end = other["window_end_at"] + cooldown
        if window_start_at < occupied_end and occupied_start < window_end_at:
            fail(
                "ERR_DEPLOYMENT_WINDOW_CONFLICT",
                "The requested window collides with an existing reservation",
            )

    deployment = make(
        "deployments",
        {
            "release_id": release_id,
            "environment_id": environment_id,
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "strategy": strategy,
            "canary_pct": canary_pct,
            "abort_error_rate_pct": abort_error_rate_pct,
            "abort_latency_p95_ms": abort_latency_p95_ms,
            "min_sample_count": min_sample_count,
            "delivery_state": "SCHEDULED",
            "verification_state": "PENDING",
            "health_score": 0,
            "completed_at": None,
            "rolled_back_at": None,
        },
    )
    cascade.refresh_evidence_packet_required(release)
    return object_response(db.public(deployment), 201)


@bp.get("/deployments/<deployment_id>")
def read_deployment(deployment_id):
    authenticate(ANY)
    deployment = db.get_deployment(deployment_id)
    return object_response(db.public(deployment))


@bp.get("/deployments")
def list_deployments():
    authenticate(ANY)
    limit, offset = v.pagination()
    records = db.by_creation(store.deployments.values())
    for field in ("release_id", "environment_id", "delivery_state"):
        wanted = request.args.get(field)
        if wanted is not None:
            records = [d for d in records if d[field] == wanted]
    items = [db.public(d) for d in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))


@bp.post("/deployments/<deployment_id>/start")
def start_deployment(deployment_id):
    authenticate(("SRE",))
    v.get_body()
    deployment = db.get_deployment(deployment_id)
    release = db.get_release(deployment["release_id"])
    env = store.environments.get(deployment["environment_id"])

    if deployment["delivery_state"] != "SCHEDULED":
        fail("ERR_DEPLOYMENT_STATE_INVALID", "Only a SCHEDULED deployment may start")
    if release["phase"] not in LIVE_PHASES:
        fail("ERR_RELEASE_PHASE_INVALID", "The release is not in a deployable phase")

    moment = now()
    if moment < deployment["window_start_at"] or moment >= deployment["window_end_at"]:
        fail("ERR_DEPLOY_WINDOW_VIOLATION", "The clock is outside the reserved window")

    if env is not None and env["blackout_start_at"] is not None and env["blackout_end_at"] is not None:
        if env["blackout_start_at"] <= moment <= env["blackout_end_at"]:
            fail("ERR_BLACKOUT_ACTIVE", "The environment is inside a change blackout")

    upd(deployment, delivery_state="IN_PROGRESS")
    if env is not None:
        upd(env, active_deployment_count=env["active_deployment_count"] + 1)
    if release["phase"] == "CUT":
        upd(release, phase="STABILIZING")
    return object_response(db.public(deployment))


@bp.post("/deployments/<deployment_id>/health-signals")
def ingest_health_signal(deployment_id):
    authenticate(("SRE", "PlatformAdmin"))
    body = v.get_body()
    observed_at = v.req_dt(body, "observed_at")
    cohort = v.req_enum(body, "cohort", ("CANARY", "BASELINE"))
    request_count = v.req_int(body, "request_count", minimum=1)
    error_count = v.req_int(body, "error_count", minimum=0)
    if error_count > request_count:
        v.bad("error_count must not exceed request_count")
    latency = v.req_int(body, "latency_p95_ms", minimum=0)

    deployment = db.get_deployment(deployment_id)

    signal = make(
        "health_signals",
        {
            "deployment_id": deployment_id,
            "observed_at": observed_at,
            "cohort": cohort,
            "request_count": request_count,
            "error_count": error_count,
            "latency_p95_ms": latency,
        },
        common=False,
    )
    if (
        cohort == "CANARY"
        and deployment["strategy"] == "CANARY"
        and deployment["delivery_state"] == "IN_PROGRESS"
    ):
        upd(deployment, delivery_state="CANARY_SOAK")
    return object_response(db.public(signal), 201)


@bp.get("/deployments/<deployment_id>/health-signals")
def list_health_signals(deployment_id):
    authenticate(ANY)
    limit, offset = v.pagination()
    db.get_deployment(deployment_id)
    records = db.by_creation(db.signals_of_deployment(deployment_id))
    cohort = request.args.get("cohort")
    if cohort is not None:
        records = [h for h in records if h["cohort"] == cohort]
    items = [db.public(h) for h in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))


@bp.post("/deployments/<deployment_id>/canary-evaluations")
def run_canary_evaluation(deployment_id):
    authenticate(("SRE",))
    body = v.get_body()
    window_start_at = v.req_dt(body, "window_start_at")
    window_end_at = v.req_dt(body, "window_end_at")
    if window_end_at <= window_start_at:
        v.bad("window_end_at must be strictly after window_start_at")

    deployment = db.get_deployment(deployment_id)
    verdict = calc.canary_health_verdict(deployment, window_start_at, window_end_at)

    evaluation = make(
        "canary_evaluations",
        {
            "deployment_id": deployment_id,
            "window_start_at": window_start_at,
            "window_end_at": window_end_at,
            "sample_count": verdict["sample_count"],
            "error_rate_pct_rounded": verdict["error_rate_pct_rounded"],
            "latency_p95_ms": verdict["latency_p95_ms"],
            "weighted_health_score": verdict["weighted_health_score"],
            "verdict": verdict["verdict"],
            "abort_triggered": verdict["abort_triggered"],
        },
        common=False,
    )

    verification = {
        "PASS": "PASSING",
        "FAIL": "FAILING",
        "INCONCLUSIVE": "INCONCLUSIVE",
    }[verdict["verdict"]]
    upd(
        deployment,
        verification_state=verification,
        health_score=verdict["weighted_health_score"],
    )

    if verdict["abort_triggered"] and deployment["delivery_state"] in (
        "IN_PROGRESS",
        "CANARY_SOAK",
    ):
        cascade.deployment_abort(deployment)

    return object_response(db.public(evaluation), 201)


@bp.get("/deployments/<deployment_id>/canary-evaluations")
def list_canary_evaluations(deployment_id):
    authenticate(ANY)
    limit, offset = v.pagination()
    db.get_deployment(deployment_id)
    records = db.by_creation(db.evaluations_of_deployment(deployment_id))
    items = [db.public(e) for e in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))


@bp.post("/deployments/<deployment_id>/complete")
def complete_deployment(deployment_id):
    authenticate(("SRE",))
    body = v.get_body()
    waive = v.opt_bool(body, "waive_verification", default=False)

    deployment = db.get_deployment(deployment_id)
    env = store.environments.get(deployment["environment_id"])
    release = store.releases.get(deployment["release_id"])

    if deployment["delivery_state"] not in ("IN_PROGRESS", "CANARY_SOAK"):
        fail("ERR_DEPLOYMENT_STATE_INVALID", "Only a running deployment may complete")

    verification = deployment["verification_state"]
    if waive:
        if verification != "INCONCLUSIVE" or (env is not None and env["tier"] == "PROD"):
            fail(
                "ERR_CANARY_NOT_PASSING",
                "A verification waiver is only available for an INCONCLUSIVE non-PROD deployment",
            )
        verification = "WAIVED"

    if deployment["strategy"] == "CANARY":
        allowed = ("PASSING", "WAIVED")
    else:
        allowed = ("PENDING", "PASSING", "WAIVED")
    if verification not in allowed:
        fail(
            "ERR_CANARY_NOT_PASSING",
            "verification_state %s does not permit completion" % verification,
        )

    upd(
        deployment,
        delivery_state="COMPLETED",
        completed_at=now(),
        verification_state=verification,
    )
    if env is not None:
        upd(
            env,
            active_deployment_count=max(0, env["active_deployment_count"] - 1),
            last_deployment_end_at=cascade.last_deployment_end_value(env),
        )
    if release is not None:
        cascade.refresh_evidence_packet_required(release)
    return object_response(db.public(deployment))


@bp.post("/deployments/<deployment_id>/rollback")
def rollback_deployment(deployment_id):
    authenticate(("SRE",))
    body = v.get_body()
    v.opt_str(body, "reason")
    deployment = db.get_deployment(deployment_id)

    if deployment["delivery_state"] != "COMPLETED":
        fail("ERR_DEPLOYMENT_STATE_INVALID", "Only a COMPLETED deployment may roll back")

    cascade.deployment_rollback(deployment)
    return object_response(db.public(deployment))
