"""Config + clock routes: pricing policies, customers, crews, trucks, test clock.

Also hosts the parent-scoped child list endpoints whose parent is a config entity:
customer haul-jobs/invoices, crew dispatches, truck dispatches.
"""
from flask import Blueprint, request
import errors
from errors import err
from db import db
from middleware import authenticate, require_role
from response import success, success_list
import helpers as H
import models
import clock
from util import parse_iso

bp = Blueprint("config", __name__)


# --------------------------------------------------------------------------
# PricingPolicy
# --------------------------------------------------------------------------

def _validate_tier_breaks(tier_breaks):
    if not isinstance(tier_breaks, list) or len(tier_breaks) == 0:
        err(errors.ERR_INVALID_REQUEST, "tier_breaks must be a non-empty array")
    prev_upper = 0.0
    for i, band in enumerate(tier_breaks):
        if not isinstance(band, dict):
            err(errors.ERR_INVALID_REQUEST, "tier_breaks entries must be objects")
        if "upper_fraction" not in band or "marginal_multiplier" not in band:
            err(errors.ERR_INVALID_REQUEST, "tier_breaks entries need upper_fraction and marginal_multiplier")
        uf = band["upper_fraction"]
        mm = band["marginal_multiplier"]
        if isinstance(uf, bool) or not isinstance(uf, (int, float)):
            err(errors.ERR_INVALID_REQUEST, "upper_fraction must be a number")
        if isinstance(mm, bool) or not isinstance(mm, (int, float)):
            err(errors.ERR_INVALID_REQUEST, "marginal_multiplier must be a number")
        if uf <= prev_upper:
            err(errors.ERR_INVALID_REQUEST, "tier_breaks upper_fraction must be strictly increasing")
        prev_upper = uf
    if abs(prev_upper - 1.0) > 1e-9:
        err(errors.ERR_INVALID_REQUEST, "tier_breaks must end at upper_fraction 1.0")


def _validate_nonneg_int(body, field):
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        err(errors.ERR_INVALID_REQUEST, "%s must be an integer" % field)
    if v < 0:
        err(errors.ERR_INVALID_REQUEST, "%s must be >= 0" % field)
    return v


