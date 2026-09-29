"""Rollout plans: closed-interval exclusivity, the phase ladder and rollback."""
from decimal import Decimal

from flask import Blueprint, g

import calc
import flows
from common import (MIN_PHASE_DWELL_HOURS, PHASE_COUNT, PHASE_PCTS,
                    ROLLBACK_COOLDOWN_HOURS, arg_filter, body_json, d2,
                    endpoint, fail, fmt_iso, get_row, hours, new_row, now_dt,
                    now_iso, ok, paginate, parse_iso, public, resolve, rows,
                    scope_rows, touch)
from valid import check_unknown, opt_str, req_bool, req_id, req_int, req_iso, req_str

bp = Blueprint("rollouts", __name__)

MODES = {"IMMEDIATE", "PHASED"}
READ_ROLES = ["PublisherAdmin", "ReleaseManager", "ComplianceOfficer",
              "PlatformPolicyAdmin", "Auditor"]
BLOCKING_STATES = ("SCHEDULED", "PHASE_ACTIVE", "PAUSED")


def _projected_end(mode, starts_at):
    if mode == "PHASED":
        return starts_at + hours(PHASE_COUNT * MIN_PHASE_DWELL_HOURS)
    return starts_at


def _mirror_shares(app, released, held_back):
    app["released_share_pct"] = released
    app["held_back_share_pct"] = held_back


@bp.route("/rollout-plans", methods=["POST"])
@endpoint(["ReleaseManager"])
def create_plan():
    body = body_json()
    check_unknown(body, {"expected_app_record_version", "app_record_id",
                         "submission_id", "mode", "scheduled_start_at"})
    app, submission = resolve([
        ("app_record", body.get("app_record_id")),
        ("submission", body.get("submission_id")),
    ])
    expected = req_int(body, "expected_app_record_version")
    req_id(body, "app_record_id")
    req_id(body, "submission_id")
    mode = req_str(body, "mode", enum=MODES)
    scheduled_start_at = req_iso(body, "scheduled_start_at")
    if expected != app["version"]:
        fail("ERR_STALE_APP_RECORD_VERSION",
             "expected_app_record_version does not match")
    flows.posture_gate(app, release_advancing=True)
    account = calc.account_of_app(app)
    flows.program_gate(account)
    if (submission.get("release_mode") == "MANUAL"
            or submission.get("release_mode") != mode):
        fail("ERR_ROLLOUT_MODE_MISMATCH",
             "the plan mode must equal the submission's release_mode")
    projected_end_at = _projected_end(mode, scheduled_start_at)
    for other in calc.plans_of_app(app["id"]):
        if other["state"] in BLOCKING_STATES:
            other_start = parse_iso(other["scheduled_start_at"])
            other_end = parse_iso(other["projected_end_at"])
            if scheduled_start_at <= other_end and other_start <= projected_end_at:
                fail("ERR_ROLLOUT_WINDOW_CONFLICT",
                     "the closed release interval touches plan %s" % other["id"])
        elif other["state"] == "ROLLED_BACK" and other.get("halt_distribution"):
            terminated_at = parse_iso(other.get("terminated_at"))
            if (terminated_at is not None
                    and scheduled_start_at < terminated_at
                    + hours(ROLLBACK_COOLDOWN_HOURS)):
                fail("ERR_ROLLOUT_WINDOW_CONFLICT",
                     "the %d-hour rollback cooldown has not elapsed"
                     % ROLLBACK_COOLDOWN_HOURS)
    row = new_row("rollout_plan", {
        "app_record_id": app["id"],
        "submission_id": submission["id"],
        "mode": mode,
        "scheduled_start_at": fmt_iso(scheduled_start_at),
        "projected_end_at": fmt_iso(projected_end_at),
        "state": "SCHEDULED",
        "phase_index": 0,
        "released_share_pct": d2("0"),
        "held_back_share_pct": d2("100"),
        "phase_entered_at": None,
        "pause_reason_code": None,
        "rollback_reason_code": None,
        "halt_distribution": False,
        "completed_at": None,
        "terminated_at": None,
    })
    touch(app)
    return ok(public(row), 201)


