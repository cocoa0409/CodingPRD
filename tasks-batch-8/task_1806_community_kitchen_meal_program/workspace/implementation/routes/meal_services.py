"""MealService lifecycle (PRD 3.6)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_INVALID_STATE, ERR_CONSTRAINT_VIOLATION,
    ERR_TEMPORAL_CONFLICT, ERR_STALE_VERSION, ERR_EQUIPMENT_HALTED,
    ERR_SUPERVISOR_REQUIRED, ERR_REFERENCE_INVALID,
)
from helpers import (
    get_body, req_field, req_int, req_enum, opt_field, stamp_new, paginate,
    apply_filters, get_or_404, touch,
)
from middleware import get_caller, check_role_allowed
from response import success_object, success_list
from routes.common import public, public_list
from services import core
from util import parse_datetime, fmt_datetime, CLOCK

bp = Blueprint("meal_services", __name__)

MODELS = {"DINE_IN", "TO_GO", "DELIVERY"}
KM = ["KitchenManager"]


def _svc_view(s):
    out = public(s)
    out.pop("_window_start", None)
    out.pop("_window_end", None)
    return out


@bp.route("/kitchen/meal-services", methods=["POST"])
def create_service():
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)

    menu_day_id = req_field(body, "menu_day_id", str)
    service_model = req_enum(body, "service_model", MODELS)
    window_start_s = req_field(body, "window_start", str)
    window_end_s = req_field(body, "window_end", str)
    capacity = req_int(body, "capacity", minimum=1)
    requires_supervisor = opt_field(body, "requires_supervisor", bool, False)

    try:
        w_start = parse_datetime(window_start_s)
        w_end = parse_datetime(window_end_s)
    except ValueError:
        raise_error(ERR_VALIDATION, "window_start and window_end must be ISO datetimes")
    if w_end <= w_start:
        raise_error(ERR_VALIDATION, "window_end must be after window_start")

    md = db["menu_days"].get(menu_day_id)
    if md is None:
        raise_error(ERR_REFERENCE_INVALID, f"menu day not found: {menu_day_id}")
    site = db["sites"].get(md["site_id"])

    if site is not None and site["status"] == "CLOSED":
        raise_error(ERR_INVALID_STATE, "site is CLOSED and refuses new services")
    if md["status"] not in ("IN_PRODUCTION", "SERVING"):
        raise_error(ERR_INVALID_STATE,
                    f"MenuDay must be IN_PRODUCTION or SERVING, is {md['status']}")

    # Temporal: window conflicts (same site + model overlap; DINE_IN buffer vs TO_GO)
    if core.service_window_conflict(md["site_id"], service_model, w_start, w_end):
        raise_error(ERR_TEMPORAL_CONFLICT, "service window conflicts with an existing service")

    # Shape: capacity rules per model
    if site is not None:
        if service_model == "DINE_IN" and capacity > site["dine_in_capacity"]:
            raise_error(ERR_CONSTRAINT_VIOLATION,
                        "DINE_IN capacity exceeds site dine_in_capacity")
        if service_model == "TO_GO":
            minutes = (w_end - w_start).total_seconds() / 60
            slots = int(minutes // 30)
            if capacity > site["togo_capacity_per_window"] * slots:
                raise_error(ERR_CONSTRAINT_VIOLATION,
                            "TO_GO capacity exceeds togo_capacity_per_window * 30-min slots")

    rec = stamp_new({
        "menu_day_id": menu_day_id,
        "site_id": md["site_id"],
        "service_model": service_model,
        "window_start": fmt_datetime(w_start),
        "window_end": fmt_datetime(w_end),
        "_window_start": w_start,
        "_window_end": w_end,
        "capacity": capacity,
        "reserved_count": 0,
        "requires_supervisor": bool(requires_supervisor),
        "status": "PLANNED",
    })
    db["meal_services"][rec["id"]] = rec
    return success_object(_svc_view(rec), 201)


@bp.route("/kitchen/meal-services/<sid>", methods=["GET"])
def get_service(sid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Volunteer", "Guest"])
    rec = get_or_404("meal_services", sid)
    return success_object(_svc_view(rec))


@bp.route("/kitchen/meal-services/<sid>/meal-orders", methods=["GET"])
def list_service_orders(sid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Volunteer"])
    get_or_404("meal_services", sid)
    items = [o for o in db["meal_orders"].values() if o["meal_service_id"] == sid]
    items = apply_filters(items, request.args, ["fulfillment_status", "prep_status"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/meal-services/<sid>/open", methods=["POST"])
def open_service(sid):
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    svc = get_or_404("meal_services", sid)

    if svc["status"] != "PLANNED":
        raise_error(ERR_INVALID_STATE, f"cannot open from {svc['status']}")

    md = db["menu_days"].get(svc["menu_day_id"])
    if md is None:
        raise_error(ERR_REFERENCE_INVALID, "parent menu day missing")
    if md["status"] != "IN_PRODUCTION":
        raise_error(ERR_INVALID_STATE,
                    f"MenuDay must be IN_PRODUCTION to open a service, is {md['status']}")

    site = db["sites"].get(svc["site_id"])
    if site is not None and site.get("equipment_posture") == "HALTED":
        raise_error(ERR_EQUIPMENT_HALTED, "site equipment posture is HALTED")

    # Window conflicts re-checked at open time
    if core.service_window_conflict(svc["site_id"], svc["service_model"],
                                    svc["_window_start"], svc["_window_end"],
                                    exclude_id=svc["id"]):
        raise_error(ERR_TEMPORAL_CONFLICT, "service window conflicts with an existing service")

    if svc.get("requires_supervisor"):
        found = False
        for sh in db["volunteer_shifts"].values():
            if (sh["site_id"] == svc["site_id"]
                    and sh["role_on_shift"] == "SUPERVISOR_ON_DUTY"
                    and sh["status"] == "CHECKED_IN"
                    and core.shifts_overlap(sh["_starts_at"], sh["_ends_at"],
                                            svc["_window_start"], svc["_window_end"])):
                found = True
                break
        if not found:
            raise_error(ERR_SUPERVISOR_REQUIRED,
                        "no CHECKED_IN SUPERVISOR_ON_DUTY shift overlaps the window")

    if "expected_menu_day_version" in body:
        ev = body["expected_menu_day_version"]
        if not isinstance(ev, int) or isinstance(ev, bool):
            raise_error(ERR_VALIDATION, "expected_menu_day_version must be an integer")
        if ev != md["version"]:
            raise_error(ERR_STALE_VERSION,
                        "expected_menu_day_version does not match current version")

    svc["status"] = "OPEN"
    touch(svc)

    # First open carries the MenuDay IN_PRODUCTION -> SERVING
    if md["status"] == "IN_PRODUCTION":
        md["status"] = "SERVING"
        touch(md)

    return success_object(_svc_view(svc))


@bp.route("/kitchen/meal-services/<sid>/pause", methods=["POST"])
def pause_service(sid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    svc = get_or_404("meal_services", sid)
    if svc["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, f"cannot pause from {svc['status']}")
    svc["status"] = "PAUSED"
    touch(svc)
    return success_object(_svc_view(svc))


@bp.route("/kitchen/meal-services/<sid>/resume", methods=["POST"])
def resume_service(sid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    svc = get_or_404("meal_services", sid)
    if svc["status"] != "PAUSED":
        raise_error(ERR_INVALID_STATE, f"cannot resume from {svc['status']}")
    site = db["sites"].get(svc["site_id"])
    if site is not None and site.get("equipment_posture") == "HALTED":
        raise_error(ERR_EQUIPMENT_HALTED, "site equipment posture is HALTED")
    svc["status"] = "OPEN"
    touch(svc)
    return success_object(_svc_view(svc))


@bp.route("/kitchen/meal-services/<sid>/close", methods=["POST"])
def close_service(sid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    svc = get_or_404("meal_services", sid)
    if svc["status"] not in ("OPEN", "PAUSED"):
        raise_error(ERR_INVALID_STATE, f"cannot close from {svc['status']}")
    svc["status"] = "CLOSED"
    touch(svc)
    # Auto-expire all non-terminal orders; reserved_count decremented per order
    for o in db["meal_orders"].values():
        if o["meal_service_id"] == sid and o["fulfillment_status"] == "RESERVED":
            o["fulfillment_status"] = "EXPIRED"
            touch(o)
            if svc["reserved_count"] > 0:
                svc["reserved_count"] -= 1
    touch(svc)
    return success_object(_svc_view(svc))


@bp.route("/kitchen/meal-services/<sid>/abort", methods=["POST"])
def abort_service(sid):
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    svc = get_or_404("meal_services", sid)
    if svc["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, f"cannot abort from {svc['status']}")

    site = db["sites"].get(svc["site_id"])
    override = body.get("override", False) if isinstance(body, dict) else False
    if (site is None or site.get("equipment_posture") != "HALTED") and not override:
        raise_error(ERR_INVALID_STATE,
                    "abort requires HALTED posture or explicit manager override")

    svc["status"] = "ABORTED"
    touch(svc)
    for o in db["meal_orders"].values():
        if o["meal_service_id"] == sid and o["fulfillment_status"] == "RESERVED":
            o["fulfillment_status"] = "RELEASED"
            touch(o)
            if svc["reserved_count"] > 0:
                svc["reserved_count"] -= 1
    touch(svc)
    core.recompute_posture(svc["site_id"])
    return success_object(_svc_view(svc))
