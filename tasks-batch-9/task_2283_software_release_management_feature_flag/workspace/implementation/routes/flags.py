"""Feature-flag inventory, rollout ladder and cleanup enforcement."""

from datetime import timedelta

from flask import Blueprint, request

import db
import validate as v
from db import make, now, store, upd
from errors import fail
from middleware import ANY, authenticate
from response import array_response, object_response
from services import calc, cascade

bp = Blueprint("flags", __name__)

LANDED_OR_GONE = ("DEPLOYED", "WITHDRAWN", "REJECTED")


@bp.post("/feature-flags")
def create_flag():
    user_id, _role = authenticate(("Engineer",))
    body = v.get_body()
    key = v.req_str(body, "key", allow_blank=False)
    owner_user_id = v.req_str(body, "owner_user_id", allow_blank=False)
    expires_at = v.req_dt(body, "expires_at")
    permanent = v.opt_bool(body, "permanent", default=False)

    for existing in store.feature_flags.values():
        if existing["key"] == key:
            fail("ERR_FLAG_KEY_DUPLICATE", "Flag key '%s' already exists" % key)

    flag = make(
        "feature_flags",
        {
            "key": key,
            "owner_user_id": owner_user_id,
            "created_by_user_id": user_id,
            "expires_at": expires_at,
            "permanent": permanent,
            "state": "DRAFT",
            "cleanup_state": "COMPLIANT",
            "current_exposure_pct": 0,
            "applied_step_count": 0,
            "kill_switch_engaged": False,
            "stale_debt_points": 0,
            "last_sweep_at": None,
            "archived_at": None,
        },
    )
    return object_response(db.public(flag), 201)


@bp.get("/feature-flags/<flag_id>")
def read_flag(flag_id):
    authenticate(ANY)
    flag = db.get_flag(flag_id)
    return object_response(db.public(flag))


@bp.get("/feature-flags")
def list_flags():
    authenticate(ANY)
    limit, offset = v.pagination()
    records = db.by_creation(store.feature_flags.values())
    for field in ("state", "cleanup_state", "owner_user_id"):
        wanted = request.args.get(field)
        if wanted is not None:
            records = [f for f in records if f[field] == wanted]
    items = [db.public(f) for f in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))


@bp.get("/feature-flags/<flag_id>/change-links")
def list_change_links(flag_id):
    authenticate(ANY)
    limit, offset = v.pagination()
    db.get_flag(flag_id)
    records = db.by_creation(db.links_of_flag(flag_id))
    items = [db.public(l) for l in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))


# ---------------------------------------------------------------------------
# rollout ladder
# ---------------------------------------------------------------------------
@bp.post("/feature-flags/<flag_id>/rollout-steps")
def plan_step(flag_id):
    user_id, _role = authenticate(("Engineer",))
    body = v.get_body()
    target_pct = v.req_num(body, "target_pct", exclusive_min=0, maximum=100)
    soak_minutes = v.req_int(body, "soak_minutes", minimum=0)
    expected_version = v.req_int(body, "expected_feature_flag_version")
    deployment_id = v.opt_str(body, "deployment_id")

    flag = db.get_flag(flag_id)
    if deployment_id is not None:
        db.get_deployment(deployment_id)

    if expected_version != flag["version"]:
        fail(
            "ERR_STALE_FLAG_VERSION",
            "expected_feature_flag_version %s does not match %s"
            % (expected_version, flag["version"]),
        )

    if user_id != flag["owner_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the flag owner may plan a rollout step")

    if flag["cleanup_state"] == "ENFORCED":
        fail("ERR_FLAG_CLEANUP_ENFORCED", "Cleanup enforcement blocks new rollout steps")

    if not calc.target_pct_valid(flag["current_exposure_pct"], target_pct):
        fail(
            "ERR_ROLLOUT_STEP_TOO_LARGE",
            "target_pct %s exceeds the ladder ceiling for exposure %s"
            % (target_pct, flag["current_exposure_pct"]),
        )

    required = calc.required_soak_minutes(target_pct)
    if soak_minutes < required:
        fail(
            "ERR_SOAK_TOO_SHORT",
            "target_pct %s requires at least %d soak minutes" % (target_pct, required),
        )

    step = make(
        "flag_rollout_steps",
        {
            "feature_flag_id": flag_id,
            "deployment_id": deployment_id,
            "step_index": calc.next_step_index(flag_id),
            "target_pct": target_pct,
            "soak_minutes": soak_minutes,
            "state": "PLANNED",
            "previous_exposure_pct": None,
            "soak_started_at": None,
            "applied_at": None,
        },
    )
    db.touch(flag)
    return object_response(db.public(step), 201)


