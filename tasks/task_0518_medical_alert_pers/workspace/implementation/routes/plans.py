"""MonitoringPlan endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_auth, require_role
from models import new_record, touch, serialize_plan
from response import object_response, array_response
from services.lookup import get_plan
from util import (get_json_body, require_fields, require_enum, require_nonneg_int,
                  parse_pagination, paginate, sort_by_created)

bp = Blueprint("plans", __name__)

PLAN_TIERS = {"BASIC", "PLUS", "PREMIUM"}


@bp.route("/pers/monitoring-plans", methods=["POST"])
def create_plan():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, [
        "tier", "monthly_fee_cents", "fall_detection_addon_cents",
        "included_test_interval_days", "response_sla_seconds",
        "early_termination_fee_cents", "min_commitment_months",
    ])
    require_enum(body["tier"], PLAN_TIERS, "tier")
    monthly = require_nonneg_int(body["monthly_fee_cents"], "monthly_fee_cents")
    addon = require_nonneg_int(body["fall_detection_addon_cents"], "fall_detection_addon_cents")
    interval = body["included_test_interval_days"]
    if not isinstance(interval, int) or isinstance(interval, bool) or interval < 1:
        raise err("ERR_INVALID_REQUEST", "included_test_interval_days must be >= 1")
    sla = body["response_sla_seconds"]
    if not isinstance(sla, int) or isinstance(sla, bool) or sla < 1:
        raise err("ERR_INVALID_REQUEST", "response_sla_seconds must be >= 1")
    etf = require_nonneg_int(body["early_termination_fee_cents"], "early_termination_fee_cents")
    commit = require_nonneg_int(body["min_commitment_months"], "min_commitment_months")

    # tier unique among non-archived plans (priority 16)
    for p in store.monitoring_plans.values():
        if not p["archived"] and p["tier"] == body["tier"]:
            raise err("ERR_DUPLICATE", "Tier already exists among non-archived plans")

    r = new_record()
    r.update({
        "tier": body["tier"],
        "monthly_fee_cents": monthly,
        "fall_detection_addon_cents": addon,
        "included_test_interval_days": interval,
        "response_sla_seconds": sla,
        "early_termination_fee_cents": etf,
        "min_commitment_months": commit,
        "archived": False,
    })
    store.monitoring_plans[r["id"]] = r
    return object_response(serialize_plan(r), 201)


@bp.route("/pers/monitoring-plans", methods=["GET"])
def list_plans():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    limit, offset = parse_pagination()
    items = list(store.monitoring_plans.values())
    if "archived" in request.args:
        raw = request.args.get("archived")
        if raw.lower() in ("true", "1"):
            want = True
        elif raw.lower() in ("false", "0"):
            want = False
        else:
            raise err("ERR_INVALID_REQUEST", "archived must be boolean")
        items = [p for p in items if p["archived"] == want]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return array_response([serialize_plan(p) for p in page], limit, offset, total)


@bp.route("/pers/monitoring-plans/<pid>", methods=["GET"])
def get_plan_route(pid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    r = get_plan(pid)
    return object_response(serialize_plan(r), 200)


@bp.route("/pers/monitoring-plans/<pid>/archive", methods=["POST"])
def archive_plan(pid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    r = get_plan(pid)
    r["archived"] = True
    touch(r)
    return object_response(serialize_plan(r), 200)
