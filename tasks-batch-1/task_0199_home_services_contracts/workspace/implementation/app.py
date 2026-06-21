"""Home Services Contracts API — Flask entry point.

In-memory only. Empty store on every boot. No seeding.
All resources mounted under /home-services (PRD §1).

Validation precedence (PRD §2.9), evaluated per request handler:
  1 ERR_UNAUTHENTICATED  2 ERR_UNAUTHORIZED  3 ERR_NOT_RESOURCE_OWNER
  4 ERR_NOT_FOUND        5 ERR_INVALID_REQUEST  then domain business rules.
"""
import os
from datetime import timedelta

from flask import Flask, request

import db
import lookups as L
import models
import services as S
from common import (
    get_body, pagination, paginate, sort_by_created, parse_iso, parse_dt,
    require, req_int, opt_int, req_str, opt_str, req_enum, opt_enum,
    req_bool, opt_bool, req_number,
)
from errors import ApiError, err
from middleware import authenticate, authorize
from response import ok, created, listing, error

app = Flask(__name__)

PREFIX = "/home-services"

# Enum vocabularies (SCAFFOLD §1.1)
PLAN_TIERS = {"BASIC", "PLUS", "PREMIUM"}
TRADES = {"HVAC", "PEST"}
REFRIGERANTS = {"R410A", "R32", "R454B", "NONE"}
VISIT_KINDS = {"SEASONAL", "PRIORITY", "WARRANTY"}
REFRIG_ACTIONS = {"ADD", "RECOVER"}


# ===========================================================================
# Error handling
# ===========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error("ERR_VALIDATION", 422, "Unexpected error: %s" % e)


def _auth(allowed_roles):
    """Run priority-1 auth then priority-2 authorization; return (user_id, role)."""
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return user_id, role


def _list_response(rows, serialize_fn):
    limit, offset = pagination()
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return listing([serialize_fn(r) for r in page], limit, offset, total)


# ===========================================================================
# ServicePlan
# ===========================================================================
@app.route(PREFIX + "/service-plans", methods=["POST"])
def create_plan():
    _auth(["ContractAdmin"])
    body = get_body()
    tier = req_enum(body, "tier", PLAN_TIERS)
    trade = req_enum(body, "trade", TRADES)
    annual_fee = req_int(body, "annual_fee_cents", minimum=0)
    included = req_int(body, "included_visits_per_year", minimum=0)
    extra_fee = req_int(body, "extra_visit_fee_cents", minimum=0)
    sla_hours = req_int(body, "sla_response_hours", minimum=1)
    discount = req_number(body, "parts_discount_pct", lo=0, hi=1)
    auto_renew_default = opt_bool(body, "auto_renew_default", default=True)
    rec = models.new_record("ServicePlan", {
        "tier": tier, "trade": trade, "annual_fee_cents": annual_fee,
        "included_visits_per_year": included, "extra_visit_fee_cents": extra_fee,
        "sla_response_hours": sla_hours, "parts_discount_pct": discount,
        "auto_renew_default": auto_renew_default, "active": True,
    })
    db.service_plans[rec["id"]] = rec
    return created(models.serialize(rec))


@app.route(PREFIX + "/service-plans/<pid>", methods=["GET"])
def get_plan(pid):
    _auth(["ContractAdmin", "Dispatcher", "Customer"])
    rec = L.plan(pid)
    return ok(models.serialize(rec))


@app.route(PREFIX + "/service-plans", methods=["GET"])
def list_plans():
    _auth(["ContractAdmin", "Dispatcher", "Customer"])
    rows = list(db.service_plans.values())
    tier = request.args.get("tier")
    trade = request.args.get("trade")
    if tier is not None:
        rows = [r for r in rows if r["tier"] == tier]
    if trade is not None:
        rows = [r for r in rows if r["trade"] == trade]
    return _list_response(rows, models.serialize)


