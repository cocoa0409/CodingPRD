"""ServicePlan endpoints (PRD 3.9).

Cyclic seasonal loop: ACTIVE -> ADJUSTING -> ACTIVE (season_cycle_count++).
Cancellation refunds via the dual-variant calc (PRORATED / FORFEIT).
"""

from flask import Blueprint

from clock import clock
from common import (
    get_json_body,
    iso_format,
    paginate,
    parse_iso8601,
    require_bool,
    require_enum,
    require_fields,
    require_int_ge,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_project, get_service_plan
from middleware import get_auth, require_role
from response import success
from services.calc import elapsed_days, service_plan_refund
from services.serialize import ser_service_plan

bp = Blueprint("service_plans", __name__)

READ_ROLES = {"OperationsAdmin", "Customer", "InstallTech"}
TIERS = {"BASIC", "PREMIUM"}


@bp.post("/service-plans")
def create_service_plan():
    _, role = get_auth()
    require_role(role, {"OperationsAdmin", "Customer"})
    body = get_json_body()
    require_fields(body, ["project_id", "tier", "annual_fee_cents"])
    project_id = require_string(body, "project_id")
    tier = require_enum(body, "tier", TIERS)
    annual_fee_cents = require_int_ge(body, "annual_fee_cents", 0)
    refundable = require_bool(body, "refundable", False)
    get_project(project_id)

    record = stamp_new(
        {
            "project_id": project_id,
            "tier": tier,
            "annual_fee_cents": annual_fee_cents,
            "refundable": refundable,
            "activated_at": None,
            "season_cycle_count": 0,
            "status": "PENDING",
        }
    )
    record["_activated_dt"] = None
    db.service_plans[record["id"]] = record
    return success(ser_service_plan(record), status=201)


@bp.get("/service-plans/<sid>")
def read_service_plan(sid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    s = get_service_plan(sid)
    return success(ser_service_plan(s), status=200)


@bp.get("/projects/<pid>/service-plans")
def list_project_service_plans(pid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_project(pid)
    items = [s for s in db.service_plans.values() if s["project_id"] == pid]
    data, pagination = paginate(items, ser_service_plan)
    return success(data, status=200, pagination=pagination)


@bp.post("/service-plans/<sid>/activate")
def activate_service_plan(sid):
    _, role = get_auth()
    require_role(role, {"Customer"})
    s = get_service_plan(sid)
    if s["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Plan is not PENDING.")
    project = db.projects[s["project_id"]]
    if project["commercial_status"] != "INSTALLED":
        raise err("ERR_PROJECT_NOT_INSTALLED", "Project is not INSTALLED.")
    now = clock.now()
    s["status"] = "ACTIVE"
    s["activated_at"] = iso_format(now)
    s["_activated_dt"] = now
    touch(s)
    # Debit the customer's wallet by the annual fee.
    customer = db.customers.get(project["customer_id"])
    if customer is not None:
        customer["wallet_credit_cents"] -= s["annual_fee_cents"]
        touch(customer)
    return success(ser_service_plan(s), status=200)


@bp.post("/service-plans/<sid>/begin-seasonal-adjustment")
def begin_seasonal_adjustment(sid):
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    s = get_service_plan(sid)
    if s["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Plan is not ACTIVE.")
    s["status"] = "ADJUSTING"
    touch(s)
    return success(ser_service_plan(s), status=200)


@bp.post("/service-plans/<sid>/complete-seasonal-adjustment")
def complete_seasonal_adjustment(sid):
    _, role = get_auth()
    require_role(role, {"InstallTech"})
    s = get_service_plan(sid)
    if s["status"] != "ADJUSTING":
        raise err("ERR_INVALID_STATE", "Plan is not ADJUSTING.")
    s["status"] = "ACTIVE"
    s["season_cycle_count"] = s["season_cycle_count"] + 1
    touch(s)
    return success(ser_service_plan(s), status=200)


@bp.post("/service-plans/<sid>/cancel")
def cancel_service_plan(sid):
    _, role = get_auth()
    require_role(role, {"Customer"})
    s = get_service_plan(sid)
    if s["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Plan is not ACTIVE.")
    # Refund variant (PRORATED / FORFEIT).
    activated = s.get("_activated_dt")
    if activated is None:
        activated = parse_iso8601(s.get("activated_at"))
    days = elapsed_days(clock.now(), activated)
    _variant, refund = service_plan_refund(
        s["annual_fee_cents"], s["refundable"], days
    )
    s["status"] = "CANCELLED"
    touch(s)
    project = db.projects[s["project_id"]]
    customer = db.customers.get(project["customer_id"])
    if customer is not None and refund != 0:
        customer["wallet_credit_cents"] += refund
        touch(customer)
    return success(ser_service_plan(s), status=200)
