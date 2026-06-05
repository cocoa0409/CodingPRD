"""MoveJob routes (PRD §3.2, §3.5, §3.9, §3.11).

Parallel state dimensions: job_status x payment_status (PRD §2.9).
Ledger in integer cents (PRD §2.7). MoveJob.version only bumps on estimate
generation and SIT waive (PRD §2.4); payments/acceptance/etc. refresh
updated_at only.
"""
from flask import Blueprint

import db
from errors import err
from middleware import authenticate, require_roles
from response import object_response, array_response
from serialize import public, public_list
from services import common

bp = Blueprint("move_jobs", __name__)

SERVICE_TYPES = {"LOCAL", "LONG_HAUL"}


@bp.route("/move-jobs", methods=["POST"])
def create_move_job():
    user_id, role = authenticate()
    require_roles(role, {"PlatformAdmin", "Customer"})
    body = common.get_json_body()
    common.require_fields(body, [
        "customer_id", "service_type", "origin_zip",
        "destination_zip", "distance_miles", "requested_move_date",
    ])

    # Existence: body FK customer_id (PRD §2.5).
    common.lookup_fk(db.customers, body["customer_id"])

    # Field validity (priority 9).
    common.require_enum(body, "service_type", SERVICE_TYPES)
    common.require_int_field(body, "distance_miles", minimum=0)

    stair_flights = body.get("stair_flights", 0)
    if stair_flights is None:
        stair_flights = 0
    long_carry_units = body.get("long_carry_units", 0)
    if long_carry_units is None:
        long_carry_units = 0
    if not common.is_int(stair_flights) or stair_flights < 0:
        raise err("ERR_INVALID_FIELD", "stair_flights must be a non-negative integer.")
    if not common.is_int(long_carry_units) or long_carry_units < 0:
        raise err("ERR_INVALID_FIELD", "long_carry_units must be a non-negative integer.")

    record = db.new_common({
        "customer_id": body["customer_id"],
        "service_type": body["service_type"],
        "origin_zip": body["origin_zip"],
        "destination_zip": body["destination_zip"],
        "distance_miles": body["distance_miles"],
        "requested_move_date": body["requested_move_date"],
        "stair_flights": stair_flights,
        "long_carry_units": long_carry_units,
        "job_status": "QUOTING",
        "payment_status": "UNPAID",
        "accepted_estimate_id": None,
        "final_charge_cents": 0,
        "gross_charges_cents": 0,
        "balance_due_cents": 0,
        "paid_cents": 0,
        "waived_cents": 0,
        "refunded_cents": 0,
    })
    db.move_jobs[record["id"]] = record
    return object_response(public(record), 201)


@bp.route("/move-jobs/<jid>", methods=["GET"])
def get_move_job(jid):
    user_id, role = authenticate()
    require_roles(role, {"PlatformAdmin", "Customer", "Estimator", "Dispatcher", "ClaimsAdjuster"})
    record = common.lookup(db.move_jobs, jid)
    return object_response(public(record), 200)


@bp.route("/move-jobs", methods=["GET"])
def list_move_jobs():
    user_id, role = authenticate()
    require_roles(role, {"PlatformAdmin", "Estimator", "Dispatcher", "ClaimsAdjuster"})
    limit, offset = common.parse_pagination()
    from flask import request
    customer_id = request.args.get("customer_id")
    job_status = request.args.get("job_status")
    records = list(db.move_jobs.values())
    if customer_id is not None:
        records = [r for r in records if r["customer_id"] == customer_id]
    if job_status is not None:
        records = [r for r in records if r["job_status"] == job_status]
    page, total = common.paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total, 200)


