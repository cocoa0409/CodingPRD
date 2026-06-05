"""EscalationPolicy + EscalationTier creation/read; tier uniqueness."""
from flask import Blueprint, request

import response
from db import db
from errors import ApiError
from middleware import require_user_context, require_role, get_json_body, get_pagination
from services.common import require_str, require_int, optional_int, stamp_create
from services.lookups import get_policy, get_schedule, get_service, get_tier
from services.serializers import policy_out, tier_out, incident_out

bp = Blueprint("policies", __name__)

ADMIN_IC = {"PlatformAdmin", "IncidentCommander"}


# ---------------- EscalationPolicy ----------------

@bp.route("/escalation-policies", methods=["POST"])
def create_policy():
    _, role = require_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    name = require_str(body, "name")
    service_id = require_str(body, "service_id")
    with db.lock:
        get_service(service_id)
        repeat_rounds = optional_int(body, "repeat_rounds", 1, minimum=0)
        rec = stamp_create({
            "name": name,
            "service_id": service_id,
            "repeat_rounds": repeat_rounds,
        })
        db.policies[rec["id"]] = rec
    return response.success(policy_out(rec), 201)


@bp.route("/escalation-policies/<pid>", methods=["GET"])
def get_one_policy(pid):
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    with db.lock:
        p = get_policy(pid)
        return response.success(policy_out(p), 200)


@bp.route("/escalation-policies/<pid>/incidents", methods=["GET"])
def list_policy_incidents(pid):
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    limit, offset = get_pagination()
    with db.lock:
        get_policy(pid)
        rows = [i for i in db.incidents.values() if i["policy_id"] == pid]
        return response.list_response(rows, limit, offset, incident_out)


# ---------------- EscalationTier ----------------

@bp.route("/escalation-tiers", methods=["POST"])
def create_tier():
    _, role = require_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    policy_id = require_str(body, "policy_id")
    schedule_id = require_str(body, "schedule_id")
    with db.lock:
        get_policy(policy_id)
        get_schedule(schedule_id)
        tier_level = require_int(body, "tier_level", minimum=1)
        delay_minutes = require_int(body, "delay_minutes", minimum=0)
        # uniqueness (priority 13): tier_level unique within policy
        for t in db.tiers.values():
            if t["policy_id"] == policy_id and t["tier_level"] == tier_level:
                raise ApiError("ERR_DUPLICATE_TIER_LEVEL", "tier_level already used within the policy.")
        rec = stamp_create({
            "policy_id": policy_id,
            "schedule_id": schedule_id,
            "tier_level": tier_level,
            "delay_minutes": delay_minutes,
        })
        db.tiers[rec["id"]] = rec
    return response.success(tier_out(rec), 201)


@bp.route("/escalation-tiers", methods=["GET"])
def list_tiers():
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    limit, offset = get_pagination()
    policy_id = request.args.get("policy_id")
    schedule_id = request.args.get("schedule_id")
    with db.lock:
        rows = list(db.tiers.values())
        if policy_id is not None:
            rows = [r for r in rows if r["policy_id"] == policy_id]
        if schedule_id is not None:
            rows = [r for r in rows if r["schedule_id"] == schedule_id]
        return response.list_response(rows, limit, offset, tier_out)


@bp.route("/escalation-tiers/<tid>", methods=["GET"])
def get_one_tier(tid):
    _, role = require_user_context()
    require_role(role, ADMIN_IC)
    with db.lock:
        t = get_tier(tid)
        return response.success(tier_out(t), 200)
