"""Installation and PunchItem routes (delivery + punch loop)."""
import re
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_user_context, require_role
from response import success, success_list
from helpers import (get_body, require_str, require_enum, parse_datetime,
                     parse_pagination, paginate, sort_by_created)
from models import _base_record, touch, serialize_installation, serialize_punch
from lookups import (get_project_in_shop, get_installation_in_project,
                     get_punch_in_installation)
from services import bubble_installation_complete

bp = Blueprint("install", __name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------
# Installation
# --------------------------------------------------------------------------
@bp.route("/shops/<shop_id>/projects/<project_id>/installations", methods=["POST"])
def create_installation(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"Installer", "ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    body = get_body()
    install_date = require_str(body, "install_date")
    if not _DATE_RE.match(install_date):
        raise err("ERR_INVALID_REQUEST", "install_date must be YYYY-MM-DD")
    window_start = parse_datetime(body, "window_start_utc")
    window_end = parse_datetime(body, "window_end_utc")
    if not (window_end > window_start):
        raise err("ERR_INVALID_REQUEST", "window_end_utc must be strictly after window_start_utc")

    # Aggregate daily capacity across the whole shop (non-cancelled installations).
    shop = store.shops[shop_id]
    shop_proj_ids = {pr["id"] for pr in store.projects.values() if pr["shop_id"] == shop_id}
    count = 0
    for inst in store.installations.values():
        if inst["project_id"] in shop_proj_ids and inst["install_date"] == install_date \
                and inst["status"] != "CANCELLED":
            count += 1
    if count >= shop["max_installs_per_day"]:
        raise err("ERR_INSTALL_CAPACITY_FULL", "Install capacity full for this date")

    rec = _base_record()
    rec.update({
        "project_id": project_id,
        "install_date": install_date,
        "window_start_utc": body["window_start_utc"],
        "window_end_utc": body["window_end_utc"],
        "status": "SCHEDULED",
    })
    store.installations[rec["id"]] = rec
    return success(serialize_installation(rec), 201)


@bp.route("/shops/<shop_id>/projects/<project_id>/installations/<installation_id>", methods=["GET"])
def get_installation(shop_id, project_id, installation_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Installer", "Customer"})
    i = get_installation_in_project(shop_id, project_id, installation_id)
    return success(serialize_installation(i), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/installations", methods=["GET"])
def list_installations(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Installer", "Customer"})
    get_project_in_shop(shop_id, project_id)
    limit, offset = parse_pagination()
    items = [i for i in store.installations.values() if i["project_id"] == project_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_installation(i) for i in page], limit, offset, total)


@bp.route("/shops/<shop_id>/projects/<project_id>/installations/<installation_id>/start", methods=["POST"])
def start_installation(shop_id, project_id, installation_id):
    _, role = get_user_context()
    require_role(role, {"Installer", "ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    i = get_installation_in_project(shop_id, project_id, installation_id)
    if i["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Installation is not SCHEDULED")
    if p["status"] != "READY_FOR_DELIVERY":
        raise err("ERR_PROJECT_NOT_READY", "Project is not READY_FOR_DELIVERY")
    i["status"] = "IN_PROGRESS"
    touch(i)
    return success(serialize_installation(i), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/installations/<installation_id>/walkthrough", methods=["POST"])
def walkthrough(shop_id, project_id, installation_id):
    _, role = get_user_context()
    require_role(role, {"Installer", "ShopManager", "ShopAdmin"})
    get_project_in_shop(shop_id, project_id)
    i = get_installation_in_project(shop_id, project_id, installation_id)
    if i["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Installation is not IN_PROGRESS")
    i["status"] = "PUNCH_PENDING"
    touch(i)
    return success(serialize_installation(i), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/installations/<installation_id>/reopen", methods=["POST"])
def reopen(shop_id, project_id, installation_id):
    _, role = get_user_context()
    require_role(role, {"Installer", "ShopManager", "ShopAdmin"})
    get_project_in_shop(shop_id, project_id)
    i = get_installation_in_project(shop_id, project_id, installation_id)
    if i["status"] != "PUNCH_PENDING":
        raise err("ERR_INVALID_STATE", "Installation is not PUNCH_PENDING")
    has_open = any(pi["installation_id"] == installation_id and pi["status"] == "OPEN"
                   for pi in store.punch_items.values())
    if not has_open:
        raise err("ERR_NOTHING_TO_REOPEN", "No open punch item to reopen")
    i["status"] = "IN_PROGRESS"
    touch(i)
    return success(serialize_installation(i), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/installations/<installation_id>/complete", methods=["POST"])
def complete_installation(shop_id, project_id, installation_id):
    _, role = get_user_context()
    require_role(role, {"Installer", "ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    i = get_installation_in_project(shop_id, project_id, installation_id)
    if i["status"] != "PUNCH_PENDING":
        raise err("ERR_INVALID_STATE", "Installation is not PUNCH_PENDING")
    for pi in store.punch_items.values():
        if pi["installation_id"] == installation_id and pi["severity"] == "MAJOR" \
                and pi["status"] == "OPEN":
            raise err("ERR_MAJOR_PUNCH_OPEN", "An open major punch item blocks completion")
    i["status"] = "COMPLETE"
    touch(i)
    # Bubble up to project: READY_FOR_DELIVERY -> INSTALLED, create RETAINAGE draw.
    if p["status"] == "READY_FOR_DELIVERY":
        bubble_installation_complete(p)
    return success(serialize_installation(i), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/installations/<installation_id>/cancel", methods=["POST"])
def cancel_installation(shop_id, project_id, installation_id):
    _, role = get_user_context()
    require_role(role, {"Installer", "ShopManager", "ShopAdmin"})
    get_project_in_shop(shop_id, project_id)
    i = get_installation_in_project(shop_id, project_id, installation_id)
    if i["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Installation is not SCHEDULED")
    i["status"] = "CANCELLED"
    touch(i)
    return success(serialize_installation(i), 200)


# --------------------------------------------------------------------------
# PunchItem
# --------------------------------------------------------------------------
@bp.route("/shops/<shop_id>/projects/<project_id>/installations/<installation_id>/punch-items", methods=["POST"])
def create_punch(shop_id, project_id, installation_id):
    _, role = get_user_context()
    require_role(role, {"Installer", "ShopManager", "ShopAdmin"})
    get_project_in_shop(shop_id, project_id)
    i = get_installation_in_project(shop_id, project_id, installation_id)
    body = get_body()
    description = require_str(body, "description")
    severity = require_enum(body, "severity", {"MINOR", "MAJOR"}, required=False, default="MINOR")

    rec = _base_record()
    rec.update({
        "installation_id": installation_id,
        "project_id": project_id,
        "description": description,
        "severity": severity,
        "status": "OPEN",
    })
    store.punch_items[rec["id"]] = rec
    return success(serialize_punch(rec), 201)


@bp.route("/shops/<shop_id>/projects/<project_id>/installations/<installation_id>/punch-items/<punch_id>", methods=["GET"])
def get_punch(shop_id, project_id, installation_id, punch_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Installer", "Customer"})
    pi = get_punch_in_installation(shop_id, project_id, installation_id, punch_id)
    return success(serialize_punch(pi), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/installations/<installation_id>/punch-items", methods=["GET"])
def list_punch_for_installation(shop_id, project_id, installation_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Installer", "Customer"})
    get_installation_in_project(shop_id, project_id, installation_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [pi for pi in store.punch_items.values() if pi["installation_id"] == installation_id]
    if status is not None:
        items = [pi for pi in items if pi["status"] == status]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_punch(pi) for pi in page], limit, offset, total)


@bp.route("/shops/<shop_id>/projects/<project_id>/punch-items", methods=["GET"])
def list_punch_for_project(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Installer", "Customer"})
    get_project_in_shop(shop_id, project_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [pi for pi in store.punch_items.values() if pi["project_id"] == project_id]
    if status is not None:
        items = [pi for pi in items if pi["status"] == status]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_punch(pi) for pi in page], limit, offset, total)


@bp.route("/shops/<shop_id>/projects/<project_id>/installations/<installation_id>/punch-items/<punch_id>/resolve", methods=["POST"])
def resolve_punch(shop_id, project_id, installation_id, punch_id):
    _, role = get_user_context()
    require_role(role, {"Installer", "ShopManager", "ShopAdmin"})
    get_installation_in_project(shop_id, project_id, installation_id)
    pi = get_punch_in_installation(shop_id, project_id, installation_id, punch_id)
    if pi["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Punch item is not OPEN")
    pi["status"] = "RESOLVED"
    touch(pi)
    return success(serialize_punch(pi), 200)
