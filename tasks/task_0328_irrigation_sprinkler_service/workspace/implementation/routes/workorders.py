"""WorkOrder routes (PRD §3.4). Two independent status dimensions."""
from flask import Blueprint, request

from db import db, LOCK, stamp_new, touch
import domain
import errors
import lookups
from cascades import cancel_workorder
from domain import serialize
from errors import fail
from listing import list_response
from middleware import get_auth, require_role
from response import success
from validation import get_body, require_str, require_int, require_enum

bp = Blueprint("workorders", __name__)

JOB_TYPES = {"INSTALL", "STARTUP", "WINTERIZATION", "LEAK_REPAIR", "HEAD_REPAIR", "BACKFLOW_TEST"}


@bp.route("/work-orders", methods=["POST"])
def create_workorder():
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        body = get_body()
        system_id = require_str(body, "system_id")
        system = lookups.get_system(system_id)
        job_type = require_enum(body, "job_type", JOB_TYPES)
        estimated_minutes = require_int(body, "estimated_minutes", minimum=1)
        estimated_cost_cents = require_int(body, "estimated_cost_cents", minimum=0)
        rec = {
            "system_id": system_id,
            "job_type": job_type,
            "estimated_minutes": estimated_minutes,
            "estimated_cost_cents": estimated_cost_cents,
            "actual_labor_cents": 0,
            "actual_parts_cents": 0,
            "assigned_technician_id": None,
            "dispatch_status": "UNSCHEDULED",
            "completion_status": "PENDING",
            "origin_quote_id": None,
        }
        stamp_new(rec)
        db.work_orders[rec["id"]] = rec
        # Creating a work order debits the system's committed_cost_cents.
        domain.recompute_system_derived(system)
        return success(serialize(rec), status=201)


@bp.route("/work-orders/<wid>", methods=["GET"])
def get_workorder(wid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer", "Technician"})
    with LOCK:
        rec = lookups.get_workorder(wid)
        return success(serialize(rec), status=200)


@bp.route("/work-orders", methods=["GET"])
def list_workorders():
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer", "Technician"})
    with LOCK:
        rows = list(db.work_orders.values())
        system_id = request.args.get("system_id")
        tech_id = request.args.get("assigned_technician_id")
        origin = request.args.get("origin_quote_id")
        if system_id is not None:
            rows = [w for w in rows if w["system_id"] == system_id]
        if tech_id is not None:
            rows = [w for w in rows if w["assigned_technician_id"] == tech_id]
        if origin is not None:
            rows = [w for w in rows if w["origin_quote_id"] == origin]
        return list_response(rows)


def _require_assigned(wo, user_id):
    """Ownership (priority 4): acting Technician must be assigned_technician_id."""
    if wo["assigned_technician_id"] != user_id:
        fail(errors.ERR_NOT_RESOURCE_OWNER, "Technician is not assigned to this work order")


@bp.route("/work-orders/<wid>/depart", methods=["POST"])
def depart(wid):
    user_id, role = get_auth()
    require_role(role, {"Technician"})
    with LOCK:
        wo = lookups.get_workorder(wid)
        _require_assigned(wo, user_id)
        if wo["dispatch_status"] != "SCHEDULED":
            fail(errors.ERR_WORKORDER_NOT_SCHEDULED, "Work order is not SCHEDULED")
        wo["dispatch_status"] = "EN_ROUTE"
        touch(wo)
        return success(serialize(wo), status=200)


@bp.route("/work-orders/<wid>/arrive", methods=["POST"])
def arrive(wid):
    user_id, role = get_auth()
    require_role(role, {"Technician"})
    with LOCK:
        wo = lookups.get_workorder(wid)
        _require_assigned(wo, user_id)
        if wo["dispatch_status"] != "EN_ROUTE":
            fail(errors.ERR_WORKORDER_NOT_EN_ROUTE, "Work order is not EN_ROUTE")
        wo["dispatch_status"] = "ON_SITE"
        # Cross-axis side effect: completion_status PENDING -> IN_PROGRESS (auto)
        if wo["completion_status"] == "PENDING":
            wo["completion_status"] = "IN_PROGRESS"
        touch(wo)
        return success(serialize(wo), status=200)


@bp.route("/work-orders/<wid>/complete", methods=["POST"])
def complete(wid):
    user_id, role = get_auth()
    require_role(role, {"Technician"})
    with LOCK:
        wo = lookups.get_workorder(wid)
        _require_assigned(wo, user_id)
        # State preconditions (priority 5): completion IN_PROGRESS then dispatch ON_SITE
        if wo["completion_status"] != "IN_PROGRESS":
            fail(errors.ERR_WORKORDER_NOT_IN_PROGRESS, "Work order is not IN_PROGRESS")
        if wo["dispatch_status"] != "ON_SITE":
            fail(errors.ERR_WORKORDER_NOT_ON_SITE, "Work order is not ON_SITE")
        body = get_body()
        actual_labor = require_int(body, "actual_labor_cents", minimum=0)
        actual_parts = require_int(body, "actual_parts_cents", minimum=0)

        wo["actual_labor_cents"] = actual_labor
        wo["actual_parts_cents"] = actual_parts
        wo["completion_status"] = "COMPLETED"
        touch(wo)

        # (1) credit committed_cost back — recompute excludes terminal WOs.
        system = db.irrigation_systems.get(wo["system_id"])

        # (2) recompute the originating quote's final_total_cents if linked.
        if wo["origin_quote_id"]:
            quote = db.service_quotes.get(wo["origin_quote_id"])
            if quote is not None:
                quote["final_total_cents"] = domain.quote_final_total(actual_labor, actual_parts)
                touch(quote)

        # (3) WINTERIZATION -> season WINTERIZED + assessed_winter_risk recompute.
        # (4) STARTUP -> season ACTIVE.
        if system is not None:
            if wo["job_type"] == "WINTERIZATION":
                system["season_state"] = "WINTERIZED"
                touch(system)
            elif wo["job_type"] == "STARTUP":
                system["season_state"] = "ACTIVE"
                touch(system)
            # recompute_system_derived handles committed_cost credit AND the
            # assessed/provisional winter-risk re-derivation in one pass.
            domain.recompute_system_derived(system)

        return success(serialize(wo), status=200)


@bp.route("/work-orders/<wid>/fail", methods=["POST"])
def fail_workorder(wid):
    user_id, role = get_auth()
    require_role(role, {"Technician"})
    with LOCK:
        wo = lookups.get_workorder(wid)
        _require_assigned(wo, user_id)
        if wo["completion_status"] != "IN_PROGRESS":
            fail(errors.ERR_WORKORDER_NOT_IN_PROGRESS, "Work order is not IN_PROGRESS")
        wo["completion_status"] = "FAILED"
        touch(wo)
        # Credit committed_cost back.
        system = db.irrigation_systems.get(wo["system_id"])
        if system is not None:
            domain.recompute_system_derived(system)
        return success(serialize(wo), status=200)


@bp.route("/work-orders/<wid>/cancel", methods=["POST"])
def cancel(wid):
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        wo = lookups.get_workorder(wid)
        if wo["completion_status"] in domain.WO_TERMINAL:
            fail(errors.ERR_WORKORDER_TERMINAL, "Work order is already terminal")
        cancel_workorder(wo)
        return success(serialize(wo), status=200)
