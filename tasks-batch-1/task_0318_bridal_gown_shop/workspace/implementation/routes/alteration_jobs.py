"""AlterationJob endpoints — cyclic fitting loop (PRD §3.5)."""
from flask import Blueprint, request

import db
import common
import errors
import services
import calculations
from middleware import require_roles
from response import success

ALL_ROLES = ("ShopManager", "BridalConsultant", "Seamstress", "FinanceClerk")

bp = Blueprint("alteration_jobs", __name__)


def _release_held_bookings_in_room(room_id):
    """Release HELD bookings on the given fitting room (job complete/cancel)."""
    if room_id is None:
        return
    for b in db.fitting_room_bookings.values():
        if b["fitting_room_id"] == room_id and b["status"] == "HELD":
            b["status"] = "RELEASED"
            db.touch(b)


@bp.route("/alteration-jobs", methods=["POST"])
@require_roles("Seamstress", "ShopManager")
def create_job():
    body = common.get_body()
    gown_order_id = common.as_str(body, "gown_order_id")
    services.get_order(gown_order_id)  # FK existence
    estimated_labor_minutes = common.as_int(body, "estimated_labor_minutes", minimum=0)
    fitting_room_id = body.get("fitting_room_id")
    if fitting_room_id is not None:
        services.get_fitting_room(fitting_room_id)  # FK existence
    obj = {
        "id": db.new_id(),
        "gown_order_id": gown_order_id,
        "fitting_room_id": fitting_room_id,
        "estimated_labor_minutes": estimated_labor_minutes,
        "actual_labor_minutes": 0,
        "refitting_count": 0,
        "estimated_cost_cents": calculations.estimated_alteration_cost_cents(estimated_labor_minutes),
        "final_cost_cents": None,
        "status": "QUEUED",
    }
    db.stamp_create(obj)
    db.alteration_jobs[obj["id"]] = obj
    return success(common.serialize(obj), status=201)


@bp.route("/alteration-jobs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_jobs():
    limit, offset = common.paginate(request.args)
    rows = list(db.alteration_jobs.values())
    gown_order_id = request.args.get("gown_order_id")
    fitting_room_id = request.args.get("fitting_room_id")
    if gown_order_id is not None:
        rows = [j for j in rows if j["gown_order_id"] == gown_order_id]
    if fitting_room_id is not None:
        rows = [j for j in rows if j.get("fitting_room_id") == fitting_room_id]
    window, meta = common.page_slice(rows, limit, offset)
    return success([common.serialize(o) for o in window], pagination=meta)


@bp.route("/alteration-jobs/<jid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_job(jid):
    obj = services.get_job(jid)
    return success(common.serialize(obj))


@bp.route("/alteration-jobs/<jid>/start-fitting", methods=["POST"])
@require_roles("Seamstress")
def start_fitting(jid):
    obj = services.get_job(jid)
    if obj["status"] != "QUEUED":
        errors.raise_error(errors.ERR_JOB_NOT_QUEUED, "Job is not QUEUED")
    order = db.gown_orders.get(obj["gown_order_id"])
    if order is None or order["fulfillment_status"] != "RECEIVED":
        errors.raise_error(errors.ERR_ORDER_NOT_RECEIVED, "Linked order is not RECEIVED")
    obj["status"] = "FITTING"
    db.touch(obj)
    return success(common.serialize(obj))


@bp.route("/alteration-jobs/<jid>/request-adjustment", methods=["POST"])
@require_roles("Seamstress")
def request_adjustment(jid):
    obj = services.get_job(jid)
    if obj["status"] != "FITTING":
        errors.raise_error(errors.ERR_JOB_NOT_FITTING, "Job is not FITTING")
    obj["status"] = "ADJUSTING"
    obj["refitting_count"] += 1
    db.touch(obj)
    return success(common.serialize(obj))


@bp.route("/alteration-jobs/<jid>/log-labor", methods=["POST"])
@require_roles("Seamstress")
def log_labor(jid):
    obj = services.get_job(jid)
    body = common.get_body()
    minutes = common.as_int(body, "minutes", minimum=0)
    if obj["status"] != "ADJUSTING":
        errors.raise_error(errors.ERR_JOB_NOT_ADJUSTING, "Job is not ADJUSTING")
    obj["actual_labor_minutes"] += minutes
    obj["status"] = "FITTING"
    db.touch(obj)
    return success(common.serialize(obj))


@bp.route("/alteration-jobs/<jid>/complete", methods=["POST"])
@require_roles("Seamstress")
def complete_job(jid):
    obj = services.get_job(jid)
    if obj["status"] != "FITTING":
        errors.raise_error(errors.ERR_JOB_NOT_FITTING, "Job is not FITTING")
    obj["status"] = "COMPLETED"
    obj["final_cost_cents"] = calculations.final_alteration_cost_cents(
        obj["actual_labor_minutes"], obj["refitting_count"]
    )
    db.touch(obj)
    _release_held_bookings_in_room(obj.get("fitting_room_id"))
    return success(common.serialize(obj))


@bp.route("/alteration-jobs/<jid>/cancel", methods=["POST"])
@require_roles("Seamstress", "ShopManager")
def cancel_job(jid):
    obj = services.get_job(jid)
    if obj["status"] in ("COMPLETED", "CANCELLED"):
        errors.raise_error(errors.ERR_JOB_NOT_CANCELLABLE, "Job is not cancellable")
    obj["status"] = "CANCELLED"
    db.touch(obj)
    _release_held_bookings_in_room(obj.get("fitting_room_id"))
    return success(common.serialize(obj))
