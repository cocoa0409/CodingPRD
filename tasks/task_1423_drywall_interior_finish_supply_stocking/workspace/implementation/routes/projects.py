"""Project endpoints."""
from flask import Blueprint, request
from db import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_ACCOUNT_SUSPENDED, ERR_INVALID_STATE,
    ERR_FRAMING_NOT_READY, ERR_NO_LOCKED_TAKEOFF, ERR_ORDERS_IN_FLIGHT,
)
from middleware import require_roles
from response import success
from services.helpers import (
    parse_pagination, paginate, body, require_fields, require_int, require_str,
    new_common_fields, touch,
)

bp = Blueprint("projects", __name__)


def _get_project_or_404(pid):
    p = db.projects.get(pid)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "Project not found", 404)
    return p


@bp.route("/supply/projects", methods=["POST"])
def create_project():
    require_roles("EstimatorUser", "ContractorAdmin")
    b = body()
    require_fields(b, "account_id", "jobsite_name", "distance_miles", "framing_pct_complete")
    account_id = b["account_id"]
    if not isinstance(account_id, str):
        raise ApiError(ERR_NOT_FOUND, "ContractorAccount not found", 404)
    account = db.contractor_accounts.get(account_id)
    if account is None:
        raise ApiError(ERR_NOT_FOUND, "ContractorAccount not found", 404)
    jobsite_name = require_str(b, "jobsite_name")
    distance_miles = require_int(b, "distance_miles", min_val=1)
    framing = require_int(b, "framing_pct_complete", min_val=0, max_val=100)
    # Account must be ACTIVE
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_SUSPENDED, "Account is not ACTIVE", 409)
    proj = new_common_fields()
    proj.update({
        "account_id": account_id,
        "jobsite_name": jobsite_name,
        "distance_miles": distance_miles,
        "framing_pct_complete": framing,
        "status": "PLANNING",
    })
    db.projects[proj["id"]] = proj
    return success(proj, status=201)


@bp.route("/supply/projects/<pid>", methods=["GET"])
def get_project(pid):
    require_roles("CreditManager", "EstimatorUser", "DispatcherUser", "Foreman", "ContractorAdmin")
    return success(_get_project_or_404(pid))


@bp.route("/supply/projects", methods=["GET"])
def list_projects():
    require_roles("CreditManager", "EstimatorUser", "DispatcherUser", "Foreman", "ContractorAdmin")
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = list(db.projects.values())
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    page, pg = paginate(items, limit, offset)
    return success(page, is_list=True, pagination=pg)


@bp.route("/supply/projects/<pid>", methods=["PATCH"])
def update_project(pid):
    require_roles("Foreman", "ContractorAdmin")
    p = _get_project_or_404(pid)
    b = body()
    if "framing_pct_complete" in b:
        p["framing_pct_complete"] = require_int(b, "framing_pct_complete", min_val=0, max_val=100)
    if "distance_miles" in b:
        p["distance_miles"] = require_int(b, "distance_miles", min_val=1)
    touch(p)
    return success(p)


@bp.route("/supply/projects/<pid>/open-stocking", methods=["POST"])
def open_stocking(pid):
    require_roles("Foreman")
    p = _get_project_or_404(pid)
    if p["status"] != "PLANNING":
        raise ApiError(ERR_INVALID_STATE, "Project must be PLANNING to open stocking", 409)
    account = db.contractor_accounts.get(p["account_id"])
    if account and account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_SUSPENDED, "Account is not ACTIVE", 409)
    if p["framing_pct_complete"] < 50:
        raise ApiError(ERR_FRAMING_NOT_READY, "framing_pct_complete must be >= 50", 422)
    has_locked = any(
        t["project_id"] == pid and t["status"] == "LOCKED"
        for t in db.takeoffs.values()
    )
    if not has_locked:
        raise ApiError(ERR_NO_LOCKED_TAKEOFF, "Project requires a LOCKED takeoff", 422)
    p["status"] = "STOCKING_OPEN"
    touch(p)
    return success(p)


@bp.route("/supply/projects/<pid>/close-stocking", methods=["POST"])
def close_stocking(pid):
    require_roles("Foreman")
    p = _get_project_or_404(pid)
    if p["status"] != "STOCKING_OPEN":
        raise ApiError(ERR_INVALID_STATE, "Project must be STOCKING_OPEN to close stocking", 409)
    in_flight = any(
        o["project_id"] == pid and o["status"] in ("SCHEDULED", "DISPATCHED")
        for o in db.stocking_orders.values()
    )
    if in_flight:
        raise ApiError(ERR_ORDERS_IN_FLIGHT, "Project has SCHEDULED or DISPATCHED orders", 409)
    p["status"] = "STOCKING_CLOSED"
    touch(p)
    # Cancel DRAFT stocking orders on this project
    for o in db.stocking_orders.values():
        if o["project_id"] == pid and o["status"] == "DRAFT":
            o["status"] = "CANCELLED"
            touch(o)
    return success(p)


@bp.route("/supply/projects/<pid>/cancel", methods=["POST"])
def cancel_project(pid):
    require_roles("ContractorAdmin")
    p = _get_project_or_404(pid)
    if p["status"] not in ("PLANNING", "STOCKING_OPEN"):
        raise ApiError(ERR_INVALID_STATE, "Project is not in a cancellable state", 409)
    if p["status"] == "STOCKING_OPEN":
        # Refused while any order is DISPATCHED
        if any(
            o["project_id"] == pid and o["status"] == "DISPATCHED"
            for o in db.stocking_orders.values()
        ):
            raise ApiError(ERR_ORDERS_IN_FLIGHT, "Project has DISPATCHED orders", 409)
    p["status"] = "CANCELLED"
    touch(p)
    # Cascade: cancel DRAFT/SCHEDULED stocking orders
    for o in db.stocking_orders.values():
        if o["project_id"] == pid and o["status"] in ("DRAFT", "SCHEDULED"):
            o["status"] = "CANCELLED"
            touch(o)
    # Cascade: cancel non-terminal takeoffs
    for t in db.takeoffs.values():
        if t["project_id"] == pid and t["status"] not in ("LOCKED", "CANCELLED"):
            t["status"] = "CANCELLED"
            touch(t)
    return success(p)