@bp.route("/rollout-plans", methods=["GET"])
@endpoint(READ_ROLES)
def list_plans():
    items = rows("rollout_plan")
    for field in ("app_record_id", "submission_id", "state", "mode"):
        wanted = arg_filter(field)
        if wanted is not None:
            items = [r for r in items if r.get(field) == wanted]
    return paginate(scope_rows(items))


@bp.route("/rollout-plans/<plan_id>", methods=["GET"])
@endpoint(READ_ROLES)
def read_plan(plan_id):
    (plan,) = resolve([("rollout_plan", plan_id)])
    return ok(public(plan))


@bp.route("/rollout-plans/<plan_id>/start", methods=["POST"])
@endpoint(["ReleaseManager"])
def start_plan(plan_id):
    (plan,) = resolve([("rollout_plan", plan_id)])
    if plan["state"] != "SCHEDULED":
        fail("ERR_INVALID_ROLLOUT_STATE",
             "a %s plan cannot be started" % plan["state"])
    submission = get_row("submission", plan["submission_id"])
    if submission is None or submission["state"] != "APPROVED":
        fail("ERR_INVALID_SUBMISSION_STATE",
             "the cited build is no longer APPROVED")
    app = get_row("app_record", plan["app_record_id"])
    flows.posture_gate(app, release_advancing=True)
    account = calc.account_of_app(app)
    flows.program_gate(account)
    for other in calc.plans_of_app(app["id"]):
        if (other["id"] != plan["id"]
                and other["state"] in ("PHASE_ACTIVE", "PAUSED")):
            fail("ERR_ROLLOUT_WINDOW_CONFLICT",
                 "plan %s already occupies the release calendar" % other["id"])
    if now_dt() < parse_iso(plan["scheduled_start_at"]):
        fail("ERR_ROLLOUT_NOT_DUE",
             "the plan may not start before scheduled_start_at")
    if plan["mode"] == "PHASED":
        released, held_back = calc.share_pair(0)
        plan["state"] = "PHASE_ACTIVE"
        plan["phase_index"] = 0
        plan["phase_entered_at"] = now_iso()
        app["distribution_state"] = "PHASED_ROLLOUT"
    else:
        released, held_back = calc.share_pair(PHASE_COUNT - 1)
        plan["state"] = "COMPLETED"
        plan["phase_index"] = PHASE_COUNT - 1
        plan["completed_at"] = now_iso()
        app["distribution_state"] = "FULLY_RELEASED"
    plan["released_share_pct"] = released
    plan["held_back_share_pct"] = held_back
    touch(plan)
    _mirror_shares(app, released, held_back)
    app["live_submission_id"] = plan["submission_id"]
    touch(app)
    if plan["state"] == "COMPLETED" and account is not None:
        calc.recompute_account_standing(account)
    return ok(public(plan))


@bp.route("/rollout-plans/<plan_id>/advance", methods=["POST"])
@endpoint(["ReleaseManager"])
def advance_plan(plan_id):
    (plan,) = resolve([("rollout_plan", plan_id)])
    body = body_json()
    check_unknown(body, {"to_phase_index"})
    to_phase_index = req_int(body, "to_phase_index", 0)
    if plan["state"] != "PHASE_ACTIVE":
        fail("ERR_INVALID_ROLLOUT_STATE",
             "a %s plan cannot be advanced" % plan["state"])
    app = get_row("app_record", plan["app_record_id"])
    flows.posture_gate(app, release_advancing=True)
    account = calc.account_of_app(app)
    flows.program_gate(account)
    if (to_phase_index != plan["phase_index"] + 1
            or to_phase_index > PHASE_COUNT - 1):
        fail("ERR_PHASE_SEQUENCE_INVALID",
             "to_phase_index must be exactly one greater and at most %d"
             % (PHASE_COUNT - 1))
    entered_at = parse_iso(plan.get("phase_entered_at"))
    if entered_at is not None and now_dt() < entered_at + hours(MIN_PHASE_DWELL_HOURS):
        fail("ERR_PHASE_DWELL_NOT_MET",
             "the %d-hour phase dwell has not elapsed" % MIN_PHASE_DWELL_HOURS)
    released, held_back = calc.share_pair(to_phase_index)
    plan["phase_index"] = to_phase_index
    plan["phase_entered_at"] = now_iso()
    plan["released_share_pct"] = released
    plan["held_back_share_pct"] = held_back
    if to_phase_index == PHASE_COUNT - 1:
        plan["state"] = "COMPLETED"
        plan["completed_at"] = now_iso()
        app["distribution_state"] = "FULLY_RELEASED"
    touch(plan)
    _mirror_shares(app, released, held_back)
    touch(app)
    if plan["state"] == "COMPLETED" and account is not None:
        calc.recompute_account_standing(account)
    return ok(public(plan))