# ---------------------------------------------------------------- Payments
@bp.route("/move-jobs/<jid>/payments", methods=["POST"])
def apply_payment(jid):
    user_id, role = authenticate()
    require_roles(role, {"Customer"})
    job = common.lookup(db.move_jobs, jid)

    # Resource ownership (priority 4): acting Customer must own the job.
    if user_id != job["customer_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "You do not own this move job.")

    body = common.get_json_body()
    common.require_fields(body, ["kind", "amount_cents"])
    common.require_enum(body, "kind", {"DEPOSIT", "BALANCE"})
    common.require_int_field(body, "amount_cents", minimum=0)

    kind = body["kind"]
    amount = body["amount_cents"]

    if kind == "DEPOSIT":
        # State guard (priority 22): deposit requires job BOOKED.
        if job["job_status"] != "BOOKED":
            raise err("ERR_DEPOSIT_BEFORE_BOOKED", "A deposit may only be taken once the job is BOOKED.")
        if job["payment_status"] != "UNPAID":
            raise err("ERR_INVALID_STATE", "Deposit is only valid from UNPAID.")
        job["paid_cents"] += amount
        job["payment_status"] = "DEPOSIT_PAID"
        common.recompute_balance(job)
        db.touch_updated_only(job)
        return object_response(public(job), 201)

    # kind == BALANCE
    # Balance requires DELIVERED job (PRD §3.5) and DEPOSIT_PAID payment status.
    if job["job_status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "A balance payment may only be taken once the job is DELIVERED.")
    if job["payment_status"] != "DEPOSIT_PAID":
        raise err("ERR_INVALID_STATE", "Balance payment requires payment_status DEPOSIT_PAID.")
    # Amount must equal balance exactly (priority 16).
    if amount != job["balance_due_cents"]:
        raise err("ERR_PAYMENT_AMOUNT_MISMATCH", "Balance payment must equal the outstanding balance exactly.")
    job["paid_cents"] += amount
    job["payment_status"] = "PAID_IN_FULL"
    common.recompute_balance(job)
    db.touch_updated_only(job)
    return object_response(public(job), 201)


# ---------------------------------------------------------------- Close
@bp.route("/move-jobs/<jid>/close", methods=["POST"])
def close_move_job(jid):
    user_id, role = authenticate()
    require_roles(role, {"PlatformAdmin"})
    job = common.lookup(db.move_jobs, jid)

    # State (priority 6): close defined only from DELIVERED.
    if job["job_status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "A job may only be closed from DELIVERED.")
    # Dependent-state block (priority 7): paid in full, no open claim/storage.
    if job["payment_status"] != "PAID_IN_FULL":
        raise err("ERR_DEPENDENT_STATE_BLOCK", "Job must be PAID_IN_FULL to close.")
    for c in db.damage_claims.values():
        if c["move_job_id"] == jid and c["status"] == "UNDER_REVIEW":
            raise err("ERR_DEPENDENT_STATE_BLOCK", "Job has a claim still under review.")
    for lot in db.storage_lots.values():
        if lot["move_job_id"] == jid and lot["status"] == "IN_STORAGE":
            raise err("ERR_DEPENDENT_STATE_BLOCK", "Job has a storage lot still in storage.")

    job["job_status"] = "CLOSED"
    db.touch_updated_only(job)
    return object_response(public(job), 200)


# ---------------------------------------------------------------- Cancel
@bp.route("/move-jobs/<jid>/cancel", methods=["POST"])
def cancel_move_job(jid):
    user_id, role = authenticate()
    require_roles(role, {"Customer"})
    job = common.lookup(db.move_jobs, jid)

    # Resource ownership (priority 4).
    if user_id != job["customer_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "You do not own this move job.")

    # State (priority 6): cancel defined only from QUOTING/BOOKED.
    if job["job_status"] not in {"QUOTING", "BOOKED"}:
        raise err("ERR_INVALID_STATE", "Only QUOTING or BOOKED jobs may be cancelled.")

    # Cancel-in-transit guard (priority 19): blocked if any EN_ROUTE dispatch.
    for d in db.dispatches.values():
        if d["move_job_id"] == jid and d["status"] == "EN_ROUTE":
            raise err("ERR_CANCEL_IN_TRANSIT", "Cannot cancel a job with goods in transit.")

    job["job_status"] = "CANCELLED"

    # Cascade: every SCHEDULED dispatch -> CANCELLED (frees windows by status).
    for d in db.dispatches.values():
        if d["move_job_id"] == jid and d["status"] == "SCHEDULED":
            d["status"] = "CANCELLED"
            db.touch(d)

    # Refund any paid amount.
    if job["paid_cents"] > 0:
        job["refunded_cents"] = job["paid_cents"]
        job["payment_status"] = "REFUNDED"
    common.recompute_balance(job)
    db.touch_updated_only(job)
    return object_response(public(job), 200)
