"""SalesConsultant, RoutePlan, and RouteStop endpoints."""

from flask import Blueprint, request

import errors as E
import middleware as M
import response as R
import services as S
from db import store, new_id, stamp_created, touch, clock_iso, dt_to_iso

bp = Blueprint("consultants_routes", __name__)

READ_ROLES = S.ALL_ROLES
WRITE_ROLES = {"SalesConsultant", "DistributionAdmin"}
COMMISSION_MODELS = {"STRAIGHT", "ACCELERATOR"}
CONSULTANT_STATES = {"ACTIVE", "INACTIVE"}


# ---------------------------------------------------------------------------
# SalesConsultant
# ---------------------------------------------------------------------------
@bp.post("/api/sales-consultants")
def create_consultant():
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"full_name", "territory_codes", "commission_model"})
    full_name = M.req_string(data, "full_name")
    territory_codes = M.req_str_array(data, "territory_codes", non_empty=True)
    commission_model = M.req_enum(data, "commission_model", COMMISSION_MODELS)
    M.require_role(ctx, {"DistributionAdmin"})
    consultant = {
        "id": new_id(),
        "full_name": full_name,
        "territory_codes": list(territory_codes),
        "commission_model": commission_model,
        "status": "ACTIVE",
        "commission_accrued_cents": 0,
        "commission_month": None,
        "commission_month_volume_cents": 0,
    }
    stamp_created(consultant)
    store.consultants[consultant["id"]] = consultant
    return R.success_object(S.pub(consultant), 201)


@bp.get("/api/sales-consultants/<cid>")
def get_consultant(cid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    return R.success_object(S.pub(S.get_consultant(cid)))


@bp.patch("/api/sales-consultants/<cid>")
def patch_consultant(cid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"status"})
    status = M.req_enum(data, "status", CONSULTANT_STATES)
    M.require_role(ctx, {"DistributionAdmin"})
    consultant = S.get_consultant(cid)
    consultant["status"] = status
    touch(consultant)
    return R.success_object(S.pub(consultant))


# ---------------------------------------------------------------------------
# RoutePlan
# ---------------------------------------------------------------------------
@bp.post("/api/route-plans")
def create_plan():
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"sales_consultant_id", "name"})
    consultant_id = M.req_string(data, "sales_consultant_id")
    name = M.req_string(data, "name")
    M.require_role(ctx, WRITE_ROLES)
    if ctx.role == "SalesConsultant" and consultant_id != ctx.user_id:
        raise E.forbidden()
    consultant = S.get_consultant(consultant_id)
    plan = {
        "id": new_id(),
        "sales_consultant_id": consultant["id"],
        "name": name,
        "status": "DRAFT",
    }
    stamp_created(plan)
    store.route_plans[plan["id"]] = plan
    return R.success_object(S.pub(plan), 201)


