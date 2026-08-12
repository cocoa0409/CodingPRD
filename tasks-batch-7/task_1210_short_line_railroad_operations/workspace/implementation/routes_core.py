"""Logical clock, Customers, IndustrySidings."""

from flask import Blueprint, request

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import (ApiError, ERR_INVALID_REQUEST, not_found, invalid_state)
from util import (json_body, req_str, opt_str, req_int, opt_int, req_dt,
                  opt_enum, paginate)
from domain import (new_record, touch, run_clock_sweeps, customer_view,
                    siding_view, CREDIT_STATUSES)

bp = Blueprint("core", __name__)

ALL_ROLES = None  # any authenticated role


# ---------------------------------------------------------------------------
# POST /rail/_clock/set_current_utc
# ---------------------------------------------------------------------------

@bp.post("/rail/_clock/set_current_utc")
def set_clock():
    uid, role = authenticate()
    body = json_body(required=True)
    to_dt = req_dt(body, "to_iso8601")
    require_role(role, ["SystemAdmin"])
    store.now = to_dt
    swept_segments, swept_crew, swept_sidings = run_clock_sweeps()
    from util import iso
    return success_object({
        "current_utc": iso(store.now),
        "swept_segments": swept_segments,
        "swept_crew": swept_crew,
        "swept_sidings": swept_sidings,
    })


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@bp.post("/rail/customers")
def create_customer():
    uid, role = authenticate()
    body = json_body(required=True)
    name = req_str(body, "name")
    billing_email = req_str(body, "billing_email")
    free_days = opt_int(body, "demurrage_free_days")
    require_role(role, ["SystemAdmin"])
    rec = new_record({
        "name": name,
        "billing_email": billing_email,
        "demurrage_free_days": 2 if free_days is None else free_days,
        "credit_status": "GOOD",
    })
    store.customers[rec["id"]] = rec
    return success_object(customer_view(rec), status=201)


@bp.get("/rail/customers")
def list_customers():
    uid, role = authenticate()
    credit_status = request.args.get("credit_status")
    records = list(store.customers.values())
    if credit_status is not None:
        records = [c for c in records if c["credit_status"] == credit_status]
    limit, offset, total, page = paginate(records)
    return success_list([customer_view(c) for c in page], limit, offset, total)


@bp.get("/rail/customers/<cid>")
def get_customer(cid):
    uid, role = authenticate()
    rec = store.customers.get(cid)
    if rec is None:
        raise not_found("customer not found")
    return success_object(customer_view(rec))


@bp.patch("/rail/customers/<cid>")
def patch_customer(cid):
    uid, role = authenticate()
    body = json_body(required=True)
    credit_status = opt_enum(body, "credit_status", CREDIT_STATUSES)
    free_days = opt_int(body, "demurrage_free_days")
    require_role(role, ["SystemAdmin"])
    rec = store.customers.get(cid)
    if rec is None:
        raise not_found("customer not found")
    if credit_status is not None:
        rec["credit_status"] = credit_status
    if free_days is not None:
        rec["demurrage_free_days"] = free_days
    touch(rec)
    return success_object(customer_view(rec))


# ---------------------------------------------------------------------------
# Industry sidings
# ---------------------------------------------------------------------------

@bp.post("/rail/industry-sidings")
def create_siding():
    uid, role = authenticate()
    body = json_body(required=True)
    customer_id = req_str(body, "customer_id")
    name = req_str(body, "name")
    capacity_cars = req_int(body, "capacity_cars")
    segment_id = req_str(body, "serving_track_segment_id")
    expires = req_dt(body, "agreement_expires_on")
    require_role(role, ["SystemAdmin"])
    if customer_id not in store.customers:
        raise not_found("customer not found")
    if segment_id not in store.track_segments:
        raise not_found("track segment not found")
    rec = new_record({
        "customer_id": customer_id,
        "name": name,
        "capacity_cars": capacity_cars,
        "serving_track_segment_id": segment_id,
        "agreement_expires_on": expires,
        "maintenance_agreement_status": "ACTIVE",
    })
    store.sidings[rec["id"]] = rec
    return success_object(siding_view(rec), status=201)


@bp.get("/rail/industry-sidings")
def list_sidings():
    uid, role = authenticate()
    f_customer = request.args.get("customer_id")
    f_segment = request.args.get("serving_track_segment_id")
    f_status = request.args.get("maintenance_agreement_status")
    records = list(store.sidings.values())
    if f_customer is not None:
        records = [s for s in records if s["customer_id"] == f_customer]
    if f_segment is not None:
        records = [s for s in records if s["serving_track_segment_id"] == f_segment]
    if f_status is not None:
        records = [s for s in records if s["maintenance_agreement_status"] == f_status]
    limit, offset, total, page = paginate(records)
    return success_list([siding_view(s) for s in page], limit, offset, total)


@bp.get("/rail/industry-sidings/<sid>")
def get_siding(sid):
    uid, role = authenticate()
    rec = store.sidings.get(sid)
    if rec is None:
        raise not_found("siding not found")
    return success_object(siding_view(rec))


@bp.post("/rail/industry-sidings/<sid>/renew-agreement")
def renew_siding(sid):
    uid, role = authenticate()
    body = json_body(required=True)
    new_expires = req_dt(body, "new_expires_on")
    require_role(role, ["SystemAdmin"])
    rec = store.sidings.get(sid)
    if rec is None:
        raise not_found("siding not found")
    if rec["maintenance_agreement_status"] not in ("EXPIRED", "SUSPENDED"):
        raise invalid_state("agreement cannot be renewed from status %s"
                            % rec["maintenance_agreement_status"])
    if not (new_expires > store.now):
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "new_expires_on must be strictly later than the current clock")
    rec["agreement_expires_on"] = new_expires
    rec["maintenance_agreement_status"] = "ACTIVE"
    touch(rec)
    return success_object(siding_view(rec))


@bp.post("/rail/industry-sidings/<sid>/suspend")
def suspend_siding(sid):
    uid, role = authenticate()
    json_body()
    require_role(role, ["SystemAdmin"])
    rec = store.sidings.get(sid)
    if rec is None:
        raise not_found("siding not found")
    if rec["maintenance_agreement_status"] != "ACTIVE":
        raise invalid_state("only an ACTIVE agreement can be suspended")
    rec["maintenance_agreement_status"] = "SUSPENDED"
    touch(rec)
    return success_object(siding_view(rec))
