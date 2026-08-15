"""EquipmentAsset (PRD 3.1)."""
from datetime import timedelta

from flask import Blueprint

from db import db, maintenance_windows
from errors import (
    raise_error, ERR_VALIDATION, ERR_INVALID_STATE, ERR_TEMPORAL_CONFLICT,
    ERR_REFERENCE_INVALID,
)
from helpers import (
    get_body, req_field, req_enum, opt_enum, stamp_new, get_or_404, touch,
)
from middleware import get_caller, check_role_allowed
from response import success_object
from routes.common import public
from services import core
from util import parse_datetime, fmt_datetime, CLOCK

bp = Blueprint("equipment", __name__)

EQUIP_CLASSES = {"OVEN", "STOVETOP", "COLD_HOLDING", "GENERAL"}
CRITICALITY = {"CRITICAL", "SUPPORT"}
KM = ["KitchenManager"]
BUFFER = timedelta(minutes=15)


def _asset_view(a):
    out = public(a)
    return out


@bp.route("/kitchen/equipment-assets", methods=["POST"])
def create_asset():
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager"])

    site_id = req_field(body, "site_id", str)
    name = req_field(body, "name", str)
    equipment_class = req_enum(body, "equipment_class", EQUIP_CLASSES)
    criticality = opt_enum(body, "criticality", CRITICALITY, "SUPPORT")

    if site_id not in db["sites"]:
        raise_error(ERR_REFERENCE_INVALID, f"site not found: {site_id}")

    rec = stamp_new({
        "site_id": site_id,
        "name": name,
        "equipment_class": equipment_class,
        "criticality": criticality,
        "last_inspected_at": None,
        "next_inspection_due": None,
        "status": "OPERATIONAL",
    })
    db["equipment_assets"][rec["id"]] = rec
    core.recompute_posture(site_id)
    return success_object(_asset_view(rec), 201)