@bp.get("/api/route-plans")
def list_plans():
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    items = list(store.route_plans.values())
    sc_id = request.args.get("sales_consultant_id")
    if ctx.role == "SalesConsultant":
        if sc_id is not None and sc_id != ctx.user_id:
            raise E.forbidden()
        items = [p for p in items if p["sales_consultant_id"] == ctx.user_id]
    elif sc_id is not None:
        items = [p for p in items if p["sales_consultant_id"] == sc_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


@bp.get("/api/route-plans/<pid>")
def get_plan(pid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    plan = S.get_plan(pid)
    S.read_scope_plan(ctx, plan)
    return R.success_object(S.pub(plan))


@bp.post("/api/route-plans/<pid>/publish")
def publish_plan(pid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, WRITE_ROLES)
    plan = S.get_plan(pid)
    S.consultant_plan_scope(ctx, plan)
    if plan["status"] != "DRAFT":
        raise E.invalid_route_plan_state("Only a DRAFT plan can be published")
    if not any(s["status"] == "SCHEDULED" for s in S.stops_of_plan(plan["id"])):
        raise E.invalid_route_plan_state("Plan has no SCHEDULED stop")
    consultant = store.consultants.get(plan["sales_consultant_id"])
    if consultant is None or consultant["status"] != "ACTIVE":
        raise E.invalid_consultant_state("Plan's consultant must be ACTIVE")
    plan["status"] = "PUBLISHED"
    touch(plan)
    return R.success_object(S.pub(plan))


@bp.post("/api/route-plans/<pid>/unpublish")
def unpublish_plan(pid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, WRITE_ROLES)
    plan = S.get_plan(pid)
    S.consultant_plan_scope(ctx, plan)
    if plan["status"] != "PUBLISHED":
        raise E.invalid_route_plan_state("Only a PUBLISHED plan can be unpublished")
    if any(s["status"] == "COMPLETED" for s in S.stops_of_plan(plan["id"])):
        raise E.invalid_route_plan_state("Plan has COMPLETED stops")
    plan["status"] = "DRAFT"
    touch(plan)
    return R.success_object(S.pub(plan))


@bp.post("/api/route-plans/<pid>/stops")
def add_stop(pid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"salon_account_id", "start_at", "end_at"})
    salon_id = M.req_string(data, "salon_account_id")
    start_at = M.req_datetime(data, "start_at")
    end_at = M.req_datetime(data, "end_at")
    if not start_at < end_at:
        raise E.invalid_time_window("end_at must be strictly after start_at")
    M.require_role(ctx, WRITE_ROLES)
    plan = S.get_plan(pid)
    S.consultant_plan_scope(ctx, plan)
    salon = S.get_salon(salon_id)
    if plan["status"] != "DRAFT":
        raise E.invalid_route_plan_state("Stops can be added only to a DRAFT plan")
    if not S.buffer_ok(plan["id"], start_at, end_at):
        raise E.route_stop_buffer_violation()
    consultant = store.consultants.get(plan["sales_consultant_id"])
    if consultant is None or salon["territory_code"] not in consultant["territory_codes"]:
        raise E.consultant_territory_mismatch()
    stop = {
        "id": new_id(),
        "route_plan_id": plan["id"],
        "salon_account_id": salon["id"],
        "start_at": dt_to_iso(start_at),
        "end_at": dt_to_iso(end_at),
        "status": "SCHEDULED",
        "visited_at": None,
    }
    stamp_created(stop)
    store.route_stops[stop["id"]] = stop
    return R.success_object(S.pub(stop), 201)


# ---------------------------------------------------------------------------
# RouteStop
# ---------------------------------------------------------------------------
@bp.get("/api/route-stops")
def list_stops():
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    items = list(store.route_stops.values())
    plan_id = request.args.get("route_plan_id")
    salon_id = request.args.get("salon_account_id")
    if ctx.role == "SalesConsultant":
        own_plans = {p["id"] for p in store.route_plans.values()
                     if p["sales_consultant_id"] == ctx.user_id}
        if plan_id is not None and plan_id not in own_plans:
            if plan_id in store.route_plans:
                raise E.forbidden()
            items = []
        else:
            items = [s for s in items if s["route_plan_id"] in own_plans]
    elif ctx.role == "SalonBuyer":
        if salon_id is not None and salon_id != ctx.user_id:
            raise E.forbidden()
        items = [s for s in items if s["salon_account_id"] == ctx.user_id]
    if plan_id is not None:
        items = [s for s in items if s["route_plan_id"] == plan_id]
    if salon_id is not None:
        items = [s for s in items if s["salon_account_id"] == salon_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


@bp.get("/api/route-stops/<sid>")
def get_stop(sid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    stop = S.get_stop(sid)
    S.read_scope_stop(ctx, stop)
    return R.success_object(S.pub(stop))


def _load_stop_for_action(ctx, sid):
    stop = S.get_stop(sid)
    S.consultant_stop_scope(ctx, stop)
    return stop


def _require_plan_published(stop):
    plan = store.route_plans.get(stop["route_plan_id"])
    if plan is None or plan["status"] != "PUBLISHED":
        raise E.invalid_route_plan_state("Stop actions require a PUBLISHED plan")
    return plan


@bp.post("/api/route-stops/<sid>/complete")
def complete_stop(sid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, WRITE_ROLES)
    stop = _load_stop_for_action(ctx, sid)
    if stop["status"] != "SCHEDULED":
        raise E.invalid_route_stop_state("Only a SCHEDULED stop can be completed")
    plan = _require_plan_published(stop)
    stop["status"] = "COMPLETED"
    stop["visited_at"] = clock_iso()
    touch(stop)
    S.maybe_complete_plan(plan)
    return R.success_object(S.pub(stop))


@bp.post("/api/route-stops/<sid>/no-show")
def no_show_stop(sid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, WRITE_ROLES)
    stop = _load_stop_for_action(ctx, sid)
    if stop["status"] != "SCHEDULED":
        raise E.invalid_route_stop_state("Only a SCHEDULED stop can be marked NO_SHOW")
    _require_plan_published(stop)
    stop["status"] = "NO_SHOW"
    touch(stop)
    return R.success_object(S.pub(stop))


@bp.post("/api/route-stops/<sid>/reschedule")
def reschedule_stop(sid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"start_at", "end_at"})
    start_at = M.req_datetime(data, "start_at")
    end_at = M.req_datetime(data, "end_at")
    if not start_at < end_at:
        raise E.invalid_time_window("end_at must be strictly after start_at")
    M.require_role(ctx, WRITE_ROLES)
    stop = _load_stop_for_action(ctx, sid)
    if stop["status"] != "NO_SHOW":
        raise E.invalid_route_stop_state("Only a NO_SHOW stop can be rescheduled")
    _require_plan_published(stop)
    if not S.buffer_ok(stop["route_plan_id"], start_at, end_at, exclude_stop_id=stop["id"]):
        raise E.route_stop_buffer_violation()
    stop["start_at"] = dt_to_iso(start_at)
    stop["end_at"] = dt_to_iso(end_at)
    stop["status"] = "SCHEDULED"
    touch(stop)
    return R.success_object(S.pub(stop))


@bp.post("/api/route-stops/<sid>/cancel")
def cancel_stop(sid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, WRITE_ROLES)
    stop = _load_stop_for_action(ctx, sid)
    if stop["status"] not in ("SCHEDULED", "NO_SHOW"):
        raise E.invalid_route_stop_state("Only a SCHEDULED or NO_SHOW stop can be cancelled")
    plan = _require_plan_published(stop)
    stop["status"] = "CANCELLED"
    touch(stop)
    S.maybe_complete_plan(plan)
    return R.success_object(S.pub(stop))
