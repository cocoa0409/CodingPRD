"""CCP observation + deviation endpoints."""

from flask import Blueprint, request

from db import store, new_id
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from validation import get_body, req_number, req_string
from errors import (raise_error, ERR_NOT_FOUND, ERR_NO_OPEN_PRODUCTION_DAY,
                    ERR_PLAN_NOT_EFFECTIVE, ERR_DEVIATION_INVALID_STATE,
                    ERR_SEGREGATION_OF_DUTIES_VIOLATION)
from serializers import observation_out, deviation_out
from services import touch, recompute_plant_scores, recompute_day_posture

bp = Blueprint("observations_deviations", __name__)

READ_ROLES = ("PlantAdmin", "QAManager", "QATech", "LabAnalyst", "Inspector", "ProductionManager")


@bp.route("/ccps/<cid>/observations", methods=["POST"])
def record_observation(cid):
    user_id, _ = require_roles("QATech")
    body = get_body()
    observed_value_f = req_number(body, "observed_value_f")
    ccp = store.ccps.get(cid)
    if not ccp:
        raise_error(ERR_NOT_FOUND, "CCP not found")
    plan = store.haccp_plans[ccp["haccp_plan_id"]]
    plant_id = plan["plant_id"]

    # Business gate 1: an OPEN production day must exist for the plant on the current clock date
    now = store.now()
    today = now.strftime("%Y-%m-%d")
    open_day = None
    for day in store.production_days.values():
        if day["plant_id"] == plant_id and day["status"] == "OPEN" and day["production_date"] == today:
            open_day = day
            break
    if not open_day:
        raise_error(ERR_NO_OPEN_PRODUCTION_DAY, "No OPEN production day for the plant on the current date")

    # Business gate 2: the CCP's plan must be EFFECTIVE
    if plan["status"] != "EFFECTIVE":
        raise_error(ERR_PLAN_NOT_EFFECTIVE, "The CCP's HACCP plan is not EFFECTIVE")

    # Compute within_limit with inclusive bounds
    within = True
    if ccp["critical_limit_min_f"] is not None and observed_value_f < ccp["critical_limit_min_f"]:
        within = False
    if ccp["critical_limit_max_f"] is not None and observed_value_f > ccp["critical_limit_max_f"]:
        within = False

    now_iso = store.now_iso()
    obs = {
        "id": new_id(),
        "ccp_id": cid,
        "production_day_id": open_day["id"],
        "monitor_user_id": user_id,
        "observed_value_f": observed_value_f,
        "within_limit": within,
        "deviation_id": None,
        "created_at": now_iso,
    }
    store.observations[obs["id"]] = obs

    if not within:
        # Spawn Deviation in OPEN, copy severity from CCP
        dv = {
            "id": new_id(),
            "ccp_id": cid,
            "production_day_id": open_day["id"],
            "observation_id": obs["id"],
            "severity": ccp["deviation_severity"],
            "corrective_action_note": None,
            "action_logged_by": None,
            "verified_by": None,
            "status": "OPEN",
            "created_at": now_iso,
            "updated_at": now_iso,
            "version": 1,
        }
        store.deviations[dv["id"]] = dv
        obs["deviation_id"] = dv["id"]
        recompute_plant_scores(plant_id)
        recompute_day_posture(open_day["id"])

    return success_object(observation_out(obs), 201)


@bp.route("/observations/<oid>", methods=["GET"])
def get_observation(oid):
    require_roles(*READ_ROLES)
    obs = store.observations.get(oid)
    if not obs:
        raise_error(ERR_NOT_FOUND, "Observation not found")
    return success_object(observation_out(obs))


@bp.route("/observations", methods=["GET"])
def list_observations():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    ccp_id = request.args.get("ccp_id")
    day_id = request.args.get("production_day_id")
    within = request.args.get("within_limit")
    items = sorted(store.observations.values(), key=lambda o: (o["created_at"], o["id"]))
    if ccp_id is not None:
        items = [o for o in items if o["ccp_id"] == ccp_id]
    if day_id is not None:
        items = [o for o in items if o["production_day_id"] == day_id]
    if within is not None:
        w = within.lower() == "true"
        items = [o for o in items if o["within_limit"] == w]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([observation_out(o) for o in page], limit, offset, total)


@bp.route("/deviations/<did>", methods=["GET"])
def get_deviation(did):
    require_roles(*READ_ROLES)
    dv = store.deviations.get(did)
    if not dv:
        raise_error(ERR_NOT_FOUND, "Deviation not found")
    return success_object(deviation_out(dv))


@bp.route("/deviations", methods=["GET"])
def list_deviations():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    ccp_id = request.args.get("ccp_id")
    day_id = request.args.get("production_day_id")
    obs_id = request.args.get("observation_id")
    status = request.args.get("status")
    items = sorted(store.deviations.values(), key=lambda d: (d["created_at"], d["id"]))
    if ccp_id is not None:
        items = [d for d in items if d["ccp_id"] == ccp_id]
    if day_id is not None:
        items = [d for d in items if d["production_day_id"] == day_id]
    if obs_id is not None:
        items = [d for d in items if d["observation_id"] == obs_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([deviation_out(d) for d in page], limit, offset, total)


@bp.route("/deviations/<did>/log-corrective-action", methods=["POST"])
def log_corrective_action(did):
    user_id, _ = require_roles("QAManager")
    body = get_body()
    note = req_string(body, "corrective_action_note")
    dv = store.deviations.get(did)
    if not dv:
        raise_error(ERR_NOT_FOUND, "Deviation not found")
    if dv["status"] != "OPEN":
        raise_error(ERR_DEVIATION_INVALID_STATE, "Deviation must be OPEN to log corrective action")
    dv["status"] = "ACTION_LOGGED"
    dv["corrective_action_note"] = note
    dv["action_logged_by"] = user_id
    touch(dv)
    day = store.production_days[dv["production_day_id"]]
    recompute_plant_scores(day["plant_id"])
    recompute_day_posture(day["id"])
    return success_object(deviation_out(dv))


@bp.route("/deviations/<did>/verify", methods=["POST"])
def verify_deviation(did):
    user_id, _ = require_roles("QAManager")
    get_body()
    dv = store.deviations.get(did)
    if not dv:
        raise_error(ERR_NOT_FOUND, "Deviation not found")
    if dv["status"] != "ACTION_LOGGED":
        raise_error(ERR_DEVIATION_INVALID_STATE, "Deviation must be ACTION_LOGGED to verify")
    obs = store.observations[dv["observation_id"]]
    if user_id == obs["monitor_user_id"] or user_id == dv["action_logged_by"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                    "Verifier must differ from the monitor and the action logger")
    dv["status"] = "VERIFIED"
    dv["verified_by"] = user_id
    touch(dv)
    day = store.production_days[dv["production_day_id"]]
    recompute_plant_scores(day["plant_id"])
    recompute_day_posture(day["id"])
    return success_object(deviation_out(dv))
