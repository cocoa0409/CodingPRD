"""Work-order-operation (WIP node) execution endpoints (PRD §3.5, §3.6, §3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import lookups
import validators as V
from middleware import authenticate, authorize, get_json_body
from response import object_response, array_response
from serialize import public, public_list

bp = Blueprint("work_order_operations", __name__)

SIGNOFF_RESULTS = {"PASS", "FAIL"}


def _recompute_wip(wo):
    wo["wip_qty"] = wo["started_qty"] - wo["completed_qty"] - wo["scrapped_qty"]


def _is_final_op(wop):
    """True if this WIP node has the highest sequence_no in its work order."""
    siblings = [w for w in db.work_order_operations.values()
                if w["work_order_id"] == wop["work_order_id"]]
    max_seq = max(w["sequence_no"] for w in siblings)
    return wop["sequence_no"] == max_seq


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.route("/work-order-operations/<rid>", methods=["GET"])
def get_wop(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    return object_response(public(lookups.work_order_operation(rid)))


@bp.route("/work-order-operations", methods=["GET"])
def list_wops():
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    limit, offset = V.parse_pagination(request.args)
    operation_id = request.args.get("operation_id")
    machine_id = request.args.get("machine_id")
    work_order_id = request.args.get("work_order_id")
    status = request.args.get("status")
    rows = list(db.work_order_operations.values())
    if operation_id is not None:
        rows = [r for r in rows if r["operation_id"] == operation_id]
    if machine_id is not None:
        rows = [r for r in rows if r["machine_id"] == machine_id]
    if work_order_id is not None:
        rows = [r for r in rows if r["work_order_id"] == work_order_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Start (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.route("/work-order-operations/<rid>/start", methods=["POST"])
def start_wop(rid):
    _, role = authenticate()
    authorize(role, ["MachineOperator"])
    body = get_json_body()
    with db.LOCK:
        wop = lookups.work_order_operation(rid)

        # State (priority 4): start defined only from QUEUED.
        if wop["status"] != "QUEUED":
            raise errors.invalid_state("Only a QUEUED operation may be started.")

        wo = db.work_orders.get(wop["work_order_id"])
        # parent WO must be in RELEASED or IN_PROCESS.
        if wo is None or wo["status"] not in ("RELEASED", "IN_PROCESS"):
            raise errors.invalid_state("Parent work order is not RELEASED/IN_PROCESS.")

        # ERR_OPERATION_SEQUENCE_VIOLATION (priority 5): all lower-seq COMPLETED.
        for w in db.work_order_operations.values():
            if (w["work_order_id"] == wop["work_order_id"]
                    and w["sequence_no"] < wop["sequence_no"]
                    and w["status"] != "COMPLETED"):
                raise errors.ApiError(errors.ERR_OPERATION_SEQUENCE_VIOLATION,
                                      "A lower-sequence operation is not COMPLETED.", 409)

        # ERR_MACHINE_DOWN (priority 7).
        machine = db.machines.get(wop["machine_id"])
        if machine is not None and machine["status"] == "DOWN":
            raise errors.ApiError(errors.ERR_MACHINE_DOWN,
                                  "Referenced machine is DOWN.", 409)

        # Parse optional schedule + units_in.
        scheduled_start = wop.get("scheduled_start")
        scheduled_end = wop.get("scheduled_end")
        if "scheduled_start" in body and body["scheduled_start"] is not None:
            scheduled_start = V.as_datetime(body["scheduled_start"], "scheduled_start")
        if "scheduled_end" in body and body["scheduled_end"] is not None:
            scheduled_end = V.as_datetime(body["scheduled_end"], "scheduled_end")

        if "units_in" in body and body["units_in"] is not None:
            units_in = V.as_int(body["units_in"], "units_in")
            if units_in < 0:
                raise errors.invalid_request("units_in must be >= 0.")
        else:
            units_in = wo["order_qty"]

        # ERR_SETUP_BUFFER_CONFLICT (priority 10): clear prior op on same work
        # center by [scheduled_end + setup_buffer_secs], closed interval.
        if scheduled_start is not None and machine is not None:
            this_start = V.parse_dt(scheduled_start)
            work_center = machine["work_center"]
            prior = _prior_op_same_work_center(wop, work_center)
            if prior is not None and prior.get("scheduled_end") is not None:
                prior_op = db.operations.get(prior["operation_id"])
                buffer_secs = prior_op["setup_buffer_secs"] if prior_op else 0
                prior_end = V.parse_dt(prior["scheduled_end"])
                buffered_end = prior_end + timedelta(seconds=buffer_secs)
                # closed buffered interval: starting at or before buffered_end conflicts
                if this_start <= buffered_end:
                    raise errors.ApiError(errors.ERR_SETUP_BUFFER_CONFLICT,
                                          "Start window violates prior op setup buffer.", 409)

        # Apply side effects.
        wop["units_in"] = units_in
        wop["scheduled_start"] = scheduled_start
        wop["scheduled_end"] = scheduled_end
        wop["status"] = "IN_PROGRESS"
        db.touch(wop)

        if machine is not None:
            machine["status"] = "RUNNING"
            db.touch(machine)

        # First op of the order -> bubble WO to IN_PROCESS.
        if _is_first_started(wop):
            if wo["status"] in ("PLANNED", "RELEASED"):
                wo["status"] = "IN_PROCESS"
                wo["started_qty"] = wo["order_qty"]
                _recompute_wip(wo)
                db.touch(wo)

        return object_response(public(wop))


def _prior_op_same_work_center(wop, work_center):
    """The WIP node with the greatest sequence_no strictly below this one whose
    machine sits on the same work center."""
    candidates = []
    for w in db.work_order_operations.values():
        if w["work_order_id"] != wop["work_order_id"]:
            continue
        if w["sequence_no"] >= wop["sequence_no"]:
            continue
        m = db.machines.get(w["machine_id"])
        if m is not None and m["work_center"] == work_center:
            candidates.append(w)
    if not candidates:
        return None
    candidates.sort(key=lambda w: w["sequence_no"])
    return candidates[-1]


def _is_first_started(wop):
    """True if this node has the minimum sequence_no among its work order's
    operations (the first op)."""
    siblings = [w for w in db.work_order_operations.values()
                if w["work_order_id"] == wop["work_order_id"]]
    min_seq = min(w["sequence_no"] for w in siblings)
    return wop["sequence_no"] == min_seq


# ---------------------------------------------------------------------------
# Pause / Resume (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.route("/work-order-operations/<rid>/pause", methods=["POST"])
def pause_wop(rid):
    _, role = authenticate()
    authorize(role, ["MachineOperator"])
    with db.LOCK:
        wop = lookups.work_order_operation(rid)
        if wop["status"] != "IN_PROGRESS":
            raise errors.invalid_state("Only an IN_PROGRESS operation may be paused.")
        wop["status"] = "PAUSED"
        db.touch(wop)
        machine = db.machines.get(wop["machine_id"])
        if machine is not None:
            machine["status"] = "AVAILABLE"
            db.touch(machine)
        return object_response(public(wop))


@bp.route("/work-order-operations/<rid>/resume", methods=["POST"])
def resume_wop(rid):
    _, role = authenticate()
    authorize(role, ["MachineOperator"])
    with db.LOCK:
        wop = lookups.work_order_operation(rid)
        # resume defined from PAUSED or REWORK.
        if wop["status"] not in ("PAUSED", "REWORK"):
            raise errors.invalid_state("Only a PAUSED or REWORK operation may be resumed.")
        machine = db.machines.get(wop["machine_id"])
        if machine is not None and machine["status"] == "DOWN":
            raise errors.ApiError(errors.ERR_MACHINE_DOWN,
                                  "Referenced machine is DOWN.", 409)
        wop["status"] = "IN_PROGRESS"
        db.touch(wop)
        # PAUSED->IN_PROGRESS sets machine RUNNING; REWORK->IN_PROGRESS scaffold
        # lists no machine side effect, but resume semantics set RUNNING for both.
        if machine is not None:
            machine["status"] = "RUNNING"
            db.touch(machine)
        return object_response(public(wop))


# ---------------------------------------------------------------------------
# Complete (PRD §3.5)
# ---------------------------------------------------------------------------
@bp.route("/work-order-operations/<rid>/complete", methods=["POST"])
def complete_wop(rid):
    _, role = authenticate()
    authorize(role, ["MachineOperator"])
    body = get_json_body()
    with db.LOCK:
        wop = lookups.work_order_operation(rid)
        if wop["status"] != "IN_PROGRESS":
            raise errors.invalid_state("Only an IN_PROGRESS operation may be completed.")

        good_qty = V.as_int(V.require(body, "good_qty"), "good_qty")
        if good_qty < 0:
            raise errors.invalid_request("good_qty must be >= 0.")

        # ERR_TRAVELER_NOT_SIGNED (priority 8): a PASS signoff must exist and be
        # active (not voided).
        has_pass = any(
            s["work_order_operation_id"] == rid
            and s["result"] == "PASS"
            and not s.get("_voided", False)
            for s in db.traveler_signoffs.values())
        if not has_pass:
            raise errors.ApiError(errors.ERR_TRAVELER_NOT_SIGNED,
                                  "A PASS traveler sign-off is required.", 409)

        # unit balance: good_qty + scrap_qty == units_in.
        if good_qty + wop["scrap_qty"] != wop["units_in"]:
            raise errors.invalid_request(
                "good_qty + scrap_qty must equal units_in.")

        wop["good_qty"] = good_qty
        wop["status"] = "COMPLETED"
        db.touch(wop)

        machine = db.machines.get(wop["machine_id"])
        if machine is not None:
            machine["status"] = "AVAILABLE"
            db.touch(machine)

        # final op -> roll completed_qty up.
        if _is_final_op(wop):
            wo = db.work_orders.get(wop["work_order_id"])
            if wo is not None:
                wo["completed_qty"] = wo["completed_qty"] + good_qty
                _recompute_wip(wo)
                db.touch(wo)

        return object_response(public(wop))


# ---------------------------------------------------------------------------
# Traveler sign-offs (PRD §3.6)
# ---------------------------------------------------------------------------
@bp.route("/work-order-operations/<rid>/signoffs", methods=["POST"])
def create_signoff(rid):
    user_id, role = authenticate()
    authorize(role, ["QualityInspector", "PlantAdmin"])
    body = get_json_body()
    with db.LOCK:
        wop = lookups.work_order_operation(rid)
        result = V.as_enum(V.require(body, "result"), "result", SIGNOFF_RESULTS)
        # TravelerSignoff: append-only, only id + created_at (no version/updated_at).
        rec = db.new_record(with_version=False)
        rec.update({
            "work_order_operation_id": rid,
            "inspector_user_id": user_id,
            "result": result,
            "signed_at": db.now_iso(),
            "_voided": False,
        })
        db.traveler_signoffs[rec["id"]] = rec
        # _voided is internal bookkeeping; strip it from output.
        out = public(rec)
        out.pop("_voided", None)
        return object_response(out, 201)


@bp.route("/work-order-operations/<rid>/signoffs", methods=["GET"])
def list_signoffs(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    lookups.work_order_operation(rid)
    limit, offset = V.parse_pagination(request.args)
    rows = [s for s in db.traveler_signoffs.values() if s["work_order_operation_id"] == rid]
    page, total = V.paginate(rows, limit, offset)
    out = []
    for s in page:
        o = public(s)
        o.pop("_voided", None)
        out.append(o)
    return array_response(out, limit, offset, total)


# ---------------------------------------------------------------------------
# Scrap dispositions (raise) (PRD §3.7)
# ---------------------------------------------------------------------------
@bp.route("/work-order-operations/<rid>/scrap-dispositions", methods=["POST"])
def raise_scrap(rid):
    _, role = authenticate()
    authorize(role, ["MachineOperator", "QualityInspector"])
    body = get_json_body()
    with db.LOCK:
        wop = lookups.work_order_operation(rid)
        quantity = V.as_int(V.require(body, "quantity"), "quantity")
        defect_code = V.as_string(V.require(body, "defect_code"), "defect_code")
        if quantity <= 0:
            raise errors.invalid_request("quantity must be > 0.")

        # ERR_SCRAP_QTY_EXCEEDS (priority 13): qty <= units_in - scrap_qty.
        available = wop["units_in"] - wop["scrap_qty"]
        if quantity > available:
            raise errors.ApiError(errors.ERR_SCRAP_QTY_EXCEEDS,
                                  "Scrap quantity exceeds available units.", 422)

        rec = db.new_record()
        rec.update({
            "work_order_operation_id": rid,
            "quantity": quantity,
            "defect_code": defect_code,
            "status": "PENDING",
            "scrap_cost_cents": 0,
        })
        db.scrap_dispositions[rec["id"]] = rec
        return object_response(public(rec), 201)


@bp.route("/work-order-operations/<rid>/scrap-dispositions", methods=["GET"])
def list_scrap_for_wop(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    lookups.work_order_operation(rid)
    limit, offset = V.parse_pagination(request.args)
    rows = [s for s in db.scrap_dispositions.values() if s["work_order_operation_id"] == rid]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)
