"""Top-level FK-reachable GET endpoints (PRD 2.7): every child resource is
also addressable by its own id, with list forms supporting FK filters."""

from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import require_roles
from response import success_object
from routes.common import (
    paginate,
    resolve_assignment_any,
    resolve_fab_any,
    resolve_filing_any,
    resolve_item_any,
    resolve_job_any,
    resolve_layout_any,
    resolve_punch_any,
    resolve_quote_any,
    resolve_session_any,
    serialize,
)

bp = Blueprint("toplevel", __name__)

LAYOUT_ROLES = ("PlatformAdmin", "ProjectManager", "SalesRep", "KitchenDesigner", "Customer", "PermitCoordinator")
ITEM_ROLES = ("PlatformAdmin", "ProjectManager", "SalesRep", "KitchenDesigner", "Customer", "FabricationLead", "StartupTechnician")
FAB_ROLES = ("PlatformAdmin", "ProjectManager", "FabricationLead")
QUOTE_ROLES = ("PlatformAdmin", "ProjectManager", "SalesRep", "Customer")
FILING_ROLES = ("PlatformAdmin", "ProjectManager", "PermitCoordinator")
JOB_ROLES = ("PlatformAdmin", "ProjectManager", "LogisticsCoordinator")
SESSION_ROLES = ("PlatformAdmin", "ProjectManager", "StartupTechnician")
ASSIGNMENT_ROLES = ("PlatformAdmin", "ProjectManager", "ServiceManager")
PUNCH_ROLES = ("PlatformAdmin", "ProjectManager", "Customer")


def _owns(record: dict, user_id: str, role: str) -> bool:
    """Customer-role visibility: the record's project must belong to the
    caller's Customer id. Non-Customer roles see everything."""
    if role != "Customer":
        return True
    project = db.projects.get(record.get("project_id"))
    return project is not None and project["customer_id"] == user_id


def _check_owns(record: dict, user_id: str, role: str) -> None:
    if not _owns(record, user_id, role):
        from errors import ApiError, ERR_INSUFFICIENT_PERMISSIONS, HTTP_STATUS
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
            "Customer may access only its own resources",
        )


def _filtered(records, filters, user_id, role):
    out = [r for r in records if _owns(r, user_id, role)]
    for key, value in filters:
        if value is not None:
            out = [r for r in out if r.get(key) == value]
    return out


# --- KitchenLayout ---------------------------------------------------------

@bp.route("/kitchen-layouts/<layoutId>", methods=["GET"])
@require_roles(*LAYOUT_ROLES)
def get_layout_toplevel(layoutId, _user_id=None, _role=None):
    layout = resolve_layout_any(layoutId)
    _check_owns(layout, _user_id, _role)
    return success_object(serialize(layout), 200)


@bp.route("/kitchen-layouts", methods=["GET"])
@require_roles(*LAYOUT_ROLES)
def list_layouts_toplevel(_user_id=None, _role=None):
    filters = [("project_id", request.args.get("project_id")), ("status", request.args.get("status"))]
    return paginate(_filtered(list(db.layouts.values()), filters, _user_id, _role))


# --- EquipmentItem ---------------------------------------------------------

@bp.route("/equipment-items/<itemId>", methods=["GET"])
@require_roles(*ITEM_ROLES)
def get_item_toplevel(itemId, _user_id=None, _role=None):
    item = resolve_item_any(itemId)
    _check_owns(item, _user_id, _role)
    return success_object(serialize(item), 200)


@bp.route("/equipment-items", methods=["GET"])
@require_roles(*ITEM_ROLES)
def list_items_toplevel(_user_id=None, _role=None):
    filters = [
        ("layout_id", request.args.get("layout_id")),
        ("project_id", request.args.get("project_id")),
        ("status", request.args.get("status")),
        ("item_kind", request.args.get("item_kind")),
    ]
    return paginate(_filtered(list(db.items.values()), filters, _user_id, _role))


# --- FabricationOrder ------------------------------------------------------

@bp.route("/fabrication-orders/<fabId>", methods=["GET"])
@require_roles(*FAB_ROLES)
def get_fab_toplevel(fabId, _user_id=None, _role=None):
    fab = resolve_fab_any(fabId)
    return success_object(serialize(fab), 200)


@bp.route("/fabrication-orders", methods=["GET"])
@require_roles(*FAB_ROLES)
def list_fabs_toplevel(_user_id=None, _role=None):
    filters = [
        ("project_id", request.args.get("project_id")),
        ("equipment_item_id", request.args.get("equipment_item_id")),
        ("status", request.args.get("status")),
    ]
    return paginate(_filtered(list(db.fab_orders.values()), filters, _user_id, _role))


