"""SewingLine, LineAssignment, and Operator endpoints (PRD §3.6, §3.7)."""

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, ALL_ROLES, ROLE_PRODUCTION_PLANNER, ROLE_LINE_SUPERVISOR,
)
from response import success_object
from util import get_body, req_str, req_int, req_date, fk_exists
from errors import (
    invalid_request, not_found, invalid_time_window, line_capacity_exceeded,
    operator_schedule_overlap,
)
from services.calc import (
    line_balance, operator_efficiency, CHANGEOVER_BUFFER_MINUTES,
)
from services.core import (
    base_record, public, get_sewing_line, get_line_assignment, get_operator,
    get_production_order, get_tech_pack,
)
from routes.common import list_response, active_filters

bp = Blueprint("sewing", __name__)


# --- Sewing lines -----------------------------------------------------------
@bp.route("/sewing-lines", methods=["POST"])
def create_sewing_line():
    require_roles([ROLE_PRODUCTION_PLANNER])
    body = get_body()
    line_code = req_str(body, "line_code")
    station_count = req_int(body, "station_count", min_v=1)
    shift_minutes = req_int(body, "shift_minutes", min_v=1)
    if any(l["line_code"] == line_code for l in store.sewing_lines.values()):
        raise invalid_request("line_code must be unique")

    rec = base_record()
    rec.update({
        "line_code": line_code,
        "station_count": station_count,
        "shift_minutes": shift_minutes,
    })
    store.sewing_lines[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/sewing-lines/<line_id>/balance", methods=["GET"])
def get_line_balance(line_id):
    require_roles(ALL_ROLES)
    line = get_sewing_line(line_id)
    order_id = request.args.get("production_order_id")
    if not order_id:
        raise invalid_request("production_order_id query parameter is required")
    order = store.production_orders.get(order_id)
    if order is None:
        raise not_found(f"ProductionOrder {order_id} not found")
    if order["tech_pack_id"] is None:
        raise invalid_request(
            "production order has no pinned tech pack to balance against")
    pack = get_tech_pack(order["tech_pack_id"])
    return success_object(line_balance(line, pack))


# --- Line assignments -------------------------------------------------------
def _check_station_capacity(line, shift_date, new_start, new_end):
    """Half-open [start, end) interval aggregate capacity (PRD §3.6)."""
    events = []
    for a in store.line_assignments.values():
        if a["sewing_line_id"] == line["id"] and a["shift_date"] == shift_date:
            events.append((a["start_minute"], +1))
            events.append((a["end_minute"], -1))
    events.append((new_start, +1))
    events.append((new_end, -1))
    # At a shared minute, ends land before starts so pure adjacency (end ==
    # start) never counts as overlap.
    events.sort(key=lambda e: (e[0], e[1]))
    concurrent = 0
    peak = 0
    for _, delta in events:
        concurrent += delta
        peak = max(peak, concurrent)
    if peak > line["station_count"]:
        raise line_capacity_exceeded(
            "overlapping assignments would exceed the line's station_count")


def _check_operator_buffer(operator_id, shift_date, new_start, new_end):
    """Buffered exclusion: 15-minute changeover around every existing
    assignment of the same operator on the same shift date; pure adjacency is
    rejected (PRD §3.6)."""
    buf = CHANGEOVER_BUFFER_MINUTES
    for a in store.line_assignments.values():
        if a["operator_id"] == operator_id and a["shift_date"] == shift_date:
            if not (new_start >= a["end_minute"] + buf
                    or new_end <= a["start_minute"] - buf):
                raise operator_schedule_overlap(
                    "assignment violates the operator's 15-minute changeover "
                    "buffer")


@bp.route("/line-assignments", methods=["POST"])
def create_line_assignment():
    require_roles([ROLE_LINE_SUPERVISOR])
    body = get_body()
    fk_exists(body, "sewing_line_id", store.sewing_lines, "SewingLine")
    fk_exists(body, "production_order_id", store.production_orders,
              "ProductionOrder")
    fk_exists(body, "operation_spec_id", store.operation_specs, "OperationSpec")
    fk_exists(body, "operator_id", store.operators, "Operator")
    sewing_line_id = req_str(body, "sewing_line_id")
    production_order_id = req_str(body, "production_order_id")
    operation_spec_id = req_str(body, "operation_spec_id")
    operator_id = req_str(body, "operator_id")
    shift_date = req_date(body, "shift_date")
    start_minute = req_int(body, "start_minute", min_v=0, max_v=1440)
    end_minute = req_int(body, "end_minute", min_v=0, max_v=1440)
    assigned_pieces = req_int(body, "assigned_pieces", min_v=1)
    # Temporal rules (pipeline step 10): window, then station capacity, then
    # operator changeover buffer.
    if not (start_minute < end_minute):
        raise invalid_time_window(
            "must satisfy 0 <= start_minute < end_minute <= 1440")
    line = get_sewing_line(sewing_line_id)
    _check_station_capacity(line, shift_date, start_minute, end_minute)
    _check_operator_buffer(operator_id, shift_date, start_minute, end_minute)

    rec = base_record()
    rec.update({
        "sewing_line_id": sewing_line_id,
        "production_order_id": production_order_id,
        "operation_spec_id": operation_spec_id,
        "operator_id": operator_id,
        "shift_date": shift_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "assigned_pieces": assigned_pieces,
    })
    store.line_assignments[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/line-assignments", methods=["GET"])
def list_line_assignments():
    require_roles(ALL_ROLES)
    filters = active_filters([
        ("sewing_line_id", request.args.get("sewing_line_id")),
        ("production_order_id", request.args.get("production_order_id")),
        ("operation_spec_id", request.args.get("operation_spec_id")),
        ("operator_id", request.args.get("operator_id")),
    ])
    return list_response(store.line_assignments.values(), filters)


@bp.route("/line-assignments/<assignment_id>", methods=["GET"])
def get_line_assignment_endpoint(assignment_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_line_assignment(assignment_id)))


# --- Operators --------------------------------------------------------------
def public_operator(op):
    d = public(op)
    eff, _, _ = operator_efficiency(op["id"])
    d["efficiency_pct"] = eff
    return d


@bp.route("/operators", methods=["POST"])
def create_operator():
    require_roles([ROLE_LINE_SUPERVISOR])
    body = get_body()
    employee_no = req_str(body, "employee_no")
    full_name = req_str(body, "full_name")
    if any(o["employee_no"] == employee_no for o in store.operators.values()):
        raise invalid_request("employee_no must be unique")

    rec = base_record()
    rec.update({
        "employee_no": employee_no,
        "full_name": full_name,
        "status": "ACTIVE",
        "efficiency_pct": 0,
        "ytd_earnings_cents": 0,
    })
    store.operators[rec["id"]] = rec
    return success_object(public_operator(rec), status=201)


@bp.route("/operators/<operator_id>", methods=["GET"])
def get_operator_endpoint(operator_id):
    require_roles(ALL_ROLES)
    return success_object(public_operator(get_operator(operator_id)))


@bp.route("/operators/<operator_id>/efficiency", methods=["GET"])
def get_operator_efficiency(operator_id):
    require_roles(ALL_ROLES)
    op = get_operator(operator_id)
    eff, earned, attended = operator_efficiency(op["id"])
    return success_object({
        "efficiency_pct": eff,
        "earned_minutes": earned,
        "attended_minutes": attended,
    })
