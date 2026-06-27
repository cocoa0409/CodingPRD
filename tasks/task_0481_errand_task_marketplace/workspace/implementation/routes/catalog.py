"""Routes: logical clock, task categories, taskers, tasker-skills,
availability-windows, clients."""
from flask import Blueprint, request

import errors
from errors import err
from db import db, parse_iso, iso_millis
from middleware import get_caller, require_roles
from response import object_response, array_response
from services import core
from services import reqs

bp = Blueprint("catalog", __name__)


# =============================================================================
# Logical clock
# =============================================================================
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer"})
    data = reqs.body()
    raw = reqs.require(data, "to_iso8601")
    try:
        db.clock = parse_iso(raw)
    except (ValueError, TypeError):
        raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 instant")
    return object_response({}, status=200)


# =============================================================================
# TaskCategory
# =============================================================================
@bp.route("/task-categories", methods=["POST"])
def create_category():
    caller = get_caller()
    require_roles(caller, {"Dispatcher"})
    data = reqs.body()
    name = reqs.require_str(data, "name")
    pricing_model = reqs.require_enum(data, "pricing_model", {"HOURLY", "FIXED"})
    default_duration = reqs.require_int(data, "default_duration_minutes", minimum=15)
    requires_vetting = reqs.opt_bool(data, "requires_vetting", default=False)

    default_hourly = reqs.opt_int(data, "default_hourly_rate_cents", default=None, minimum=1000)
    fixed_price = reqs.opt_int(data, "fixed_price_cents", default=None, minimum=1000)
    if pricing_model == "HOURLY" and default_hourly is None:
        reqs.invalid("default_hourly_rate_cents required for HOURLY")
    if pricing_model == "FIXED" and fixed_price is None:
        reqs.invalid("fixed_price_cents required for FIXED")

    rec = {
        "name": name,
        "pricing_model": pricing_model,
        "default_hourly_rate_cents": default_hourly,
        "fixed_price_cents": fixed_price,
        "default_duration_minutes": default_duration,
        "requires_vetting": requires_vetting,
        "status": "ACTIVE",
    }
    core.stamp_create(rec)
    db.task_categories[rec["id"]] = rec
    return object_response(core.serialize(rec), status=201)


@bp.route("/task-categories", methods=["GET"])
def list_categories():
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    limit, offset = core.parse_pagination(request.args)
    window, meta = core.paginate(list(db.task_categories.values()), limit, offset)
    return array_response([core.serialize(c) for c in window], pagination=meta)