# --- Quote -----------------------------------------------------------------

@bp.route("/quotes/<quoteId>", methods=["GET"])
@require_roles(*QUOTE_ROLES)
def get_quote_toplevel(quoteId, _user_id=None, _role=None):
    quote = resolve_quote_any(quoteId)
    _check_owns(quote, _user_id, _role)
    return success_object(serialize(quote), 200)


@bp.route("/quotes", methods=["GET"])
@require_roles(*QUOTE_ROLES)
def list_quotes_toplevel(_user_id=None, _role=None):
    filters = [
        ("project_id", request.args.get("project_id")),
        ("layout_id", request.args.get("layout_id")),
        ("status", request.args.get("status")),
        ("variant", request.args.get("variant")),
    ]
    return paginate(_filtered(list(db.quotes.values()), filters, _user_id, _role))


# --- PermitFiling ----------------------------------------------------------

@bp.route("/permit-filings/<filingId>", methods=["GET"])
@require_roles(*FILING_ROLES)
def get_filing_toplevel(filingId, _user_id=None, _role=None):
    filing = resolve_filing_any(filingId)
    return success_object(serialize(filing), 200)


@bp.route("/permit-filings", methods=["GET"])
@require_roles(*FILING_ROLES)
def list_filings_toplevel(_user_id=None, _role=None):
    filters = [
        ("project_id", request.args.get("project_id")),
        ("layout_id", request.args.get("layout_id")),
        ("status", request.args.get("status")),
        ("authority", request.args.get("authority")),
    ]
    return paginate(_filtered(list(db.filings.values()), filters, _user_id, _role))


# --- DeliveryJob -----------------------------------------------------------

@bp.route("/delivery-jobs/<jobId>", methods=["GET"])
@require_roles(*JOB_ROLES)
def get_job_toplevel(jobId, _user_id=None, _role=None):
    job = resolve_job_any(jobId)
    return success_object(serialize(job), 200)


@bp.route("/delivery-jobs", methods=["GET"])
@require_roles(*JOB_ROLES)
def list_jobs_toplevel(_user_id=None, _role=None):
    filters = [("project_id", request.args.get("project_id")), ("status", request.args.get("status"))]
    return paginate(_filtered(list(db.jobs.values()), filters, _user_id, _role))


# --- StartupSession --------------------------------------------------------

@bp.route("/startup-sessions/<sessionId>", methods=["GET"])
@require_roles(*SESSION_ROLES)
def get_session_toplevel(sessionId, _user_id=None, _role=None):
    session = resolve_session_any(sessionId)
    return success_object(serialize(session), 200)


@bp.route("/startup-sessions", methods=["GET"])
@require_roles(*SESSION_ROLES)
def list_sessions_toplevel(_user_id=None, _role=None):
    filters = [
        ("project_id", request.args.get("project_id")),
        ("equipment_item_id", request.args.get("equipment_item_id")),
        ("status", request.args.get("status")),
    ]
    return paginate(_filtered(list(db.sessions.values()), filters, _user_id, _role))


# --- ServiceAssignment -----------------------------------------------------

@bp.route("/service-assignments/<assignmentId>", methods=["GET"])
@require_roles(*ASSIGNMENT_ROLES)
def get_assignment_toplevel(assignmentId, _user_id=None, _role=None):
    assignment = resolve_assignment_any(assignmentId)
    return success_object(serialize(assignment), 200)


@bp.route("/service-assignments", methods=["GET"])
@require_roles(*ASSIGNMENT_ROLES)
def list_assignments_toplevel(_user_id=None, _role=None):
    filters = [
        ("project_id", request.args.get("project_id")),
        ("agency_id", request.args.get("agency_id")),
        ("status", request.args.get("status")),
    ]
    return paginate(_filtered(list(db.assignments.values()), filters, _user_id, _role))


# --- PunchListItem ----------------------------------------------------------

@bp.route("/punch-list-items/<itemId>", methods=["GET"])
@require_roles(*PUNCH_ROLES)
def get_punch_toplevel(itemId, _user_id=None, _role=None):
    item = resolve_punch_any(itemId)
    _check_owns(item, _user_id, _role)
    return success_object(serialize(item), 200)


@bp.route("/punch-list-items", methods=["GET"])
@require_roles(*PUNCH_ROLES)
def list_punch_toplevel(_user_id=None, _role=None):
    filters = [
        ("project_id", request.args.get("project_id")),
        ("status", request.args.get("status")),
        ("severity", request.args.get("severity")),
    ]
    return paginate(_filtered(list(db.punch_items.values()), filters, _user_id, _role))