@app.route(PREFIX + "/service-plans/<pid>/retire", methods=["POST"])
def retire_plan(pid):
    _auth(["ContractAdmin"])
    rec = L.plan(pid)
    if rec["active"]:
        rec["active"] = False
        models.touch(rec)
    return ok(models.serialize(rec))


# ===========================================================================
# Customer
# ===========================================================================
@app.route(PREFIX + "/customers", methods=["POST"])
def create_customer():
    _auth(["ContractAdmin"])
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email", non_empty=True)
    # email unique among customers (PRD §3.2)
    for c in db.customers.values():
        if c["email"] == email:
            raise err("ERR_INVALID_REQUEST", "Email already in use")
    rec = models.new_record("Customer", {
        "full_name": full_name, "email": email, "billing_balance_cents": 0,
    })
    db.customers[rec["id"]] = rec
    return created(models.serialize(rec))


@app.route(PREFIX + "/customers/<cid>", methods=["GET"])
def get_customer(cid):
    user_id, role = _auth(["ContractAdmin", "Customer"])
    rec = L.customer(cid)
    if role == "Customer":
        L.require_customer_owns(user_id, rec["id"])
    return ok(models.serialize(rec))


# ===========================================================================
# Site
# ===========================================================================
@app.route(PREFIX + "/sites", methods=["POST"])
def create_site():
    _auth(["ContractAdmin"])
    body = get_body()
    customer_id = req_str(body, "customer_id")
    address = req_str(body, "address")
    region_code = req_str(body, "region_code", non_empty=True)
    access_notes = opt_str(body, "access_notes", default="")
    L.customer(customer_id)  # existence (priority 4)
    rec = models.new_record("Site", {
        "customer_id": customer_id, "address": address,
        "region_code": region_code, "access_notes": access_notes,
    })
    db.sites[rec["id"]] = rec
    return created(models.serialize(rec))


@app.route(PREFIX + "/sites/<sid>", methods=["GET"])
def get_site(sid):
    user_id, role = _auth(["ContractAdmin", "Dispatcher", "Customer"])
    rec = L.site(sid)
    if role == "Customer":
        L.require_customer_owns(user_id, L.owner_customer_id_of_site(rec))
    return ok(models.serialize(rec))


@app.route(PREFIX + "/sites", methods=["GET"])
def list_sites():
    user_id, role = _auth(["ContractAdmin", "Dispatcher", "Customer"])
    rows = list(db.sites.values())
    customer_id = request.args.get("customer_id")
    region_code = request.args.get("region_code")
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if region_code is not None:
        rows = [r for r in rows if r["region_code"] == region_code]
    if role == "Customer":
        rows = [r for r in rows if r["customer_id"] == user_id]
    return _list_response(rows, models.serialize)


@app.route(PREFIX + "/sites/<sid>/equipment", methods=["GET"])
def list_site_equipment(sid):
    user_id, role = _auth(["ContractAdmin", "Dispatcher", "Customer", "Technician"])
    site = L.site(sid)
    if role == "Customer":
        L.require_customer_owns(user_id, site["customer_id"])
    rows = [e for e in db.equipment.values() if e["site_id"] == sid]
    for e in rows:
        S.refresh_warranty(e)
    return _list_response(rows, models.serialize)


# ===========================================================================
# Equipment
# ===========================================================================
@app.route(PREFIX + "/equipment", methods=["POST"])
def create_equipment():
    _auth(["ContractAdmin"])
    body = get_body()
    site_id = req_str(body, "site_id")
    model = req_str(body, "model")
    refrigerant_type = opt_enum(body, "refrigerant_type", REFRIGERANTS, default="NONE")
    nameplate = req_int(body, "nameplate_charge_grams", minimum=0)
    warranty_expires_at = parse_dt(body, "warranty_expires_at", required=True)
    L.site(site_id)  # existence
    rec = models.new_record("Equipment", {
        "site_id": site_id, "model": model, "refrigerant_type": refrigerant_type,
        "nameplate_charge_grams": nameplate, "current_charge_grams": nameplate,
        "operational_status": "OPERATIONAL", "warranty_status": "IN_WARRANTY",
        "warranty_expires_at": db.iso(warranty_expires_at),
    })
    db.equipment[rec["id"]] = rec
    return created(models.serialize(rec))


