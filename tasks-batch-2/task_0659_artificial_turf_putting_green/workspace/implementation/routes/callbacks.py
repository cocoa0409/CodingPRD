"""Callbacks (PRD 3.11). Opened against an INSTALLED project; coverage decision
sets billable + charge_cents. Serviced through start/resolve/cancel; a billable
resolve spawns a PENDING BALANCE payment."""

from flask import Blueprint, request

from clock import clock
from common import (
    get_json_body,
    paginate,
    public,
    require_enum,
    require_fields,
    stamp_new,
    stamp_new_minimal,
    touch,
)
from db import db
from errors import err
from lookups import get_child_or_404, get_project_or_404, ref_warranty_or_404
from middleware import get_auth, require_role
from ownership import enforce_project_ownership
from response import success
from services.calculations import compute_callback_billing
from services.project_service import (
    expire_warranty_if_due,
    recompute_rollups,
)

bp = Blueprint("callbacks", __name__)

REASONS = {"SEAM_LIFT", "INFILL_MIGRATION", "DRAINAGE", "WRINKLE", "PET_ODOR", "OTHER"}


@bp.route("/projects/<project_id>/callbacks", methods=["POST"])
def create_callback(project_id):
    uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    body = get_json_body()
    require_fields(body, ["reason"])

    # Reference existence of warranty_plan_id when provided (priority 5).
    warranty_plan = None
    if "warranty_plan_id" in body and body["warranty_plan_id"] is not None:
        warranty_plan = ref_warranty_or_404(body["warranty_plan_id"], project_id)

    reason = require_enum(body, "reason", REASONS)

    # Project must be INSTALLED to open a callback (priority 8).
    if project["workflow_status"] != "INSTALLED":
        raise err("ERR_INVALID_STATE", "Project is not INSTALLED.")

    # Apply lazy expiry to the referenced warranty before the coverage decision.
    if warranty_plan is not None:
        expire_warranty_if_due(warranty_plan)

    recompute_rollups(project)
    billable, charge = compute_callback_billing(
        reason,
        warranty_plan,
        project["variant"],
        project["billable_area_sqft"],
        clock.now(),
    )

    rec = {
        "project_id": project_id,
        "warranty_plan_id": warranty_plan["id"] if warranty_plan is not None else None,
        "reason": reason,
        "billable": billable,
        "charge_cents": charge,
        "status": "OPEN",
    }
    stamp_new(rec)
    db.callbacks[rec["id"]] = rec

    # open_callback_count recomputed; project version increments.
    touch(project)

    return success(public(rec), status=201)


@bp.route("/projects/<project_id>/callbacks", methods=["GET"])
def list_callbacks(project_id):
    uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    items = [c for c in db.callbacks.values() if c["project_id"] == project_id]
    for field in ("warranty_plan_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [c for c in items if c.get(field) == val]
    data, pagination = paginate(items, public)
    return success(data, status=200, pagination=pagination)


@bp.route("/projects/<project_id>/callbacks/<callback_id>", methods=["GET"])
def get_callback(project_id, callback_id):
    uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    rec = get_child_or_404(db.callbacks, callback_id, project_id, "Callback")
    return success(public(rec), status=200)


@bp.route("/projects/<project_id>/callbacks/<callback_id>/start", methods=["POST"])
def start_callback(project_id, callback_id):
    _uid, role = get_auth()
    require_role(role, {"Scheduler", "OpsAdmin"})
    get_project_or_404(project_id)
    cb = get_child_or_404(db.callbacks, callback_id, project_id, "Callback")

    if cb["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Callback is not in OPEN status.")
    cb["status"] = "IN_PROGRESS"
    touch(cb)
    return success(public(cb), status=200)


@bp.route("/projects/<project_id>/callbacks/<callback_id>/resolve", methods=["POST"])
def resolve_callback(project_id, callback_id):
    _uid, role = get_auth()
    require_role(role, {"Scheduler", "OpsAdmin"})
    project = get_project_or_404(project_id)
    cb = get_child_or_404(db.callbacks, callback_id, project_id, "Callback")

    if cb["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Callback is not in IN_PROGRESS status.")
    cb["status"] = "RESOLVED"
    touch(cb)

    # If billable: a BALANCE Payment of charge_cents is created PENDING.
    if cb["billable"]:
        payment = {
            "project_id": project_id,
            "kind": "BALANCE",
            "amount_cents": cb["charge_cents"],
            "status": "PENDING",
        }
        stamp_new_minimal(payment)
        db.payments[payment["id"]] = payment

    # open_callback_count recomputed (bubble up); project version increments.
    recompute_rollups(project)
    touch(project)
    return success(public(cb), status=200)


@bp.route("/projects/<project_id>/callbacks/<callback_id>/cancel", methods=["POST"])
def cancel_callback(project_id, callback_id):
    uid, role = get_auth()
    require_role(role, {"Scheduler", "OpsAdmin", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    cb = get_child_or_404(db.callbacks, callback_id, project_id, "Callback")

    if cb["status"] not in ("OPEN", "IN_PROGRESS"):
        raise err("ERR_INVALID_STATE", "Callback cannot be cancelled in its current state.")
    cb["status"] = "CANCELLED"
    touch(cb)

    # open_callback_count recomputed (bubble up); project version increments.
    recompute_rollups(project)
    touch(project)
    return success(public(cb), status=200)
