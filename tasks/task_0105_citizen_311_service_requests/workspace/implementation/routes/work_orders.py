"""WorkOrder endpoints (PRD §3.4): assign, start, complete, cancel + reads."""
from flask import Blueprint, request as flask_request

import db
import errors
import validate
import serialize
from middleware import authenticate, authorize
import response
from services import calc, workflow

bp = Blueprint("work_orders", __name__)


@bp.route("/work-orders/<wid>", methods=["GET"])
def get_work_order(wid):
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher", "Agent"})
    rec = db.work_orders.get(wid)
    if rec is None:
        raise errors.not_found("Work order not found.")
    return response.object_response(serialize.view("work_order", rec))


@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    p = authenticate()
    authorize(p, {"SystemAdmin", "Dispatcher", "Agent"})
    limit, offset = validate.pagination()
    args = flask_request.args
    f_request = args.get("request_id")
    f_department = args.get("department_id")
    f_agent = args.get("assigned_agent_id")
    f_status = args.get("status")

    def pred(r):
        if f_request is not None and r["request_id"] != f_request:
            return False
        if f_department is not None and r["department_id"] != f_department:
            return False
        if f_agent is not None and r.get("assigned_agent_id") != f_agent:
            return False
        if f_status is not None and r["status"] != f_status:
            return False
        return True

    rows = db.ordered(db.work_orders, pred)
    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(serialize.view_list("work_order", page), limit, offset, total)


@bp.route("/work-orders/<wid>/assign", methods=["POST"])
def assign(wid):
    p = authenticate()
    authorize(p, {"Dispatcher"})
    wo = db.work_orders.get(wid)
    if wo is None:
        raise errors.not_found("Work order not found.")
    data = validate.body()
    assigned_agent_id = validate.require_str(data, "assigned_agent_id")
    expected_work_order_version = validate.require_int(data, "expected_work_order_version")

    # Existence (priority 3): the agent body id.
    agent = db.agents.get(assigned_agent_id)
    if agent is None:
        raise errors.not_found("Agent not found.")

    # priority 5: agent belongs to the work order's department.
    if agent["department_id"] != wo["department_id"]:
        raise errors.agent_wrong_department()

    # priority 6: state — assign is a field-set permitted while OPEN.
    if wo["status"] != "OPEN":
        raise errors.invalid_state("Work order is not OPEN.")

    # priority 7: OCC on work order version.
    if expected_work_order_version != wo["version"]:
        raise errors.stale_version("Work order version is stale.")

    wo["assigned_agent_id"] = assigned_agent_id
    db.touch(wo)
    return response.object_response(serialize.view("work_order", wo))


@bp.route("/work-orders/<wid>/start", methods=["POST"])
def start(wid):
    p = authenticate()
    authorize(p, {"Agent"})
    wo = db.work_orders.get(wid)
    if wo is None:
        raise errors.not_found("Work order not found.")

    # priority 5: acting agent belongs to the work order's department.
    agent = db.agents.get(p.user_id)
    if agent is None or agent["department_id"] != wo["department_id"]:
        raise errors.agent_wrong_department()

    # priority 6: state + assigned.
    if wo["status"] != "OPEN":
        raise errors.invalid_state("Work order is not OPEN.")
    if wo.get("assigned_agent_id") is None:
        raise errors.invalid_state("Work order has no assigned agent.")

    wo["status"] = "IN_PROGRESS"
    db.touch(wo)

    # Bubble-up: request ROUTED->IN_PROGRESS.
    req = db.service_requests.get(wo["request_id"])
    if req is not None and req["status"] == "ROUTED":
        workflow.request_to_in_progress(req)
    return response.object_response(serialize.view("work_order", wo))


@bp.route("/work-orders/<wid>/complete", methods=["POST"])
def complete(wid):
    p = authenticate()
    authorize(p, {"Agent"})
    wo = db.work_orders.get(wid)
    if wo is None:
        raise errors.not_found("Work order not found.")

    # priority 5: acting agent belongs to the work order's department.
    agent = db.agents.get(p.user_id)
    if agent is None or agent["department_id"] != wo["department_id"]:
        raise errors.agent_wrong_department()

    data = validate.body()

    # priority 6: state.
    if wo["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Work order is not IN_PROGRESS.")

    # Acting agent must be the assigned agent.
    if wo.get("assigned_agent_id") != p.user_id:
        raise errors.agent_wrong_department()

    # completion_note required (priority 18 schema).
    completion_note = validate.require_str(data, "completion_note")

    wo["completion_note"] = completion_note
    wo["status"] = "COMPLETED"
    db.touch(wo)

    dept = db.departments.get(wo["department_id"])
    if dept is not None:
        calc.department_backlog(dept)

    # Bubble-up cascade: request IN_PROGRESS->RESOLVED (survey + escalation resolve).
    req = db.service_requests.get(wo["request_id"])
    if req is not None and req["status"] == "IN_PROGRESS":
        workflow.request_to_resolved(req)
    return response.object_response(serialize.view("work_order", wo))


@bp.route("/work-orders/<wid>/cancel", methods=["POST"])
def cancel(wid):
    p = authenticate()
    authorize(p, {"Dispatcher"})
    wo = db.work_orders.get(wid)
    if wo is None:
        raise errors.not_found("Work order not found.")
    # priority 6: state — only an OPEN work order may be cancelled.
    if wo["status"] != "OPEN":
        raise errors.invalid_state("Work order is not OPEN.")

    wo["status"] = "CANCELLED"
    db.touch(wo)
    dept = db.departments.get(wo["department_id"])
    if dept is not None:
        calc.department_backlog(dept)
    return response.object_response(serialize.view("work_order", wo))
