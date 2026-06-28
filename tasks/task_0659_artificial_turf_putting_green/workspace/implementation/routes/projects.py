"""Projects (PRD 3.1, 3.12). Aggregate root with two parallel status
dimensions. Includes create, get, list, ledger, close, cancel."""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    public,
    require_fields,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_project_or_404
from middleware import get_auth, require_role
from ownership import enforce_project_ownership
from response import success
from services.project_service import (
    compute_ledger,
    recompute_rollups,
    serialize_project,
)

bp = Blueprint("projects", __name__)


def _new_project(customer_id, site_address):
    rec = {
        "customer_id": customer_id,
        "site_address": site_address,
        "workflow_status": "DRAFT",
        "finance_status": "UNBILLED",
        "variant": None,
        "billable_area_sqft": 0,
        "contract_total_cents": 0,
        "deposit_paid_cents": 0,
        "balance_paid_cents": 0,
        "amount_refunded_cents": 0,
        "outstanding_balance_cents": 0,
        "open_callback_count": 0,
    }
    stamp_new(rec)
    return rec


@bp.route("/projects", methods=["POST"])
def create_project():
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep"})
    body = get_json_body()
    require_fields(body, ["customer_id", "site_address"])
    customer_id = require_string(body, "customer_id")
    site_address = require_string(body, "site_address")
    # NOTE: customer_id is the owning-customer FK but is NOT in the
    # ERR_REFERENCE_NOT_FOUND check catalog (PRD 2.7 lists only turf/infill/
    # measure/crew/design/scope/warranty FKs, and only for design/scope/quote/
    # install-job/callback creation). Project create therefore does not reject an
    # unknown customer_id — over-validating here would be a PRD-fidelity bug.
    rec = _new_project(customer_id, site_address)
    db.projects[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep", "Scheduler", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    return success(serialize_project(project), status=200)


@bp.route("/projects", methods=["GET"])
def list_projects():
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep", "Scheduler"})
    items = list(db.projects.values())
    customer_id = request.args.get("customer_id")
    workflow_status = request.args.get("workflow_status")
    if customer_id is not None:
        items = [p for p in items if p["customer_id"] == customer_id]
    if workflow_status is not None:
        items = [p for p in items if p["workflow_status"] == workflow_status]
    data, pagination = paginate(items, serialize_project)
    return success(data, status=200, pagination=pagination)


@bp.route("/projects/<project_id>/ledger", methods=["GET"])
def get_ledger(project_id):
    uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)

    include_pending_raw = request.args.get("include_pending")
    include_pending = False
    if include_pending_raw is not None:
        if include_pending_raw.lower() in ("true", "1"):
            include_pending = True
        elif include_pending_raw.lower() in ("false", "0"):
            include_pending = False
        else:
            raise err("ERR_INVALID_REQUEST", "include_pending must be a boolean.")

    recompute_rollups(project)
    ledger = compute_ledger(project, include_pending=include_pending)
    data = serialize_project(project)
    # Overlay the requested ledger view (settled-only by default; projected when
    # include_pending=true — a different outstanding figure when pending exist).
    data["deposit_paid_cents"] = ledger["deposit_paid_cents"]
    data["balance_paid_cents"] = ledger["balance_paid_cents"]
    data["amount_refunded_cents"] = ledger["amount_refunded_cents"]
    data["outstanding_balance_cents"] = ledger["outstanding_balance_cents"]
    return success(data, status=200)


@bp.route("/projects/<project_id>/close", methods=["POST"])
def close_project(project_id):
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin"})
    project = get_project_or_404(project_id)

    if project["workflow_status"] != "INSTALLED":
        raise err("ERR_INVALID_STATE", "Project is not INSTALLED.")
    recompute_rollups(project)
    if project["finance_status"] != "PAID_IN_FULL" or project["open_callback_count"] != 0:
        raise err(
            "ERR_PROJECT_NOT_CLOSEABLE",
            "Project must be PAID_IN_FULL with no open callbacks to close.",
        )
    project["workflow_status"] = "CLOSED"
    touch(project)
    return success(serialize_project(project), status=200)


@bp.route("/projects/<project_id>/cancel", methods=["POST"])
def cancel_project(project_id):
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin"})
    project = get_project_or_404(project_id)

    if project["workflow_status"] in ("INSTALLED", "CLOSED", "CANCELLED"):
        raise err("ERR_INVALID_STATE", "Project cannot be cancelled in its current state.")

    pid = project["id"]

    # Cascade: abort SCHEDULED/IN_PROGRESS install jobs (release crew window).
    for job in db.install_jobs.values():
        if job["project_id"] == pid and job["status"] in ("SCHEDULED", "IN_PROGRESS"):
            job["status"] = "ABORTED"
            touch(job)

    # Cascade: void DRAFT/SENT/REVISED quotes.
    for q in db.quotes.values():
        if q["project_id"] == pid and q["status"] in ("DRAFT", "SENT", "REVISED"):
            q["status"] = "VOID"
            touch(q)

    # Cascade: void PENDING warranty plans.
    for w in db.warranty_plans.values():
        if w["project_id"] == pid and w["status"] == "PENDING":
            w["status"] = "VOID"
            touch(w)

    # Cascade: if deposit settled, create a PENDING REFUND for the full settled
    # deposit amount.
    recompute_rollups(project)
    if project["deposit_paid_cents"] > 0:
        from common import stamp_new_minimal

        refund = {
            "project_id": pid,
            "kind": "REFUND",
            "amount_cents": project["deposit_paid_cents"],
            "status": "PENDING",
        }
        stamp_new_minimal(refund)
        db.payments[refund["id"]] = refund

    project["workflow_status"] = "CANCELLED"
    touch(project)
    return success(serialize_project(project), status=200)
