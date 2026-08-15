"""CorrugatorRun endpoints."""
from decimal import Decimal

from flask import Blueprint, request

from db import db
from errors import (
    err_board_source_mismatch,
    err_invalid_request,
    err_invalid_state,
    err_machine_type_mismatch,
    err_not_found,
    err_order_grade_mismatch,
    err_outside_shift_window,
    err_run_window_overlap,
    err_trim_waste_excessive,
    err_trim_width_exceeds_web,
)
from middleware import require_roles
from response import success_object
from services.calcs import (
    bump,
    recompute_credit_exposure,
    recompute_run_trim,
    recompute_shift_rollup,
)
from services.cascade import cancel_run_orders
from services.serialize import serialize_corrugator_run
from util import D, is_int, is_num, new_id, utcnow_iso
from ._helpers import get_json_body, paginate_list, require_fields

bp = Blueprint("corrugator_runs", __name__)

ALL_ROLES = ("PlantAdmin", "SalesRep", "ProductionPlanner", "CustomerService", "ClaimsAdjuster", "Customer")


def _get_run_or_404(rid):
    r = db.corrugator_runs.get(rid)
    if r is None:
        raise err_not_found("corrugator run not found")
    return r


@bp.route("/api/corrugator-runs", methods=["POST"])
@require_roles("ProductionPlanner")
def create_corrugator_run(_user_id, _role):
    body = get_json_body()
    require_fields(body, ["work_shift_id", "board_grade_id", "start_minute", "end_minute", "web_width_in"])

    work_shift_id = body["work_shift_id"]
    board_grade_id = body["board_grade_id"]
    start_minute = body["start_minute"]
    end_minute = body["end_minute"]
    web_width = body["web_width_in"]

    # Well-formedness
    if not is_int(start_minute) or start_minute < 0:
        raise err_invalid_request("start_minute must be an integer >= 0")
    if not is_int(end_minute) or end_minute <= start_minute:
        raise err_invalid_request("end_minute must be > start_minute")
    if not is_num(web_width) or D(web_width) <= 0:
        raise err_invalid_request("web_width_in must be > 0")

    # Existence (priority 3)
    shift = db.work_shifts.get(work_shift_id)
    if shift is None:
        raise err_not_found("work shift not found")
    grade = db.board_grades.get(board_grade_id)
    if grade is None:
        raise err_not_found("board grade not found")

    # Shift must be OPEN (priority 4)
    if shift["status"] != "OPEN":
        raise err_invalid_state("work shift is not OPEN")

    # Machine compatibility (priority 6)
    if shift["machine_code"] != "CORRUGATOR":
        raise err_machine_type_mismatch("corrugator run requires a CORRUGATOR shift")

    # Window containment (priority 8)
    if start_minute < shift["start_minute"] or end_minute > shift["end_minute"]:
        raise err_outside_shift_window("run window not contained in the shift window")

    # Pairwise half-open overlap vs non-CANCELLED runs on this shift (priority 8)
    for r in db.corrugator_runs.values():
        if r["work_shift_id"] != shift["id"]:
            continue
        if r["status"] == "CANCELLED":
            continue
        # overlap iff new.start < existing.end AND existing.start < new.end
        if start_minute < r["end_minute"] and r["start_minute"] < end_minute:
            raise err_run_window_overlap("corrugator run overlaps another non-CANCELLED run on the shift")

    now = utcnow_iso()
    rid = new_id()
    run = {
        "id": rid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "work_shift_id": work_shift_id,
        "board_grade_id": board_grade_id,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "web_width_in": D(web_width),
        "consumed_width_in": Decimal("0"),
        "trim_waste_in": D(web_width),
        "trim_waste_pct": Decimal("100.00"),
        "status": "SCHEDULED",
    }
    db.corrugator_runs[rid] = run
    db.run_outs[rid] = {}

    recompute_shift_rollup(shift)
    bump(shift)

    return success_object(serialize_corrugator_run(run), 201)