@app.route(PREFIX + "/equipment/<eid>", methods=["GET"])
def get_equipment(eid):
    _auth(["ContractAdmin", "Dispatcher", "Customer", "Technician"])
    rec = L.equipment(eid)
    S.refresh_warranty(rec)
    return ok(models.serialize(rec))


@app.route(PREFIX + "/equipment/<eid>/flag-service", methods=["POST"])
def flag_equipment(eid):
    _auth(["Technician"])
    rec = L.equipment(eid)
    if rec["operational_status"] != "OPERATIONAL":
        raise err("ERR_INVALID_STATE", "Equipment is not OPERATIONAL")
    rec["operational_status"] = "NEEDS_SERVICE"
    models.touch(rec)
    return ok(models.serialize(rec))


@app.route(PREFIX + "/equipment/<eid>/clear-service", methods=["POST"])
def clear_equipment(eid):
    _auth(["Technician"])
    rec = L.equipment(eid)
    if rec["operational_status"] != "NEEDS_SERVICE":
        raise err("ERR_INVALID_STATE", "Equipment is not NEEDS_SERVICE")
    # PRD §3.9: only once recharged into spec (>= 10% of nameplate).
    if not S.at_or_above_low_charge(rec):
        raise err("ERR_INVALID_STATE", "Equipment not recharged into spec")
    rec["operational_status"] = "OPERATIONAL"
    models.touch(rec)
    return ok(models.serialize(rec))


@app.route(PREFIX + "/equipment/<eid>/decommission", methods=["POST"])
def decommission_equipment(eid):
    _auth(["ContractAdmin"])
    rec = L.equipment(eid)
    if rec["operational_status"] not in ("OPERATIONAL", "NEEDS_SERVICE"):
        raise err("ERR_INVALID_STATE", "Equipment cannot be decommissioned from its state")
    # PRD §3.9 / priority 11: current_charge_grams must be exactly 0.
    if rec["current_charge_grams"] != 0:
        raise err("ERR_REFRIGERANT_NOT_EVACUATED",
                  "Equipment still holds refrigerant")
    rec["operational_status"] = "DECOMMISSIONED"
    models.touch(rec)
    return ok(models.serialize(rec))


# ===========================================================================
# Technician
# ===========================================================================
@app.route(PREFIX + "/technicians", methods=["POST"])
def create_technician():
    _auth(["ContractAdmin"])
    body = get_body()
    full_name = req_str(body, "full_name")
    region_code = req_str(body, "region_code")
    trade = req_enum(body, "trade", TRADES)
    epa_certified = opt_bool(body, "epa_certified", default=False)
    capacity = req_int(body, "daily_visit_capacity", minimum=1)
    rec = models.new_record("Technician", {
        "full_name": full_name, "region_code": region_code, "trade": trade,
        "epa_certified": epa_certified, "daily_visit_capacity": capacity,
    })
    db.technicians[rec["id"]] = rec
    return created(models.serialize(rec))


@app.route(PREFIX + "/technicians/<tid>", methods=["GET"])
def get_technician(tid):
    _auth(["ContractAdmin", "Dispatcher"])
    rec = L.technician(tid)
    return ok(models.serialize(rec))


@app.route(PREFIX + "/technicians", methods=["GET"])
def list_technicians():
    _auth(["ContractAdmin", "Dispatcher"])
    rows = list(db.technicians.values())
    region_code = request.args.get("region_code")
    trade = request.args.get("trade")
    if region_code is not None:
        rows = [r for r in rows if r["region_code"] == region_code]
    if trade is not None:
        rows = [r for r in rows if r["trade"] == trade]
    return _list_response(rows, models.serialize)


# Membership / visit / offer / refrigerant / part / claim / clock routes are
# registered from routes_extra to keep this module readable.
import routes_extra  # noqa: E402
routes_extra.register(app, PREFIX)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
