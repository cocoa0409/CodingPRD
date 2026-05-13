"""Option Plan routes."""

from flask import Blueprint
from db import DB, new_id
from middleware import auth_required
from response import success_response, list_response
from errors import (
    raise_error,
    ERR_INVALID_REQUEST, ERR_PLAN_NOT_ACTIVE,
    ERR_PENDING_GRANTS_EXIST, ERR_OPEN_EXERCISES_EXIST,
)
from services.common import (
    init_common, bump_version, check_occ, get_body, get_or_404,
    get_pagination, paginate_list, sort_by_created_at_asc,
    require_string, require_enum, require_positive_int,
    require_iso_datetime,
)
from services.time_util import server_now, format_iso, parse_iso, add_seconds
from services.serializers import serialize_plan


bp = Blueprint("plans", __name__)

JURISDICTIONS = {"US", "UK", "CN", "SG"}


@bp.post("/option-plans")
@auth_required(["PlanAdministrator"])
def create_plan():
    body = get_body()
    name = require_string(body, "name")
    pool = body.get("pool_total_options")
    if not isinstance(pool, int) or isinstance(pool, bool) or pool < 1:
        raise_error(ERR_INVALID_REQUEST, "pool_total_options must be positive integer")
    jurisdiction = require_enum(body, "jurisdiction_code", JURISDICTIONS)

    pid = new_id()
    plan = {
        "id": pid,
        "name": name,
        "pool_total_options": pool,
        "jurisdiction_code": jurisdiction,
        "current_clock_ts": None,
        "status": "DRAFT",
    }
    init_common(plan)
    DB["option_plans"][pid] = plan
    return success_response(serialize_plan(plan), http_status=201)


@bp.get("/option-plans")
@auth_required(["PlanAdministrator", "BoardSecretary", "ShareholderRegistrar", "AuditViewer"])
def list_plans():
    from flask import request
    limit, offset = get_pagination()
    items = list(DB["option_plans"].values())
    status_f = request.args.get("status")
    if status_f:
        items = [p for p in items if p["status"] == status_f]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate_list(items, limit, offset)
    return list_response([serialize_plan(p) for p in sliced], total, limit, offset)


@bp.get("/option-plans/<plan_id>")
@auth_required(["PlanAdministrator", "BoardSecretary", "ShareholderRegistrar", "AuditViewer"])
def get_plan(plan_id):
    plan = get_or_404("option_plans", plan_id)
    return success_response(serialize_plan(plan))


@bp.post("/option-plans/<plan_id>/activate")
@auth_required(["PlanAdministrator"])
def activate_plan(plan_id):
    plan = get_or_404("option_plans", plan_id)
    body = get_body()
    check_occ(plan, body)
    if plan["status"] != "DRAFT":
        raise_error(ERR_PLAN_NOT_ACTIVE, "Plan not in DRAFT")
    if int(plan["pool_total_options"]) < 1:
        raise_error(ERR_INVALID_REQUEST, "pool_total_options must be >= 1")
    now_iso = body.get("now_iso")
    if now_iso is not None:
        dt = parse_iso(now_iso) if isinstance(now_iso, str) else None
        if dt is None:
            raise_error(ERR_INVALID_REQUEST, "now_iso must be ISO datetime")
        plan["current_clock_ts"] = format_iso(dt)
    else:
        plan["current_clock_ts"] = format_iso(server_now())
    plan["status"] = "ACTIVE"
    bump_version(plan)
    return success_response(serialize_plan(plan))


@bp.post("/option-plans/<plan_id>/close")
@auth_required(["PlanAdministrator"])
def close_plan(plan_id):
    plan = get_or_404("option_plans", plan_id)
    body = get_body()
    check_occ(plan, body)
    if plan["status"] != "ACTIVE":
        raise_error(ERR_PLAN_NOT_ACTIVE, "Plan not in ACTIVE")
    # Check pending grants
    pending_grant_states = {"DRAFT", "BOARD_APPROVED", "SHAREHOLDER_APPROVED"}
    for g in DB["grants"].values():
        if g["plan_id"] == plan_id and g["status"] in pending_grant_states:
            raise_error(ERR_PENDING_GRANTS_EXIST, "Plan has pending grants")
    # Check open exercise applications
    open_app_states = {"SUBMITTED", "ELIGIBILITY_VERIFIED", "PAYMENT_RECEIVED", "TAX_WITHHELD"}
    for a in DB["exercise_applications"].values():
        if a["plan_id"] == plan_id and a["status"] in open_app_states:
            raise_error(ERR_OPEN_EXERCISES_EXIST, "Plan has open exercise applications")
    plan["status"] = "CLOSED"
    bump_version(plan)
    # Mark windows so the next sweep flips them to CLOSED.
    # We implement this by setting an internal flag — the actual sweep route handles transition.
    plan["_close_pending_sweep"] = True
    return success_response(serialize_plan(plan))


@bp.post("/option-plans/<plan_id>/clock/advance")
@auth_required(["PlanAdministrator"])
def advance_clock(plan_id):
    plan = get_or_404("option_plans", plan_id)
    body = get_body()
    check_occ(plan, body)
    if plan["status"] != "ACTIVE":
        raise_error(ERR_PLAN_NOT_ACTIVE, "Plan not in ACTIVE")
    by_seconds = body.get("by_seconds")
    if not isinstance(by_seconds, int) or isinstance(by_seconds, bool):
        raise_error(ERR_INVALID_REQUEST, "by_seconds must be an integer")
    if plan.get("current_clock_ts") is None:
        raise_error(ERR_INVALID_REQUEST, "Plan clock not initialized")
    cur = parse_iso(plan["current_clock_ts"])
    new_ts = add_seconds(cur, by_seconds)
    plan["current_clock_ts"] = format_iso(new_ts)
    bump_version(plan)
    # On clock advance: re-evaluate frozen grants — auto-unfreeze when no blackout overlaps.
    _auto_unfreeze_grants(plan)
    return success_response(serialize_plan(plan))


def _auto_unfreeze_grants(plan):
    """Flip FROZEN grants under this plan to LIVE when no active blackout overlaps clock."""
    clock = parse_iso(plan["current_clock_ts"])
    if clock is None:
        return
    active_blackouts = _active_blackouts(plan, clock)
    if active_blackouts:
        return  # still blacked out
    for g in DB["grants"].values():
        if g["plan_id"] != plan["id"]:
            continue
        if g["status"] == "FROZEN":
            g["status"] = "LIVE"
            bump_version(g)


def _active_blackouts(plan, clock):
    out = []
    for ev in DB["corporate_events"].values():
        if ev["plan_id"] != plan["id"]:
            continue
        if ev["event_type"] not in ("EARNINGS_BLACKOUT", "MATERIAL_EVENT_BLACKOUT"):
            continue
        start = parse_iso(ev["effective_ts"])
        end = parse_iso(ev["blackout_end_ts"])
        if start <= clock < end:
            out.append(ev)
    return out