@bp.route("/api/corrugator-runs/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_corrugator_run(rid, _user_id, _role):
    r = _get_run_or_404(rid)
    return success_object(serialize_corrugator_run(r), 200)


@bp.route("/api/corrugator-runs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_corrugator_runs(_user_id, _role):
    filters = {
        "work_shift_id": request.args.get("work_shift_id"),
        "board_grade_id": request.args.get("board_grade_id"),
        "status": request.args.get("status"),
    }
    return paginate_list(list(db.corrugator_runs.values()), serialize_corrugator_run, filters)


@bp.route("/api/corrugator-runs/<rid>/orders", methods=["POST"])
@require_roles("ProductionPlanner")
def attach_order(rid, _user_id, _role):
    run = _get_run_or_404(rid)
    body = get_json_body()
    require_fields(body, ["box_order_id", "outs"])

    box_order_id = body["box_order_id"]
    outs = body["outs"]

    # Well-formedness
    if not is_int(outs) or outs <= 0:
        raise err_invalid_request("outs must be an integer > 0")

    # Existence
    order = db.box_orders.get(box_order_id)
    if order is None:
        raise err_not_found("box order not found")

    # State: order must be ACCEPTED
    if order["status"] != "ACCEPTED":
        raise err_invalid_state(f"order status {order['status']} is not ACCEPTED")

    # Board source: only INTERNAL attaches
    if order["board_source"] != "INTERNAL":
        raise err_board_source_mismatch("only INTERNAL orders attach to corrugator runs")

    # Order grade must match run grade
    if order["board_grade_id"] != run["board_grade_id"]:
        raise err_order_grade_mismatch("attached order's grade differs from the run's grade")

    # Run must be SCHEDULED and shift OPEN
    if run["status"] != "SCHEDULED":
        raise err_invalid_state("run is not SCHEDULED")
    shift = db.work_shifts.get(run["work_shift_id"])
    if shift is None:
        raise err_not_found("work shift not found")
    if shift["status"] != "OPEN":
        raise err_invalid_state("work shift is not OPEN")

    # Trim fit gate
    new_consumed = D(run["consumed_width_in"]) + D(outs) * D(order["blank_width_in"])
    if new_consumed > D(run["web_width_in"]):
        raise err_trim_width_exceeds_web("attach would push consumed_width_in above web_width_in")

    # Commit
    order["status"] = "SCHEDULED"
    order["corrugator_run_id"] = run["id"]
    bump(order)

    db.run_outs.setdefault(run["id"], {})[order["id"]] = outs
    recompute_run_trim(run)
    bump(run)

    # Recompute customer exposure (order moved into SCHEDULED pipeline state)
    cust = db.customer_accounts.get(order["customer_id"])
    if cust is not None:
        recompute_credit_exposure(cust)
        bump(cust)

    return success_object(serialize_corrugator_run(run), 200)


@bp.route("/api/corrugator-runs/<rid>/complete", methods=["POST"])
@require_roles("ProductionPlanner")
def complete_run(rid, _user_id, _role):
    run = _get_run_or_404(rid)

    if run["status"] != "SCHEDULED":
        raise err_invalid_state("run is not SCHEDULED")
    shift = db.work_shifts.get(run["work_shift_id"])
    if shift is None:
        raise err_not_found("work shift not found")
    if shift["status"] != "OPEN":
        raise err_invalid_state("work shift is not OPEN")

    # Trim-waste gate at completion
    if D(run["trim_waste_in"]) > Decimal("8.0"):
        raise err_trim_waste_excessive("trim_waste_in exceeds 8.0 inches")

    # Flip run
    run["status"] = "COMPLETED"
    bump(run)

    # Advance attached SCHEDULED orders to AWAITING_CONVERTING (retain corrugator_run_id)
    for o in db.box_orders.values():
        if o.get("corrugator_run_id") == run["id"] and o.get("status") == "SCHEDULED":
            o["status"] = "AWAITING_CONVERTING"
            bump(o)
            cust = db.customer_accounts.get(o["customer_id"])
            if cust is not None:
                recompute_credit_exposure(cust)
                bump(cust)

    # Shift rollup recomputes (completed run keeps occupying minutes)
    recompute_shift_rollup(shift)
    bump(shift)

    return success_object(serialize_corrugator_run(run), 200)


@bp.route("/api/corrugator-runs/<rid>/cancel", methods=["POST"])
@require_roles("ProductionPlanner")
def cancel_run(rid, _user_id, _role):
    run = _get_run_or_404(rid)
    if run["status"] != "SCHEDULED":
        raise err_invalid_state("run is not SCHEDULED")
    shift = db.work_shifts.get(run["work_shift_id"])
    if shift is None:
        raise err_not_found("work shift not found")

    run["status"] = "CANCELLED"
    # Revert attached orders
    cancel_run_orders(run)
    recompute_run_trim(run)
    bump(run)

    # Shift rollup recomputes (cancelled run frees its minutes)
    recompute_shift_rollup(shift)
    bump(shift)

    return success_object(serialize_corrugator_run(run), 200)