@bp.get("/flag-rollout-steps/<step_id>")
def read_step(step_id):
    authenticate(ANY)
    step = db.get_step(step_id)
    return object_response(db.public(step))


@bp.get("/flag-rollout-steps")
def list_steps():
    authenticate(ANY)
    limit, offset = v.pagination()
    records = db.by_creation(store.flag_rollout_steps.values())
    for field in ("feature_flag_id", "deployment_id", "state"):
        wanted = request.args.get(field)
        if wanted is not None:
            records = [s for s in records if s[field] == wanted]
    items = [db.public(s) for s in v.page(records, limit, offset)]
    return array_response(items, limit, offset, len(records))


@bp.post("/flag-rollout-steps/<step_id>/start-soak")
def start_soak(step_id):
    user_id, _role = authenticate(("Engineer",))
    v.get_body()
    step = db.get_step(step_id)
    flag = db.get_flag(step["feature_flag_id"])

    if step["state"] != "PLANNED":
        fail("ERR_STEP_STATE_INVALID", "Only a PLANNED step may start soaking")

    if flag["state"] not in ("DRAFT", "ACTIVE_ROLLING_OUT"):
        fail("ERR_FLAG_STATE_INVALID", "Flag state %s may not soak" % flag["state"])

    for link in db.by_creation(db.links_of_flag(flag["id"])):
        change = store.change_requests.get(link["change_request_id"])
        if change is None or change["state"] != "DEPLOYED":
            fail(
                "ERR_CHANGE_STATE_INVALID",
                "Every change guarded by this flag must be DEPLOYED",
            )

    if user_id != flag["owner_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the flag owner may start a soak")

    if flag["cleanup_state"] == "ENFORCED":
        fail("ERR_FLAG_CLEANUP_ENFORCED", "Cleanup enforcement blocks new soaks")

    for other in db.steps_of_flag(flag["id"]):
        if other["id"] != step["id"] and other["state"] == "SOAKING":
            fail("ERR_STEP_ALREADY_SOAKING", "Another step of this flag is already soaking")

    if step["step_index"] != flag["applied_step_count"] + 1:
        fail("ERR_STEP_OUT_OF_ORDER", "This step is not the flag's next rung")

    if step["deployment_id"] is not None:
        deployment = store.deployments.get(step["deployment_id"])
        if deployment is None or deployment["delivery_state"] not in (
            "IN_PROGRESS",
            "CANARY_SOAK",
        ):
            fail(
                "ERR_DEPLOYMENT_STATE_INVALID",
                "The gating deployment is not running",
            )

    upd(
        step,
        state="SOAKING",
        soak_started_at=now(),
        previous_exposure_pct=flag["current_exposure_pct"],
    )
    if flag["state"] == "DRAFT":
        upd(flag, state="ACTIVE_ROLLING_OUT")
    return object_response(db.public(step))


