"""Project routes: create/read/list/cut-list + lifecycle transitions."""
from flask import Blueprint

from db import store
from errors import err
from middleware import get_user_context, require_role
from response import success, success_list
from helpers import (get_body, require_str, require_bool, require_enum, require_int,
                     parse_pagination, paginate, sort_by_created)
from models import (_base_record, touch, serialize_project,
                    project_active_finish, project_paid_to_date,
                    project_specs)
from lookups import (get_shop, get_customer_in_shop, get_project_in_shop,
                     require_project_owner)
from calculations import contract_total, cut_list
from services import (recompute_estimate, create_draw, recompute_deposit_required,
                      release_reservations)

bp = Blueprint("project", __name__)


@bp.route("/shops/<shop_id>/customers/<customer_id>/projects", methods=["POST"])
def create_project(shop_id, customer_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    cust = get_customer_in_shop(shop_id, customer_id)
    body = get_body()
    title = require_str(body, "title")
    is_rush = require_bool(body, "is_rush", required=False, default=False)
    install_address = require_str(body, "install_address", required=False)
    margin_policy = require_enum(body, "margin_policy", {"STANDARD", "PREMIUM"},
                                 required=False, default="STANDARD")

    rec = _base_record()
    rec.update({
        "customer_id": customer_id,
        "shop_id": shop_id,
        "title": title,
        "is_rush": is_rush,
        "install_address": install_address,
        "margin_policy": margin_policy,
        "estimate_total_cents": 0,
        "contract_total_cents": 0,
        "deposit_required_cents": 0,
        "status": "DRAFT",
    })
    store.projects[rec["id"]] = rec
    return success(serialize_project(rec), 201)


@bp.route("/shops/<shop_id>/projects/<project_id>", methods=["GET"])
def get_project(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer", "Installer", "Customer"})
    p = get_project_in_shop(shop_id, project_id)
    return success(serialize_project(p), 200)


def _filter_projects(items, args):
    customer_id = args.get("customer_id")
    status = args.get("status")
    if customer_id is not None:
        items = [p for p in items if p["customer_id"] == customer_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return items


@bp.route("/shops/<shop_id>/projects", methods=["GET"])
def list_projects(shop_id):
    from flask import request
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer", "Installer", "Customer"})
    get_shop(shop_id)
    limit, offset = parse_pagination()
    items = [p for p in store.projects.values() if p["shop_id"] == shop_id]
    items = _filter_projects(items, request.args)
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_project(p) for p in page], limit, offset, total)


@bp.route("/shops/<shop_id>/customers/<customer_id>/projects", methods=["GET"])
def list_customer_projects(shop_id, customer_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer", "Customer"})
    get_customer_in_shop(shop_id, customer_id)
    limit, offset = parse_pagination()
    items = [p for p in store.projects.values()
             if p["shop_id"] == shop_id and p["customer_id"] == customer_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_project(p) for p in page], limit, offset, total)


@bp.route("/shops/<shop_id>/projects/<project_id>/cut-list", methods=["GET"])
def get_cut_list(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager", "Designer"})
    get_project_in_shop(shop_id, project_id)
    materials, total = cut_list(project_id)
    return success({"materials": materials, "total_sheets": total}, 200)


# --------------------------------------------------------------------------
# Lifecycle transitions
# --------------------------------------------------------------------------
@bp.route("/shops/<shop_id>/projects/<project_id>/measure", methods=["POST"])
def measure(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"Designer", "ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    if p["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Project is not in DRAFT")
    specs = project_specs(project_id)
    if len(specs) == 0:
        raise err("ERR_NO_SPECS", "Project has no cabinet specs")
    for s in specs:
        if not (s["width_mm"] > 0 and s["height_mm"] > 0 and s["depth_mm"] > 0 and s["quantity"] >= 1):
            raise err("ERR_INVALID_REQUEST", "All specs must have positive dimensions and quantity >= 1")
    p["status"] = "MEASURED"
    recompute_estimate(p)
    touch(p)
    return success(serialize_project(p), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/quote", methods=["POST"])
def quote(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"Designer", "ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    if p["status"] != "MEASURED":
        raise err("ERR_INVALID_STATE", "Project is not in MEASURED")
    if project_active_finish(project_id) is None:
        raise err("ERR_FINISH_REQUIRED", "No active finish selection")
    p["status"] = "QUOTED"
    recompute_estimate(p)
    touch(p)
    return success(serialize_project(p), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/revise", methods=["POST"])
def revise(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"Designer", "ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    if p["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Project is not in QUOTED")
    p["status"] = "DRAFT"
    touch(p)
    return success(serialize_project(p), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/contract", methods=["POST"])
def contract(shop_id, project_id):
    user_id, role = get_user_context()
    require_role(role, {"Customer"})
    p = get_project_in_shop(shop_id, project_id)
    require_project_owner(p, user_id, role)
    body = get_body()
    expected_version = require_int(body, "expected_project_version")
    if p["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Project is not in QUOTED")
    if project_active_finish(project_id) is None:
        raise err("ERR_FINISH_REQUIRED", "No active finish selection")
    cust = store.customers[p["customer_id"]]
    if cust["credit_hold"]:
        raise err("ERR_CUSTOMER_CREDIT_HOLD", "Customer is on credit hold")
    if expected_version != p["version"]:
        raise err("ERR_STALE_VERSION", "expected_project_version does not match")

    # Cascade: lock specs, compute final total, deposit, create DEPOSIT draw, bump version.
    for s in project_specs(project_id):
        s["lock_state"] = "LOCKED"
        touch(s)
    p["contract_total_cents"] = contract_total(p, "final")
    recompute_deposit_required(p)
    p["status"] = "CONTRACTED"
    touch(p)  # increments version by 1
    create_draw(p, "DEPOSIT")
    return success(serialize_project(p), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/mark-ready", methods=["POST"])
def mark_ready(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    if p["status"] != "IN_PRODUCTION":
        raise err("ERR_INVALID_STATE", "Project is not in IN_PRODUCTION")
    jobs = [b for b in store.build_jobs.values() if b["project_id"] == project_id]
    for b in jobs:
        if b["status"] != "COMPLETE":
            raise err("ERR_BUILD_INCOMPLETE", "Not all build jobs are complete")
    for c in store.change_orders.values():
        if c["project_id"] == project_id and c["status"] in ("SUBMITTED", "REVISING"):
            raise err("ERR_CHANGE_OPEN", "An open change order exists")
    p["status"] = "READY_FOR_DELIVERY"
    touch(p)
    return success(serialize_project(p), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/close", methods=["POST"])
def close(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    if p["status"] != "INSTALLED":
        raise err("ERR_INVALID_STATE", "Project is not in INSTALLED")
    if project_paid_to_date(project_id) < p["contract_total_cents"]:
        raise err("ERR_BALANCE_OUTSTANDING", "Balance outstanding")
    # No PunchItem on any installation is OPEN
    for pi in store.punch_items.values():
        if pi["project_id"] == project_id and pi["status"] == "OPEN":
            raise err("ERR_PUNCH_OPEN", "An open punch item exists")
    p["status"] = "CLOSED"
    touch(p)
    release_reservations(p, {"HELD"})
    return success(serialize_project(p), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/cancel", methods=["POST"])
def cancel(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    status = p["status"]
    if status in ("DRAFT", "MEASURED", "QUOTED"):
        p["status"] = "CANCELLED"
        touch(p)
        release_reservations(p, {"HELD", "COMMITTED"})
    elif status == "CONTRACTED":
        if project_paid_to_date(project_id) != 0:
            raise err("ERR_DEPOSIT_PAID_NO_CANCEL", "Deposit already paid; cannot cancel")
        # void all PENDING/ISSUED draws
        for d in store.draws.values():
            if d["project_id"] == project_id and d["status"] in ("PENDING", "ISSUED"):
                d["status"] = "VOIDED"
                touch(d)
        p["status"] = "CANCELLED"
        touch(p)
        release_reservations(p, {"HELD", "COMMITTED"})
    else:
        raise err("ERR_INVALID_STATE", "Project cannot be cancelled from %s" % status)
    return success(serialize_project(p), 200)
