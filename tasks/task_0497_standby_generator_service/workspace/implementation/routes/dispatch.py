"""RepairDispatch routes: request(PAID), assign(OCC), start/pause/resolve,
close(segregation), cancel. Resolve cascades RECALL remediation completion."""
from flask import Blueprint, request

import calc
import db
import posture
from auth import get_principal, require_roles
from clock import get_now
from errors import err
from response import success
from serialize import out
from validate import get_body, opt_int, require_int, require_str
from routes.common import customer_owns, find_or_404, ref_or_404, render_list

bp = Blueprint("dispatch", __name__)


def _opt_number(body, field, default=0, ge=0):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a number")
    if ge is not None and not v >= ge:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {ge}")
    return v


# ---- Request a PAID dispatch ----------------------------------------------
@bp.route("/units/<unit_id>/repair-dispatches", methods=["POST"])
def request_dispatch(unit_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    unit = find_or_404(db.units, unit_id)
    body = get_body()
    labor_cents = opt_int(body, "labor_cents", default=0, minimum=0)
    parts_cents = opt_int(body, "parts_cents", default=0, minimum=0)

    # Ownership (priority 6) after body well-formedness.
    customer_owns(principal, unit["customer_id"])

    rec = db.base_record(full_common=True)
    rec.update({
        "unit_id": unit_id,
        "origin": "PAID",
        "warranty_claim_id": None,
        "assigned_tech_id": None,
        "status": "REQUESTED",
        "labor_cents": labor_cents,
        "parts_cents": parts_cents,
        "billable": True,
        "invoice_total_cents": 0,
        "resolved_by_tech_id": None,
        "runtime_added_hours": 0,
    })
    db.repair_dispatches[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/repair-dispatches", methods=["GET"])
def list_dispatches():
    principal = get_principal()
    require_roles(principal, {"Customer", "Technician", "ServiceManager", "ComplianceOfficer"})
    records = list(db.repair_dispatches.values())
    for f in ("unit_id", "warranty_claim_id", "assigned_tech_id", "resolved_by_tech_id"):
        if f in request.args:
            val = request.args.get(f)
            records = [r for r in records if r.get(f) == val]
    return render_list(records)


@bp.route("/repair-dispatches/<dispatch_id>", methods=["GET"])
def get_dispatch(dispatch_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "Technician", "ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.repair_dispatches, dispatch_id)
    return success(out(rec), status=200)


# ---- Assign: REQUESTED -> DISPATCHED (OCC) --------------------------------
@bp.route("/repair-dispatches/<dispatch_id>/assign", methods=["POST"])
def assign_dispatch(dispatch_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager"})
    dispatch = find_or_404(db.repair_dispatches, dispatch_id)
    body = get_body()
    assigned_tech_id = require_str(body, "assigned_tech_id")
    expected_dispatch_version = require_int(body, "expected_dispatch_version")

    # FK reference (priority 4)
    tech = ref_or_404(db.technicians, assigned_tech_id)

    # OCC (priority 7)
    if expected_dispatch_version != dispatch["version"]:
        raise err("ERR_STALE_VERSION", "Dispatch version is stale")

    # state legality (priority 8)
    if dispatch["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Dispatch must be REQUESTED to assign")

    # tech must be ACTIVE
    if tech["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Technician is not ACTIVE")
    # load cap
    if tech["open_dispatch_count"] >= 5:
        raise err("ERR_TECH_OVERLOADED", "Technician already at capacity")

    dispatch["assigned_tech_id"] = assigned_tech_id
    dispatch["status"] = "DISPATCHED"
    db.touch(dispatch)
    tech["open_dispatch_count"] += 1
    db.touch(tech)
    return success(out(dispatch), status=200)


# ---- Start / Pause ---------------------------------------------------------
@bp.route("/repair-dispatches/<dispatch_id>/start", methods=["POST"])
def start_dispatch(dispatch_id):
    return _tech_transition(dispatch_id, "DISPATCHED", "IN_PROGRESS")


@bp.route("/repair-dispatches/<dispatch_id>/pause", methods=["POST"])
def pause_dispatch(dispatch_id):
    return _tech_transition(dispatch_id, "IN_PROGRESS", "DISPATCHED")


def _tech_transition(dispatch_id, from_state, to_state):
    principal = get_principal()
    require_roles(principal, {"Technician"})
    dispatch = find_or_404(db.repair_dispatches, dispatch_id)
    if principal.user_id != dispatch.get("assigned_tech_id"):
        raise err("ERR_NOT_ASSIGNED_TECH", "Acting technician is not assigned")
    if dispatch["status"] != from_state:
        raise err("ERR_INVALID_STATE", f"Dispatch must be {from_state}")
    dispatch["status"] = to_state
    db.touch(dispatch)
    return success(out(dispatch), status=200)


# ---- Resolve: IN_PROGRESS -> RESOLVED -------------------------------------
@bp.route("/repair-dispatches/<dispatch_id>/resolve", methods=["POST"])
def resolve_dispatch(dispatch_id):
    principal = get_principal()
    require_roles(principal, {"Technician"})
    dispatch = find_or_404(db.repair_dispatches, dispatch_id)
    body = get_body()
    runtime_added_hours = _opt_number(body, "runtime_added_hours", default=0, ge=0)

    if principal.user_id != dispatch.get("assigned_tech_id"):
        raise err("ERR_NOT_ASSIGNED_TECH", "Acting technician is not assigned")
    if dispatch["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Dispatch must be IN_PROGRESS to resolve")

    unit = db.units.get(dispatch["unit_id"])
    # NON_COMPLIANT blocks non-RECALL resolution (priority 9)
    if dispatch["origin"] != "RECALL" and unit["operating_status"] == "NON_COMPLIANT":
        raise err("ERR_UNIT_NON_COMPLIANT", "Unit is NON_COMPLIANT")

    dispatch["status"] = "RESOLVED"
    dispatch["resolved_by_tech_id"] = principal.user_id
    dispatch["runtime_added_hours"] = runtime_added_hours
    if dispatch["billable"]:
        dispatch["invoice_total_cents"] = calc.run_repair_invoice(
            dispatch["labor_cents"], dispatch["parts_cents"])
    db.touch(dispatch)

    unit["runtime_hours"] += runtime_added_hours

    # decrement tech load
    tech = db.technicians.get(dispatch["assigned_tech_id"])
    if tech is not None:
        tech["open_dispatch_count"] = max(0, tech["open_dispatch_count"] - 1)
        db.touch(tech)

    # RECALL origin: cascade linked remediation -> COMPLETED
    if dispatch["origin"] == "RECALL":
        _complete_linked_remediation(dispatch)

    posture.recompute_unit_posture(unit)
    return success(out(dispatch), status=200)


def _complete_linked_remediation(dispatch):
    for rem in db.recall_remediations.values():
        if rem.get("dispatch_id") != dispatch["id"]:
            continue
        if rem["status"] not in ("SCHEDULED", "OVERDUE"):
            continue
        rem["status"] = "COMPLETED"
        rem["completed_at"] = db.now_iso()
        db.touch(rem)
        campaign = db.recall_campaigns.get(rem["campaign_id"])
        if campaign is not None:
            campaign["remediated_count"] += 1
            db.touch(campaign)
        break


# ---- Close: RESOLVED -> CLOSED (segregation) ------------------------------
@bp.route("/repair-dispatches/<dispatch_id>/close", methods=["POST"])
def close_dispatch(dispatch_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager"})
    dispatch = find_or_404(db.repair_dispatches, dispatch_id)
    if dispatch["status"] != "RESOLVED":
        raise err("ERR_INVALID_STATE", "Dispatch must be RESOLVED to close")
    # segregation of duties: closing principal != resolved_by_tech_id
    if principal.user_id == dispatch.get("resolved_by_tech_id"):
        raise err("ERR_SEGREGATION_VIOLATION", "Closer must differ from resolver")
    dispatch["status"] = "CLOSED"
    db.touch(dispatch)
    unit = db.units.get(dispatch["unit_id"])
    posture.recompute_unit_posture(unit)
    return success(out(dispatch), status=200)


# ---- Cancel: REQUESTED/DISPATCHED -> CANCELLED ----------------------------
@bp.route("/repair-dispatches/<dispatch_id>/cancel", methods=["POST"])
def cancel_dispatch(dispatch_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager"})
    dispatch = find_or_404(db.repair_dispatches, dispatch_id)
    if dispatch["status"] not in ("REQUESTED", "DISPATCHED"):
        raise err("ERR_INVALID_STATE", "Dispatch cannot be cancelled in its current state")
    was_dispatched = dispatch["status"] == "DISPATCHED"
    dispatch["status"] = "CANCELLED"
    db.touch(dispatch)
    if was_dispatched and dispatch.get("assigned_tech_id"):
        tech = db.technicians.get(dispatch["assigned_tech_id"])
        if tech is not None:
            tech["open_dispatch_count"] = max(0, tech["open_dispatch_count"] - 1)
            db.touch(tech)
    return success(out(dispatch), status=200)
