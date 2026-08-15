"""MenuDay lifecycle (PRD 3.2, 3.8)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_INVALID_STATE, ERR_CONSTRAINT_VIOLATION,
    ERR_REFERENCE_INVALID, ERR_STALE_VERSION, ERR_EQUIPMENT_HALTED, ERR_NOT_FOUND,
)
from helpers import (
    get_body, req_field, opt_enum, stamp_new, paginate, apply_filters, get_or_404, touch,
)
from middleware import get_caller, check_role_allowed
from response import success_object, success_list
from routes.common import public, public_list
from services import core
from util import parse_date

bp = Blueprint("menu_days", __name__)

ALL = ["ProgramAdmin", "KitchenManager", "FoodSafetyOfficer", "Volunteer", "Guest"]
KM = ["KitchenManager"]


def _md_view(md):
    """MenuDay output; when reconciled, surface waste_ratio + alert flag."""
    out = public(md)
    out.pop("_service_date", None)
    if md["status"] == "RECONCILED":
        ratio = core.compute_waste_ratio(md["id"])
        out["waste_ratio"] = ratio
        out["overproduction_alert"] = bool(
            ratio is not None and ratio > float(core.WASTE_ALERT_THRESHOLD)
        )
    return out


@bp.route("/kitchen/menu-days", methods=["POST"])
def create_menu_day():
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)

    site_id = req_field(body, "site_id", str)
    service_date = req_field(body, "service_date", str)
    forecast_variant = opt_enum(body, "forecast_variant",
                                {"TRAILING_AVERAGE", "DOW_WEIGHTED"}, "TRAILING_AVERAGE")
    try:
        d = parse_date(service_date)
    except ValueError:
        raise_error(ERR_VALIDATION, "service_date must be an ISO date (YYYY-MM-DD)")

    site = db["sites"].get(site_id)
    if site is None:
        raise_error(ERR_REFERENCE_INVALID, f"site not found: {site_id}")
    if site["status"] == "CLOSED":
        raise_error(ERR_INVALID_STATE, "site is CLOSED")

    for m in db["menu_days"].values():
        if m["site_id"] == site_id and m["service_date"] == service_date:
            raise_error(ERR_CONSTRAINT_VIOLATION,
                        "a MenuDay already exists for this site and service_date")

    rec = stamp_new({
        "site_id": site_id,
        "service_date": service_date,
        "forecast_servings": None,
        "forecast_variant": forecast_variant,
        "committed_servings": 0,
        "served_count": 0,
        "overproduction_ratio": None,
        "status": "DRAFT",
    })
    db["menu_days"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/kitchen/menu-days", methods=["GET"])
def list_menu_days():
    caller = get_caller()
    check_role_allowed(caller, ALL)
    items = apply_filters(list(db["menu_days"].values()), request.args,
                          ["site_id", "status", "service_date"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list([_md_view(m) for m in page], total, limit, offset)


@bp.route("/kitchen/menu-days/<mid>", methods=["GET"])
def get_menu_day(mid):
    caller = get_caller()
    check_role_allowed(caller, ALL)
    rec = get_or_404("menu_days", mid)
    return success_object(_md_view(rec))


@bp.route("/kitchen/menu-days/<mid>/summary", methods=["GET"])
def menu_day_summary(mid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager"])
    md = get_or_404("menu_days", mid)
    out = _md_view(md)
    ratio = core.compute_waste_ratio(mid)
    cost = core.compute_cost_summary(md)
    out["forecast_servings"] = md["forecast_servings"]
    out["committed_servings"] = md["committed_servings"]
    out["served_count"] = md["served_count"]
    out["waste_ratio"] = ratio
    out["overproduction_alert"] = bool(
        ratio is not None and ratio > float(core.WASTE_ALERT_THRESHOLD)
    )
    out["total_cost_cents"] = cost["total_cost_cents"]
    out["cost_per_served_cents"] = cost["cost_per_served_cents"]
    return success_object(out)


@bp.route("/kitchen/menu-days/<mid>/menu-items", methods=["GET"])
def list_md_items(mid):
    caller = get_caller()
    check_role_allowed(caller, ALL)
    get_or_404("menu_days", mid)
    items = [i for i in db["menu_items"].values() if i["menu_day_id"] == mid]
    items = apply_filters(items, request.args, ["status"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/menu-days/<mid>/meal-services", methods=["GET"])
def list_md_services(mid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Volunteer", "Guest"])
    get_or_404("menu_days", mid)
    items = [s for s in db["meal_services"].values() if s["menu_day_id"] == mid]
    items = apply_filters(items, request.args, ["service_model", "status"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/menu-days/<mid>/waste-logs", methods=["GET"])
def list_md_waste(mid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "FoodSafetyOfficer"])
    get_or_404("menu_days", mid)
    items = [w for w in db["waste_logs"].values() if w["menu_day_id"] == mid]
    items = apply_filters(items, request.args, ["reason", "disposition"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/menu-days/<mid>/volunteer-shifts", methods=["GET"])
def list_md_shifts(mid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Volunteer"])
    get_or_404("menu_days", mid)
    items = [s for s in db["volunteer_shifts"].values() if s["menu_day_id"] == mid]
    items = apply_filters(items, request.args, ["status", "volunteer_id"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/menu-days/<mid>/lock-forecast", methods=["POST"])
def lock_forecast(mid):
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    md = get_or_404("menu_days", mid)

    if md["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"cannot lock forecast from {md['status']}")
    confirmed = [i for i in db["menu_items"].values()
                 if i["menu_day_id"] == mid and i["status"] == "CONFIRMED"]
    if not confirmed:
        raise_error(ERR_INVALID_STATE, "at least one MenuItem must be CONFIRMED")
    for a in db["batch_allocations"].values():
        if a.get("released"):
            continue
        item = db["menu_items"].get(a["menu_item_id"])
        if item is None or item["menu_day_id"] != mid:
            continue
        batch = db["food_batches"].get(a["food_batch_id"])
        if batch is None or batch["status"] != "ACCEPTED":
            raise_error(ERR_INVALID_STATE,
                        "all allocated FoodBatches must be ACCEPTED at lock time")

    if "expected_menu_day_version" in body:
        ev = body["expected_menu_day_version"]
        if not isinstance(ev, int) or isinstance(ev, bool):
            raise_error(ERR_VALIDATION, "expected_menu_day_version must be an integer")
        if ev != md["version"]:
            raise_error(ERR_STALE_VERSION,
                        "expected_menu_day_version does not match current version")

    core.run_production_forecast(md)
    md["status"] = "FORECAST_LOCKED"
    touch(md)
    return success_object(_md_view(md))


@bp.route("/kitchen/menu-days/<mid>/start-production", methods=["POST"])
def start_production(mid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    md = get_or_404("menu_days", mid)

    if md["status"] != "FORECAST_LOCKED":
        raise_error(ERR_INVALID_STATE, f"cannot start production from {md['status']}")
    site = db["sites"].get(md["site_id"])
    if site is not None and site["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "site is not OPEN")
    if site is not None and site.get("equipment_posture") == "HALTED":
        raise_error(ERR_EQUIPMENT_HALTED, "site equipment posture is HALTED")

    md["status"] = "IN_PRODUCTION"
    touch(md)
    return success_object(_md_view(md))


@bp.route("/kitchen/menu-days/<mid>/reconcile", methods=["POST"])
def reconcile(mid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    md = get_or_404("menu_days", mid)

    if md["status"] != "SERVING":
        raise_error(ERR_INVALID_STATE, f"cannot reconcile from {md['status']}")
    services = [s for s in db["meal_services"].values() if s["menu_day_id"] == mid]
    for s in services:
        if s["status"] not in ("CLOSED", "ABORTED"):
            raise_error(ERR_INVALID_STATE, "all MealServices must be CLOSED or ABORTED")
    svc_ids = {s["id"] for s in services}
    for o in db["meal_orders"].values():
        if o["meal_service_id"] in svc_ids and o["fulfillment_status"] not in (
                "SERVED", "DELIVERED", "RELEASED", "EXPIRED"):
            raise_error(ERR_INVALID_STATE,
                        "all MealOrders must be in a terminal fulfillment state")

    ratio = core.compute_waste_ratio(mid)
    md["waste_ratio"] = ratio
    md["overproduction_alert"] = bool(
        ratio is not None and ratio > float(core.WASTE_ALERT_THRESHOLD)
    )
    md["status"] = "RECONCILED"
    touch(md)
    return success_object(_md_view(md))


@bp.route("/kitchen/menu-days/<mid>/cancel", methods=["POST"])
def cancel_menu_day(mid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    md = get_or_404("menu_days", mid)

    if md["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"cannot cancel from {md['status']}")
    for s in db["meal_services"].values():
        if s["menu_day_id"] == mid and s["status"] in ("OPEN", "PAUSED"):
            raise_error(ERR_INVALID_STATE,
                        "a MealService under this MenuDay is OPEN or PAUSED")

    # Cascade: items PLANNED/CONFIRMED -> UNAVAILABLE; release allocations
    for item in db["menu_items"].values():
        if item["menu_day_id"] != mid:
            continue
        if item["status"] in ("PLANNED", "CONFIRMED"):
            if item["status"] == "CONFIRMED":
                md["committed_servings"] -= item["planned_servings"]
            item["status"] = "UNAVAILABLE"
            touch(item)
            for a in db["batch_allocations"].values():
                if a["menu_item_id"] == item["id"] and not a.get("released"):
                    a["released"] = True
                    batch = db["food_batches"].get(a["food_batch_id"])
                    if batch is not None:
                        core.recalc_batch_remaining(batch)
    # Cascade: shifts SCHEDULED -> CANCELLED
    for s in db["volunteer_shifts"].values():
        if s["menu_day_id"] == mid and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)

    core.recompute_overproduction(md)
    md["status"] = "CANCELLED"
    touch(md)
    return success_object(_md_view(md))
