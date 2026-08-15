"""Job endpoints: intake, confirm, cancel with the full down-cascade."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_FORBIDDEN_OWNERSHIP, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import authenticate, require_role, require_ownership, get_or_404, ALL_ROLES
from response import success, success_list
from services import cascade, serializers
from services.derive import job_posture
from util import as_bool, as_dt, as_int, as_str, body, paginate

bp = Blueprint("jobs", __name__)


def _scoped_jobs(role, uid, records):
    if role == "CustomerContact":
        records = [j for j in records if j["customer_id"] == uid]
    return records


@bp.route("/plant/jobs", methods=["POST"])
def create_job():
    uid, role = authenticate()
    require_role(role, ["CustomerContact", "PlantManager"])
    data = body()
    # Priority 3 (ownership) precedes priority 4 (existence): a CustomerContact
    # may only create jobs for its own customer account.
    if role == "CustomerContact" and data.get("customer_id") != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "customer contact may only create jobs for its own account")
    customer = None
    if data.get("customer_id") is not None:
        customer = get_or_404(db.customers, data["customer_id"], "customer account")
    # Schema.
    customer_id = as_str(data.get("customer_id"), "customer_id", required=True)
    if customer is None:
        customer = db.customers[customer_id]
    job_name = as_str(data.get("job_name"), "job_name", required=True)
    jobsite_address = as_str(data.get("jobsite_address"), "jobsite_address", required=True)
    jobsite_state = as_str(data.get("jobsite_state"), "jobsite_state", required=True)
    window_start = as_dt(data.get("delivery_window_start"), "delivery_window_start", required=True)
    window_end = as_dt(data.get("delivery_window_end"), "delivery_window_end", required=True)
    contracted = as_int(data.get("contracted_value_cents"), "contracted_value_cents", required=True)
    crane_required = as_bool(data.get("crane_required_at_jobsite"), "crane_required_at_jobsite", default=False)
    if window_end < window_start:
        raise ApiError(ERR_INVALID_REQUEST, 400, "delivery_window_end must be on or after delivery_window_start")
    rec = db.new_record({
        "customer_id": customer["id"],
        "job_name": job_name,
        "jobsite_address": jobsite_address,
        "jobsite_state": jobsite_state,
        "delivery_window_start": window_start,
        "delivery_window_end": window_end,
        "crane_required_at_jobsite": crane_required,
        "contracted_value_cents": contracted,
        # invoiced_cents is initially 0 (PRD section 3.2) and recomputed from
        # contracted value plus CLOSED loads' final freight at each load close.
        "invoiced_cents": 0,
        "status": "QUOTED",
    })
    db.jobs[rec["id"]] = rec
    return success(serializers.job(rec), status=201)


@bp.route("/plant/jobs/<jid>", methods=["GET"])
def get_job(jid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.jobs, jid, "job")
    require_ownership(role, uid, rec["customer_id"])
    return success(serializers.job(rec))


@bp.route("/plant/jobs", methods=["GET"])
def list_jobs():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    records = _scoped_jobs(role, uid, list(db.jobs.values()))
    raw = request.args.get("customer_id")
    if raw is not None:
        records = [j for j in records if j["customer_id"] == raw]
    raw = request.args.get("status")
    if raw is not None:
        records = [j for j in records if j["status"] == raw]
    raw = request.args.get("posture")
    if raw is not None:
        records = [j for j in records if job_posture(j) == raw]
    page, meta = paginate(records)
    return success_list([serializers.job(j) for j in page], meta)


@bp.route("/plant/jobs/<jid>/confirm", methods=["POST"])
def confirm_job(jid):
    _uid, role = authenticate()
    require_role(role, ["PlantManager"])
    rec = get_or_404(db.jobs, jid, "job")
    if rec["status"] != "QUOTED":
        raise ApiError(ERR_INVALID_STATE, 409, "only a QUOTED job can be confirmed")
    rec["status"] = "CONFIRMED"
    db.touch(rec)
    return success(serializers.job(rec))


@bp.route("/plant/jobs/<jid>/cancel", methods=["POST"])
def cancel_job(jid):
    _uid, role = authenticate()
    require_role(role, ["PlantManager"])
    rec = get_or_404(db.jobs, jid, "job")
    if rec["status"] not in ("QUOTED", "CONFIRMED", "IN_PRODUCTION"):
        raise ApiError(ERR_INVALID_STATE, 409, f"job in status {rec['status']} cannot be cancelled")
    for load in db.delivery_loads.values():
        if load["job_id"] == jid and load["status"] in (
            "DISPATCHED", "DELIVERED", "RETURNED", "RESCHEDULED", "CLAIM_HOLD"
        ):
            raise ApiError(ERR_INVALID_STATE, 409, "freight already on the road must be settled, not cancelled")
    cascade.job_cancel_cascade(rec)
    rec["status"] = "CANCELLED"
    db.touch(rec)
    return success(serializers.job(rec))