@bp.route("/rollout-plans/<plan_id>/hold", methods=["POST"])
@endpoint(["ReleaseManager", "PlatformPolicyAdmin"])
def hold_plan(plan_id):
    (plan,) = resolve([("rollout_plan", plan_id)])
    body = body_json()
    check_unknown(body, {"action", "pause_reason_code"})
    action = req_str(body, "action", enum={"PAUSE", "RESUME"})
    pause_reason_code = opt_str(body, "pause_reason_code", 1, 80)
    required = "PHASE_ACTIVE" if action == "PAUSE" else "PAUSED"
    if plan["state"] != required:
        fail("ERR_INVALID_ROLLOUT_STATE",
             "action %s is not declared for a %s plan" % (action, plan["state"]))
    app = get_row("app_record", plan["app_record_id"])
    flows.posture_gate(app, release_advancing=(action == "RESUME"))
    if action == "PAUSE":
        plan["state"] = "PAUSED"
        plan["pause_reason_code"] = pause_reason_code
        app["distribution_state"] = "PAUSED"
    else:
        plan["state"] = "PHASE_ACTIVE"
        plan["pause_reason_code"] = None
        plan["phase_entered_at"] = now_iso()
        app["distribution_state"] = "PHASED_ROLLOUT"
    touch(plan)
    touch(app)
    return ok(public(plan))


@bp.route("/rollout-plans/<plan_id>/rollback", methods=["POST"])
@endpoint(["ReleaseManager", "PlatformPolicyAdmin"])
def rollback_plan(plan_id):
    (plan,) = resolve([("rollout_plan", plan_id)])
    body = body_json()
    check_unknown(body, {"rollback_reason_code", "halt_distribution"})
    reason_code = req_str(body, "rollback_reason_code", 1, 80)
    halt = req_bool(body, "halt_distribution")
    if plan["state"] not in ("PHASE_ACTIVE", "PAUSED", "COMPLETED"):
        fail("ERR_INVALID_ROLLOUT_STATE",
             "a %s plan cannot be rolled back" % plan["state"])
    app = get_row("app_record", plan["app_record_id"])
    account = calc.account_of_app(app)
    if app["distribution_state"] not in ("PHASED_ROLLOUT", "FULLY_RELEASED",
                                        "PAUSED"):
        fail("ERR_APP_NOT_DISTRIBUTED",
             "nothing can be rolled back before the app has been distributed")
    # §3.3 declares exactly one distribution edge per rollback flavour: PHASED_ROLLOUT ->
    # ROLLED_BACK on a halting rollback and PAUSED -> NOT_DISTRIBUTED on a non-halting one.
    # Driving the dimension along an undeclared edge is ERR_INVALID_DISTRIBUTION_STATE.
    if not halt and app["distribution_state"] != "PAUSED":
        fail("ERR_INVALID_DISTRIBUTION_STATE",
             "a non-halting rollback may only drive PAUSED to NOT_DISTRIBUTED, not %s"
             % app["distribution_state"])
    released, held_back = calc.zero_share()
    plan["state"] = "ROLLED_BACK"
    plan["released_share_pct"] = released
    plan["held_back_share_pct"] = held_back
    plan["rollback_reason_code"] = reason_code
    plan["halt_distribution"] = halt
    plan["terminated_at"] = now_iso()
    touch(plan)
    _mirror_shares(app, released, held_back)
    app["rollback_count"] = app.get("rollback_count", 0) + 1
    app["live_submission_id"] = None
    app["distribution_state"] = "ROLLED_BACK" if halt else "NOT_DISTRIBUTED"
    touch(app)
    if halt:
        for item in rows("commerce_item"):
            if (item["app_record_id"] == app["id"]
                    and item["item_type"] == "EXTERNAL_PAYMENT_LINK"
                    and item["status"] == "APPROVED"):
                item["status"] = "REMOVED"
                touch(item)
    if account is not None:
        calc.recompute_account_standing(account)
    return ok(public(plan))