@bp.post("/flag-rollout-steps/<step_id>/apply")
def apply_step(step_id):
    user_id, _role = authenticate(("Engineer",))
    v.get_body()
    step = db.get_step(step_id)
    flag = db.get_flag(step["feature_flag_id"])

    if step["state"] != "SOAKING":
        fail("ERR_STEP_STATE_INVALID", "Only a SOAKING step may be applied")
    if flag["state"] != "ACTIVE_ROLLING_OUT":
        fail("ERR_FLAG_STATE_INVALID", "The flag is not ACTIVE_ROLLING_OUT")
    if user_id != flag["owner_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the flag owner may apply a rollout step")

    soak_end = step["soak_started_at"] + timedelta(minutes=step["soak_minutes"])
    if now() < soak_end:
        fail("ERR_SOAK_NOT_ELAPSED", "The soak has not finished yet")

    if step["deployment_id"] is not None:
        deployment = store.deployments.get(step["deployment_id"])
        if deployment is None or deployment["verification_state"] != "PASSING":
            fail(
                "ERR_DEPLOYMENT_STATE_INVALID",
                "The gating deployment's verification is not PASSING",
            )

    upd(step, state="APPLIED", applied_at=now())

    fields = {
        "current_exposure_pct": step["target_pct"],
        "applied_step_count": flag["applied_step_count"] + 1,
    }
    if calc.round_half_up(step["target_pct"], 2) == calc.dec(100):
        fields["state"] = "FULLY_ROLLED_OUT"
        fields["current_exposure_pct"] = 100

    probe = dict(flag)
    probe.update(fields)
    debt, cleanup = calc.flag_stale_debt(probe, now())
    fields["stale_debt_points"] = debt
    fields["cleanup_state"] = cleanup
    upd(flag, **fields)
    return object_response(db.public(step))


# ---------------------------------------------------------------------------
# kill switch / lifecycle
# ---------------------------------------------------------------------------
@bp.post("/feature-flags/<flag_id>/pause")
def pause_flag(flag_id):
    authenticate(("Engineer", "SRE"))
    body = v.get_body()
    v.opt_str(body, "reason")
    flag = db.get_flag(flag_id)
    if flag["state"] != "ACTIVE_ROLLING_OUT":
        fail("ERR_FLAG_STATE_INVALID", "Only an ACTIVE_ROLLING_OUT flag may be paused")
    upd(flag, state="PAUSED")
    return object_response(db.public(flag))


@bp.post("/feature-flags/<flag_id>/resume")
def resume_flag(flag_id):
    user_id, _role = authenticate(("Engineer",))
    v.get_body()
    flag = db.get_flag(flag_id)
    if flag["state"] != "PAUSED":
        fail("ERR_FLAG_STATE_INVALID", "Only a PAUSED flag may be resumed")
    if user_id != flag["owner_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the flag owner may resume this flag")
    if flag["cleanup_state"] == "ENFORCED":
        fail("ERR_FLAG_CLEANUP_ENFORCED", "Cleanup enforcement blocks resumption")
    upd(flag, state="ACTIVE_ROLLING_OUT", kill_switch_engaged=False)
    return object_response(db.public(flag))


@bp.post("/feature-flags/<flag_id>/archive")
def archive_flag(flag_id):
    user_id, _role = authenticate(("Engineer",))
    v.get_body()
    flag = db.get_flag(flag_id)
    if flag["state"] not in ("FULLY_ROLLED_OUT", "PAUSED"):
        fail("ERR_FLAG_STATE_INVALID", "Flag state %s may not be archived" % flag["state"])
    if user_id != flag["owner_user_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the flag owner may archive this flag")

    for link in db.by_creation(db.links_of_flag(flag_id)):
        change = store.change_requests.get(link["change_request_id"])
        if change is None or change["state"] not in LANDED_OR_GONE:
            fail(
                "ERR_CHANGE_STATE_INVALID",
                "A change guarded by this flag has not landed yet",
            )

    upd(
        flag,
        state="ARCHIVED",
        archived_at=now(),
        cleanup_state="COMPLIANT",
        stale_debt_points=0,
    )
    for step in db.by_creation(db.steps_of_flag(flag_id)):
        if step["state"] == "PLANNED":
            upd(step, state="VOIDED")
    return object_response(db.public(flag))


@bp.post("/flag-cleanup-sweeps")
def cleanup_sweep():
    authenticate(("ComplianceOfficer",))
    v.get_body()
    return object_response(cascade.cleanup_sweep())