@bp.route("/task-categories/<cid>", methods=["GET"])
def get_category(cid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    c = core.get_category_or_404(cid)
    return object_response(core.serialize(c))


@bp.route("/task-categories/<cid>/retire", methods=["POST"])
def retire_category(cid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher"})
    c = core.get_category_or_404(cid)
    c["status"] = "RETIRED"
    core.touch(c)
    return object_response(core.serialize(c))


# =============================================================================
# Tasker
# =============================================================================
@bp.route("/taskers", methods=["POST"])
def create_tasker():
    caller = get_caller()
    require_roles(caller, {"Dispatcher"})
    data = reqs.body()
    full_name = reqs.require_str(data, "full_name")
    hourly_rate = reqs.require_int(data, "hourly_rate_cents", minimum=1000)
    rec = {
        "full_name": full_name,
        "hourly_rate_cents": hourly_rate,
        "status": "ACTIVE",
        "trust_score": 100,
        "incident_penalty_total": 0,
        "active_booking_count": 0,
        "completed_booking_count": 0,
        "rating_count": 0,
        "avg_rating": 0.0,
    }
    core.stamp_create(rec)
    db.taskers[rec["id"]] = rec
    return object_response(core.serialize_tasker(rec), status=201)


@bp.route("/taskers", methods=["GET"])
def list_taskers():
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client"})
    limit, offset = core.parse_pagination(request.args)
    window, meta = core.paginate(list(db.taskers.values()), limit, offset)
    return array_response([core.serialize_tasker(t) for t in window], pagination=meta)


@bp.route("/taskers/<tid>", methods=["GET"])
def get_tasker(tid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    t = core.get_tasker_or_404(tid)
    return object_response(core.serialize_tasker(t))


@bp.route("/taskers/<tid>/skills", methods=["GET"])
def list_tasker_skills_sub(tid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    core.get_tasker_or_404(tid)
    limit, offset = core.parse_pagination(request.args)
    items = [s for s in db.tasker_skills.values() if s["tasker_id"] == tid]
    window, meta = core.paginate(items, limit, offset)
    return array_response([core.serialize(s) for s in window], pagination=meta)


# =============================================================================
# TaskerSkill
# =============================================================================
@bp.route("/tasker-skills", methods=["POST"])
def create_skill():
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "Tasker"})
    data = reqs.body()
    tasker_id = reqs.require_str(data, "tasker_id")
    category_id = reqs.require_str(data, "category_id")
    # existence left-to-right
    tasker = core.get_tasker_or_404(tasker_id)
    category = core.get_category_or_404(category_id)
    # ownership for Tasker caller
    if caller.role == "Tasker" and caller.user_id != tasker_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Tasker may only declare own skill")
    # retired category admits no new skills
    if category["status"] == "RETIRED":
        raise err(errors.ERR_CATEGORY_RETIRED, "Category is retired")
    rec = {
        "tasker_id": tasker_id,
        "category_id": category_id,
        "vetting_status": "PENDING",
    }
    core.stamp_create(rec)
    db.tasker_skills[rec["id"]] = rec
    return object_response(core.serialize(rec), status=201)


@bp.route("/tasker-skills", methods=["GET"])
def list_skills():
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    limit, offset = core.parse_pagination(request.args)
    items = list(db.tasker_skills.values())
    tasker_id = request.args.get("tasker_id")
    category_id = request.args.get("category_id")
    if tasker_id is not None:
        items = [s for s in items if s["tasker_id"] == tasker_id]
    if category_id is not None:
        items = [s for s in items if s["category_id"] == category_id]
    window, meta = core.paginate(items, limit, offset)
    return array_response([core.serialize(s) for s in window], pagination=meta)


@bp.route("/tasker-skills/<sid>", methods=["GET"])
def get_skill(sid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    s = core.get_skill_or_404(sid)
    return object_response(core.serialize(s))


@bp.route("/tasker-skills/<sid>/vet", methods=["POST"])
def vet_skill(sid):
    caller = get_caller()
    require_roles(caller, {"TrustSafetyOfficer"})
    s = core.get_skill_or_404(sid)
    if s["vetting_status"] != "PENDING":
        raise err(errors.ERR_SKILL_INVALID_STATE, "Only PENDING skills may be vetted")
    category = db.task_categories.get(s["category_id"])
    if category is None or category["status"] != "ACTIVE":
        # category retired -> cannot vet
        raise err(errors.ERR_CATEGORY_RETIRED, "Category not ACTIVE")
    s["vetting_status"] = "VETTED"
    core.touch(s)
    return object_response(core.serialize(s))


@bp.route("/tasker-skills/<sid>/reject", methods=["POST"])
def reject_skill(sid):
    caller = get_caller()
    require_roles(caller, {"TrustSafetyOfficer"})
    s = core.get_skill_or_404(sid)
    if s["vetting_status"] not in ("PENDING", "VETTED"):
        raise err(errors.ERR_SKILL_INVALID_STATE, "Only PENDING/VETTED skills may be rejected")
    s["vetting_status"] = "REJECTED"
    core.touch(s)
    return object_response(core.serialize(s))


# =============================================================================
# AvailabilityWindow
# =============================================================================
@bp.route("/availability-windows", methods=["POST"])
def create_window():
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "Tasker"})
    data = reqs.body()
    tasker_id = reqs.require_str(data, "tasker_id")
    tasker = core.get_tasker_or_404(tasker_id)
    if caller.role == "Tasker" and caller.user_id != tasker_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Tasker may only create own window")
    start_raw = reqs.require(data, "window_start")
    end_raw = reqs.require(data, "window_end")
    try:
        start_dt = parse_iso(start_raw)
        end_dt = parse_iso(end_raw)
    except (ValueError, TypeError):
        reqs.invalid("window_start/window_end must be ISO 8601 instants")
    if not end_dt > start_dt:
        reqs.invalid("window_end must be strictly after window_start")
    rec = {
        "tasker_id": tasker_id,
        "window_start": iso_millis(start_dt),
        "window_end": iso_millis(end_dt),
        "status": "OPEN",
        "_window_start_dt": start_dt,
        "_window_end_dt": end_dt,
    }
    core.stamp_create(rec)
    db.availability_windows[rec["id"]] = rec
    return object_response(core.serialize(rec), status=201)


@bp.route("/availability-windows", methods=["GET"])
def list_windows():
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    limit, offset = core.parse_pagination(request.args)
    items = list(db.availability_windows.values())
    tasker_id = request.args.get("tasker_id")
    if tasker_id is not None:
        items = [w for w in items if w["tasker_id"] == tasker_id]
    window, meta = core.paginate(items, limit, offset)
    return array_response([core.serialize(w) for w in window], pagination=meta)


@bp.route("/availability-windows/<wid>", methods=["GET"])
def get_window(wid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client", "Tasker"})
    w = core.get_window_or_404(wid)
    return object_response(core.serialize(w))


@bp.route("/availability-windows/<wid>/close", methods=["POST"])
def close_window(wid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "Tasker"})
    w = core.get_window_or_404(wid)
    if caller.role == "Tasker" and caller.user_id != w["tasker_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Tasker may only close own window")
    w["status"] = "CLOSED"
    core.touch(w)
    return object_response(core.serialize(w))


# =============================================================================
# Client
# =============================================================================
@bp.route("/clients", methods=["POST"])
def create_client():
    caller = get_caller()
    require_roles(caller, {"Dispatcher"})
    data = reqs.body()
    full_name = reqs.require_str(data, "full_name")
    rec = {"full_name": full_name, "wallet_credit_cents": 0}
    core.stamp_create(rec)
    db.clients[rec["id"]] = rec
    return object_response(core.serialize(rec), status=201)


@bp.route("/clients", methods=["GET"])
def list_clients():
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer"})
    limit, offset = core.parse_pagination(request.args)
    window, meta = core.paginate(list(db.clients.values()), limit, offset)
    return array_response([core.serialize(c) for c in window], pagination=meta)


@bp.route("/clients/<cid>", methods=["GET"])
def get_client(cid):
    caller = get_caller()
    require_roles(caller, {"Dispatcher", "TrustSafetyOfficer", "Client"})
    c = core.get_client_or_404(cid)
    if caller.role == "Client" and caller.user_id != cid:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Client may only read own record")
    return object_response(core.serialize(c))