def _opt_nonneg_number(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err(errors.ERR_INVALID_REQUEST, "%s must be a number" % field)
    if v < 0:
        err(errors.ERR_INVALID_REQUEST, "%s must be >= 0" % field)
    return v


@bp.route("/pricing-policies", methods=["POST"])
def create_pricing_policy():
    auth = authenticate()
    require_role(auth, {"PlatformAdmin"})
    body = H.get_json_body()
    required = [
        "name", "full_truck_cents", "tier_breaks", "mattress_surcharge_cents",
        "appliance_surcharge_cents", "freon_surcharge_cents",
        "dump_fee_per_ton_cents", "full_truck_dump_cents",
        "recycle_fee_per_ton_cents", "diversion_credit_per_ton_cents",
    ]
    H.require_fields(body, required)
    name = H.as_str(body["name"], "name")
    full_truck_cents = _validate_nonneg_int(body, "full_truck_cents")
    _validate_tier_breaks(body["tier_breaks"])
    for f in ["mattress_surcharge_cents", "appliance_surcharge_cents",
              "freon_surcharge_cents", "dump_fee_per_ton_cents",
              "full_truck_dump_cents", "recycle_fee_per_ton_cents",
              "diversion_credit_per_ton_cents"]:
        _validate_nonneg_int(body, f)

    min_billable_fraction = _opt_nonneg_number(body, "min_billable_fraction", 0.125)
    fraction_step = _opt_nonneg_number(body, "fraction_step", 0.125)
    same_day_surcharge_pct = _opt_nonneg_number(body, "same_day_surcharge_pct", 0.20)
    tax_pct = _opt_nonneg_number(body, "tax_pct", 0.08)
    cancel_pct_scheduled = _opt_nonneg_number(body, "cancel_pct_scheduled", 0.25)
    cancel_pct_dispatched = _opt_nonneg_number(body, "cancel_pct_dispatched", 0.50)

    # First policy created is ACTIVE; activating retires the prior ACTIVE.
    policy = models.make_pricing_policy(
        name=name, full_truck_cents=full_truck_cents, tier_breaks=body["tier_breaks"],
        mattress_surcharge_cents=body["mattress_surcharge_cents"],
        appliance_surcharge_cents=body["appliance_surcharge_cents"],
        freon_surcharge_cents=body["freon_surcharge_cents"],
        dump_fee_per_ton_cents=body["dump_fee_per_ton_cents"],
        full_truck_dump_cents=body["full_truck_dump_cents"],
        recycle_fee_per_ton_cents=body["recycle_fee_per_ton_cents"],
        diversion_credit_per_ton_cents=body["diversion_credit_per_ton_cents"],
        min_billable_fraction=min_billable_fraction, fraction_step=fraction_step,
        same_day_surcharge_pct=same_day_surcharge_pct, tax_pct=tax_pct,
        cancel_pct_scheduled=cancel_pct_scheduled,
        cancel_pct_dispatched=cancel_pct_dispatched, status="ACTIVE",
    )
    for p in db.pricing_policies.values():
        if p["status"] == "ACTIVE":
            p["status"] = "RETIRED"
            models.touch(p)
    db.pricing_policies[policy["id"]] = policy
    return success(models.ser_pricing_policy(policy), 201)


@bp.route("/pricing-policies/<pid>", methods=["GET"])
def get_pricing_policy(pid):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher", "Billing"})
    policy = db.pricing_policies.get(pid)
    if policy is None:
        err(errors.ERR_POLICY_NOT_FOUND, "PricingPolicy not found")
    return success(models.ser_pricing_policy(policy), 200)


# --------------------------------------------------------------------------
# Customer
# --------------------------------------------------------------------------

@bp.route("/customers", methods=["POST"])
def create_customer():
    auth = authenticate()
    require_role(auth, {"PlatformAdmin"})
    body = H.get_json_body()
    H.require_fields(body, ["email", "full_name"])
    email = H.as_str(body["email"], "email")
    full_name = H.as_str(body["full_name"], "full_name")
    credit_limit_cents = 50000
    if "credit_limit_cents" in body and body["credit_limit_cents"] is not None:
        credit_limit_cents = _validate_nonneg_int(body, "credit_limit_cents")
    # Email must be unique among customers.
    for c in db.customers.values():
        if c["email"] == email:
            err(errors.ERR_INVALID_REQUEST, "email must be unique among customers")
    customer = models.make_customer(email, full_name, credit_limit_cents)
    db.customers[customer["id"]] = customer
    return success(models.ser_customer(customer), 201)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Billing", "Dispatcher", "Customer"})
    customer = db.customers.get(cid)
    if customer is None:
        err(errors.ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    if auth.role == "Customer" and auth.user_id != cid:
        err(errors.ERR_FORBIDDEN_ROLE, "Customer may only read its own record")
    return success(models.ser_customer(customer), 200)


@bp.route("/customers/<cid>/haul-jobs", methods=["GET"])
def list_customer_jobs(cid):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Billing", "Dispatcher", "Customer"})
    customer = db.customers.get(cid)
    if customer is None:
        err(errors.ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    if auth.role == "Customer" and auth.user_id != cid:
        err(errors.ERR_FORBIDDEN_ROLE, "Customer may only read its own jobs")
    limit, offset = H.pagination_params()
    status_filter = request.args.get("status")
    items = [j for j in db.haul_jobs.values() if j["customer_id"] == cid]
    if status_filter is not None:
        items = [j for j in items if j["status"] == status_filter]
    items = H.sort_by_creation(items)
    page, total = H.paginate(items, limit, offset)
    return success_list([models.ser_haul_job(j) for j in page], limit, offset, total)


@bp.route("/customers/<cid>/invoices", methods=["GET"])
def list_customer_invoices(cid):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Billing", "Customer"})
    customer = db.customers.get(cid)
    if customer is None:
        err(errors.ERR_CUSTOMER_NOT_FOUND, "Customer not found")
    if auth.role == "Customer" and auth.user_id != cid:
        err(errors.ERR_FORBIDDEN_ROLE, "Customer may only read its own invoices")
    limit, offset = H.pagination_params()
    bs_filter = request.args.get("billing_status")
    items = [i for i in db.invoices.values() if i["customer_id"] == cid]
    if bs_filter is not None:
        items = [i for i in items if i["billing_status"] == bs_filter]
    items = H.sort_by_creation(items)
    page, total = H.paginate(items, limit, offset)
    return success_list([models.ser_invoice(i) for i in page], limit, offset, total)


# --------------------------------------------------------------------------
# Crew
# --------------------------------------------------------------------------

@bp.route("/crews", methods=["POST"])
def create_crew():
    auth = authenticate()
    require_role(auth, {"PlatformAdmin"})
    body = H.get_json_body()
    H.require_fields(body, ["name", "shift_start_utc", "shift_end_utc"])
    name = H.as_str(body["name"], "name")
    shift_start = H.as_str(body["shift_start_utc"], "shift_start_utc")
    shift_end = H.as_str(body["shift_end_utc"], "shift_end_utc")
    if parse_iso(shift_start) is None:
        err(errors.ERR_INVALID_REQUEST, "shift_start_utc must be a valid ISO8601 datetime")
    if parse_iso(shift_end) is None:
        err(errors.ERR_INVALID_REQUEST, "shift_end_utc must be a valid ISO8601 datetime")
    buffer_minutes = 30
    if "buffer_minutes" in body and body["buffer_minutes"] is not None:
        buffer_minutes = _validate_nonneg_int(body, "buffer_minutes")
    hazmat_certified = False
    if "hazmat_certified" in body and body["hazmat_certified"] is not None:
        hazmat_certified = H.as_bool(body["hazmat_certified"], "hazmat_certified")
    crew = models.make_crew(name, shift_start, shift_end, buffer_minutes, hazmat_certified)
    db.crews[crew["id"]] = crew
    return success(models.ser_crew(crew), 201)


@bp.route("/crews/<cid>", methods=["GET"])
def get_crew(cid):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher", "CrewLead"})
    crew = db.crews.get(cid)
    if crew is None:
        err(errors.ERR_CREW_NOT_FOUND, "Crew not found")
    if auth.role == "CrewLead" and auth.user_id != cid:
        err(errors.ERR_FORBIDDEN_ROLE, "CrewLead may only read its own crew")
    return success(models.ser_crew(crew), 200)


@bp.route("/crews/<cid>/dispatches", methods=["GET"])
def list_crew_dispatches(cid):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher", "CrewLead"})
    crew = db.crews.get(cid)
    if crew is None:
        err(errors.ERR_CREW_NOT_FOUND, "Crew not found")
    if auth.role == "CrewLead" and auth.user_id != cid:
        err(errors.ERR_FORBIDDEN_ROLE, "CrewLead may only read its own dispatches")
    limit, offset = H.pagination_params()
    ds_filter = request.args.get("dispatch_status")
    items = [d for d in db.dispatches.values() if d["crew_id"] == cid]
    if ds_filter is not None:
        items = [d for d in items if d["dispatch_status"] == ds_filter]
    items = H.sort_by_creation(items)
    page, total = H.paginate(items, limit, offset)
    return success_list([models.ser_dispatch(d) for d in page], limit, offset, total)


@bp.route("/crews/<cid>/status", methods=["POST"])
def set_crew_status(cid):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin"})
    crew = db.crews.get(cid)
    if crew is None:
        err(errors.ERR_CREW_NOT_FOUND, "Crew not found")
    body = H.get_json_body()
    H.require_fields(body, ["status"])
    status = H.as_enum(body["status"], "status", {"ON_DUTY", "OFF_DUTY"})
    crew["status"] = status
    models.touch(crew)  # status change is a mutation; bumps version
    return success(models.ser_crew(crew), 200)


# --------------------------------------------------------------------------
# Truck
# --------------------------------------------------------------------------

@bp.route("/trucks", methods=["POST"])
def create_truck():
    auth = authenticate()
    require_role(auth, {"PlatformAdmin"})
    body = H.get_json_body()
    H.require_fields(body, ["name"])
    name = H.as_str(body["name"], "name")
    truck = models.make_truck(name)
    db.trucks[truck["id"]] = truck
    return success(models.ser_truck(truck), 201)


@bp.route("/trucks/<tid>", methods=["GET"])
def get_truck(tid):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher"})
    truck = db.trucks.get(tid)
    if truck is None:
        err(errors.ERR_TRUCK_NOT_FOUND, "Truck not found")
    return success(models.ser_truck(truck), 200)


@bp.route("/trucks/<tid>/dispatches", methods=["GET"])
def list_truck_dispatches(tid):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Dispatcher"})
    truck = db.trucks.get(tid)
    if truck is None:
        err(errors.ERR_TRUCK_NOT_FOUND, "Truck not found")
    limit, offset = H.pagination_params()
    ds_filter = request.args.get("dispatch_status")
    items = [d for d in db.dispatches.values() if d["truck_id"] == tid]
    if ds_filter is not None:
        items = [d for d in items if d["dispatch_status"] == ds_filter]
    items = H.sort_by_creation(items)
    page, total = H.paginate(items, limit, offset)
    return success_list([models.ser_dispatch(d) for d in page], limit, offset, total)


@bp.route("/trucks/<tid>/status", methods=["POST"])
def set_truck_status(tid):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin"})
    truck = db.trucks.get(tid)
    if truck is None:
        err(errors.ERR_TRUCK_NOT_FOUND, "Truck not found")
    body = H.get_json_body()
    H.require_fields(body, ["status"])
    status = H.as_enum(body["status"], "status", {"IN_SERVICE", "OUT_OF_SERVICE"})
    truck["status"] = status
    models.touch(truck)
    return success(models.ser_truck(truck), 200)


# --------------------------------------------------------------------------
# Test clock
# --------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth = authenticate()
    require_role(auth, {"PlatformAdmin"})
    body = H.get_json_body()
    H.require_fields(body, ["to_iso8601"])
    iso = H.as_str(body["to_iso8601"], "to_iso8601")
    dt = parse_iso(iso)
    if dt is None:
        err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO8601 datetime")
    clock.set_current_utc(dt)
    return success({}, 200)
