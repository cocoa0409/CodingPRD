"""PermitApplication endpoints: list per order, get, approve, deny."""

from flask import Blueprint, request

import db
from errors import invalid_state, ApiError, ERR_STALE_RULE_SET
from middleware import authenticate, require_roles, check_customer_owns_order
from response import success_object, success_list
from services.common import (
    get_body, optional, get_order, get_permit_app, paginate,
)
from services.cascade import bump, advance_order_to_ready

bp = Blueprint("permits", __name__)

READ_ROLES = ("Customer", "SalesRep", "PermitCoordinator", "InstallCrew",
              "FinanceManager", "OperationsAdmin")


@bp.get("/api/orders/<oid>/permit-applications")
def list_order_permit_applications(oid):
    authenticate()
    require_roles(*READ_ROLES)
    order = get_order(oid)
    check_customer_owns_order(order)
    rows = [p for p in db.permit_applications.values() if p["order_id"] == oid]
    rows.sort(key=lambda p: p["created_at"])
    limit, offset = paginate(request.args, rows)
    return success_list(rows[offset:offset + limit], limit, offset, len(rows))


@bp.get("/api/permit-applications/<pid>")
def read_permit_application(pid):
    authenticate()
    require_roles(*READ_ROLES)
    app = get_permit_app(pid)
    order = db.orders.get(app["order_id"])
    if order is not None:
        check_customer_owns_order(order)
    return success_object(app)


def _check_rule_set_pin(app: dict):
    jurisdiction = db.jurisdictions[app["jurisdiction_id"]]
    if app["jurisdiction_version"] != jurisdiction["version"]:
        raise ApiError(ERR_STALE_RULE_SET,
                       "Permit decision attempted on an application whose pinned "
                       "jurisdiction_version is stale", 409)


@bp.post("/api/permit-applications/<pid>/approve")
def approve_permit(pid):
    authenticate()
    require_roles("PermitCoordinator")
    get_body()
    app = get_permit_app(pid)
    if app["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED permit application can be approved")
    _check_rule_set_pin(app)

    app["status"] = "APPROVED"
    app["decided_at"] = db.now_iso()
    bump(app)

    order = db.orders.get(app["order_id"])
    if order is not None and order["status"] == "PERMIT_REVIEW":
        advance_order_to_ready(order)
    return success_object(app)


@bp.post("/api/permit-applications/<pid>/deny")
def deny_permit(pid):
    authenticate()
    require_roles("PermitCoordinator")
    body = get_body()
    decision_note = optional(body, "decision_note", "str", default=None, allow_none=True)

    app = get_permit_app(pid)
    if app["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED permit application can be denied")
    _check_rule_set_pin(app)

    app["status"] = "DENIED"
    app["decision_note"] = decision_note
    app["decided_at"] = db.now_iso()
    bump(app)

    order = db.orders.get(app["order_id"])
    if order is not None and order["status"] == "PERMIT_REVIEW":
        order["status"] = "DRAFT"
        bump(order)
    return success_object(app)
