"""InstallOrder endpoints (PRD §3.7)."""
from flask import Blueprint, request

import db
import errors
import helpers
from clock import clock
from middleware import authenticate, authorize, get_json_body, get_pagination
from response import object_response, array_response
from serializers import serialize, serialize_list
from services import calculations

bp = Blueprint("install_orders", __name__)


def _release_bookings(order):
    """Release all RESERVED/CONFIRMED bookings for this order (cascade)."""
    for b in db.crew_bookings.items.values():
        if b["install_order_id"] == order["id"] and b["status"] in ("RESERVED", "CONFIRMED"):
            b["status"] = "RELEASED"
            helpers.touch(b)


@bp.route("/install-orders/<install_order_id>", methods=["GET"])
def get_order(install_order_id):
    _uid, role = authenticate()
    authorize(role, ["Scheduler", "Inspector", "WarrantyAdmin"])
    entity = helpers.find_or_404(db.install_orders, install_order_id)
    return object_response(serialize(entity), status=200)


@bp.route("/install-orders", methods=["GET"])
def list_orders():
    _uid, role = authenticate()
    authorize(role, ["Scheduler", "Inspector", "WarrantyAdmin"])
    limit, offset = get_pagination()
    job_id = request.args.get("job_id")
    status = request.args.get("status")

    def pred(o):
        if job_id is not None and o["job_id"] != job_id:
            return False
        if status is not None and o["status"] != status:
            return False
        return True

    page, total = helpers.paginate_list(db.install_orders, limit, offset, pred)
    return array_response(serialize_list(page), limit, offset, total)


@bp.route("/install-orders/<install_order_id>/dispatch", methods=["POST"])
def dispatch_order(install_order_id):
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    order = helpers.find_or_404(db.install_orders, install_order_id)
    # state: PLANNED (PRD §3.7).
    if order["status"] != "PLANNED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a PLANNED order can be dispatched")
    # precondition: at least one CONFIRMED crew booking exists.
    has_confirmed = any(
        b["install_order_id"] == install_order_id and b["status"] == "CONFIRMED"
        for b in db.crew_bookings.items.values()
    )
    if not has_confirmed:
        raise errors.err(errors.ERR_INVALID_STATE, "Dispatch requires a CONFIRMED crew booking")
    order["status"] = "DISPATCHED"
    helpers.touch(order)
    return object_response(serialize(order), status=200)


@bp.route("/install-orders/<install_order_id>/start", methods=["POST"])
def start_order(install_order_id):
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    order = helpers.find_or_404(db.install_orders, install_order_id)
    # DISPATCHED -> IN_PROGRESS (requires clock >= scheduled_start), or FAILED -> IN_PROGRESS (no clock check).
    if order["status"] == "DISPATCHED":
        if clock.now() < helpers.parse_iso(order["scheduled_start"]):
            raise errors.err(errors.ERR_INVALID_STATE, "Cannot start before scheduled_start")
        order["status"] = "IN_PROGRESS"
        helpers.touch(order)
    elif order["status"] == "FAILED":
        order["status"] = "IN_PROGRESS"
        helpers.touch(order)
    else:
        raise errors.err(errors.ERR_INVALID_STATE, "Start requires DISPATCHED or FAILED order")
    return object_response(serialize(order), status=200)


@bp.route("/install-orders/<install_order_id>/inspect-pass", methods=["POST"])
def inspect_pass(install_order_id):
    _uid, role = authenticate()
    authorize(role, ["Inspector"])
    order = helpers.find_or_404(db.install_orders, install_order_id)
    if order["status"] != "IN_PROGRESS":
        raise errors.err(errors.ERR_INVALID_STATE, "Pass requires an IN_PROGRESS order")
    order["status"] = "PASSED"
    helpers.touch(order)
    return object_response(serialize(order), status=200)


@bp.route("/install-orders/<install_order_id>/inspect-fail", methods=["POST"])
def inspect_fail(install_order_id):
    _uid, role = authenticate()
    authorize(role, ["Inspector"])
    order = helpers.find_or_404(db.install_orders, install_order_id)
    if order["status"] != "IN_PROGRESS":
        raise errors.err(errors.ERR_INVALID_STATE, "Fail requires an IN_PROGRESS order")
    order["status"] = "FAILED"
    helpers.touch(order)
    return object_response(serialize(order), status=200)


@bp.route("/install-orders/<install_order_id>/complete", methods=["POST"])
def complete_order(install_order_id):
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    order = helpers.find_or_404(db.install_orders, install_order_id)
    body = get_json_body()
    actual_drain_linear_ft = helpers.optional_int(body, "actual_drain_linear_ft", 0)
    if actual_drain_linear_ft < 0:
        raise errors.err(errors.ERR_VALIDATION, "actual_drain_linear_ft must be at least 0")

    job = db.jobs.items.get(order["job_id"])
    # state: order PASSED and Job SCHEDULED (PRD §3.7).
    if order["status"] != "PASSED":
        raise errors.err(errors.ERR_INVALID_STATE, "Only a PASSED order can be completed")
    if job is None or job["lifecycle_status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Completion requires the job in SCHEDULED")

    order["actual_drain_linear_ft"] = actual_drain_linear_ft
    accepted_quote = db.quotes.items.get(order["quote_id"])
    final_total, variance = calculations.reconcile_install(
        job["footprint_sqft"], accepted_quote, actual_drain_linear_ft
    )
    order["final_total_cents"] = final_total
    order["variance_cents"] = variance
    order["status"] = "COMPLETED"
    helpers.touch(order)

    job["lifecycle_status"] = "INSTALLED"
    helpers.touch(job)
    _release_bookings(order)
    return object_response(serialize(order), status=200)


@bp.route("/install-orders/<install_order_id>/cancel", methods=["POST"])
def cancel_order(install_order_id):
    _uid, role = authenticate()
    authorize(role, ["Scheduler"])
    order = helpers.find_or_404(db.install_orders, install_order_id)
    # state: PLANNED or DISPATCHED (PRD §3.7).
    if order["status"] not in ("PLANNED", "DISPATCHED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Only a PLANNED or DISPATCHED order can be cancelled")
    order["status"] = "CANCELLED"
    helpers.touch(order)
    _release_bookings(order)
    job = db.jobs.items.get(order["job_id"])
    if job is not None and job["lifecycle_status"] == "SCHEDULED":
        job["lifecycle_status"] = "SOLD"
        job["install_order_id"] = None
        helpers.touch(job)
    return object_response(serialize(order), status=200)