@bp.route("/kitchen/equipment-assets/<aid>", methods=["GET"])
def get_asset(aid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Volunteer"])
    rec = get_or_404("equipment_assets", aid)
    return success_object(_asset_view(rec))


@bp.route("/kitchen/equipment-assets/<aid>/schedule-maintenance", methods=["POST"])
def schedule_maintenance(aid):
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    asset = get_or_404("equipment_assets", aid)

    m_start_s = req_field(body, "maint_start", str)
    m_end_s = req_field(body, "maint_end", str)
    try:
        m_start = parse_datetime(m_start_s)
        m_end = parse_datetime(m_end_s)
    except ValueError:
        raise_error(ERR_VALIDATION, "maint_start and maint_end must be ISO datetimes")
    if m_end <= m_start:
        raise_error(ERR_VALIDATION, "maint_end must be after maint_start")

    if asset["status"] != "OPERATIONAL":
        raise_error(ERR_INVALID_STATE,
                    f"cannot schedule maintenance from {asset['status']}")

    # Closed-interval + 15-minute buffer overlap against other IN_MAINTENANCE
    # records for the same equipment_class at the same site.
    for other_id, windows in maintenance_windows.items():
        other = db["equipment_assets"].get(other_id)
        if other is None or other_id == aid:
            continue
        if other["site_id"] != asset["site_id"]:
            continue
        if other["equipment_class"] != asset["equipment_class"]:
            continue
        if other["status"] != "IN_MAINTENANCE":
            continue
        for (ws, we) in windows:
            if (m_start - BUFFER) <= (we + BUFFER) and (ws - BUFFER) <= (m_end + BUFFER):
                raise_error(ERR_TEMPORAL_CONFLICT,
                            "maintenance window overlaps another in-maintenance window")

    asset["status"] = "IN_MAINTENANCE"
    touch(asset)
    maintenance_windows.setdefault(aid, []).append((m_start, m_end))
    core.recompute_posture(asset["site_id"])
    return success_object(_asset_view(asset))


def _stamp_inspection(asset):
    now = CLOCK.now()
    asset["last_inspected_at"] = fmt_datetime(now)
    asset["next_inspection_due"] = fmt_datetime(
        now + timedelta(days=core.INSPECTION_INTERVAL_DAYS)
    )


@bp.route("/kitchen/equipment-assets/<aid>/complete-maintenance", methods=["POST"])
def complete_maintenance(aid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    asset = get_or_404("equipment_assets", aid)
    if asset["status"] != "IN_MAINTENANCE":
        raise_error(ERR_INVALID_STATE,
                    f"cannot complete maintenance from {asset['status']}")
    asset["status"] = "OPERATIONAL"
    _stamp_inspection(asset)
    maintenance_windows.pop(aid, None)
    touch(asset)
    core.recompute_posture(asset["site_id"])
    return success_object(_asset_view(asset))


@bp.route("/kitchen/equipment-assets/<aid>/report-fault", methods=["POST"])
def report_fault(aid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, ["KitchenManager", "Volunteer"])
    asset = get_or_404("equipment_assets", aid)
    if asset["status"] != "OPERATIONAL":
        raise_error(ERR_INVALID_STATE,
                    f"cannot report fault from {asset['status']}")
    asset["status"] = "DOWN_FOR_REPAIR"
    touch(asset)
    core.recompute_posture(asset["site_id"])

    site = db["sites"].get(asset["site_id"])
    if site is not None and site.get("equipment_posture") == "HALTED":
        # Cascade: OPEN services at this site whose menu day has items requiring
        # this equipment_class are ABORTED; their pipeline orders are released.
        for svc in db["meal_services"].values():
            if svc["site_id"] != asset["site_id"] or svc["status"] != "OPEN":
                continue
            needs_class = any(
                i["menu_day_id"] == svc["menu_day_id"]
                and i["requires_equipment_class"] == asset["equipment_class"]
                and i["status"] in ("CONFIRMED", "SOLD_OUT")
                for i in db["menu_items"].values()
            )
            if not needs_class:
                continue
            svc["status"] = "ABORTED"
            touch(svc)
            for o in db["meal_orders"].values():
                if o["meal_service_id"] == svc["id"] and o["fulfillment_status"] == "RESERVED":
                    o["fulfillment_status"] = "RELEASED"
                    touch(o)
                    if svc["reserved_count"] > 0:
                        svc["reserved_count"] -= 1
            touch(svc)
    return success_object(_asset_view(asset))


@bp.route("/kitchen/equipment-assets/<aid>/complete-repair", methods=["POST"])
def complete_repair(aid):
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    asset = get_or_404("equipment_assets", aid)

    inspected = body.get("inspected", False) if isinstance(body, dict) else False
    if not isinstance(inspected, bool):
        raise_error(ERR_VALIDATION, "inspected must be a boolean")

    if asset["status"] != "DOWN_FOR_REPAIR":
        raise_error(ERR_INVALID_STATE,
                    f"cannot complete repair from {asset['status']}")

    # Inspection gating: within inspection interval OR inspected at close.
    within_interval = True
    if asset.get("next_inspection_due"):
        within_interval = CLOCK.now() <= parse_datetime(asset["next_inspection_due"])
    if not within_interval and not inspected:
        raise_error(ERR_INVALID_STATE,
                    "asset is past its inspection due; an inspection must be completed at repair close")

    if inspected:
        _stamp_inspection(asset)
    asset["status"] = "OPERATIONAL"
    touch(asset)
    core.recompute_posture(asset["site_id"])
    return success_object(_asset_view(asset))


@bp.route("/kitchen/equipment-assets/<aid>/decommission", methods=["POST"])
def decommission(aid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    asset = get_or_404("equipment_assets", aid)
    if asset["status"] != "DOWN_FOR_REPAIR":
        raise_error(ERR_INVALID_STATE,
                    f"cannot decommission from {asset['status']}")
    asset["status"] = "DECOMMISSIONED"
    touch(asset)
    core.recompute_posture(asset["site_id"])
    return success_object(_asset_view(asset))
