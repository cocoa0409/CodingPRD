"""Clock, Customer, Technician, GeneratorModel routes."""
from flask import Blueprint

import calc
import db
import posture
from auth import get_principal, require_roles
from clock import parse_iso8601, set_now
from errors import err
from response import success
from serialize import out
from validate import (
    get_body, opt_bool, opt_int, opt_str, require_enum, require_number,
    require_str,
)
from routes.common import find_or_404, render_list

bp = Blueprint("onboarding", __name__)


# ---- Logical clock ---------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    principal = get_principal()
    require_roles(principal, {"ServiceManager", "ComplianceOfficer"})
    body = get_body()
    raw = body.get("to_iso8601")
    if raw is None:
        raise err("ERR_INVALID_REQUEST", "Missing to_iso8601")
    try:
        dt = parse_iso8601(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO8601 instant")
    set_now(dt)
    posture.sweep_all()
    return success({}, status=200)


# ---- Customers -------------------------------------------------------------
@bp.route("/customers", methods=["POST"])
def create_customer():
    principal = get_principal()
    require_roles(principal, {"Anonymous", "ServiceManager"})
    body = get_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    service_address = require_str(body, "service_address")
    elevation_ft = opt_int(body, "elevation_ft", default=0, minimum=0)
    phone = opt_str(body, "phone", default=None)

    for c in db.customers.values():
        if c["email"] == email:
            raise err("ERR_DUPLICATE_EMAIL", "Email already registered")

    rec = db.base_record(full_common=True)
    rec.update({
        "email": email,
        "full_name": full_name,
        "service_address": service_address,
        "elevation_ft": elevation_ft,
        "phone": phone,
    })
    db.customers[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.customers, customer_id)
    return success(out(rec), status=200)


@bp.route("/customers/<customer_id>/projects", methods=["GET"])
def list_customer_projects(customer_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    find_or_404(db.customers, customer_id)
    records = [p for p in db.projects.values() if p["customer_id"] == customer_id]
    return render_list(records)


@bp.route("/customers/<customer_id>/units", methods=["GET"])
def list_customer_units(customer_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    find_or_404(db.customers, customer_id)
    records = [u for u in db.units.values() if u["customer_id"] == customer_id]
    return render_list(records)


# ---- Technicians -----------------------------------------------------------
@bp.route("/technicians", methods=["POST"])
def create_technician():
    principal = get_principal()
    require_roles(principal, {"Anonymous", "ServiceManager"})
    body = get_body()
    name = require_str(body, "name")
    license_no = require_str(body, "license_no")
    gas_certified = opt_bool(body, "gas_certified", default=False)

    for t in db.technicians.values():
        if t["license_no"] == license_no:
            raise err("ERR_DUPLICATE_LICENSE", "License number already registered")

    rec = db.base_record(full_common=True)
    rec.update({
        "name": name,
        "license_no": license_no,
        "gas_certified": gas_certified,
        "status": "ACTIVE",
        "open_dispatch_count": 0,
    })
    db.technicians[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/technicians/<technician_id>", methods=["GET"])
def get_technician(technician_id):
    principal = get_principal()
    require_roles(principal, {"Technician", "ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.technicians, technician_id)
    return success(out(rec), status=200)


@bp.route("/technicians/<technician_id>", methods=["PATCH"])
def update_technician(technician_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager"})
    rec = find_or_404(db.technicians, technician_id)
    body = get_body()
    changed = False
    if "status" in body and body["status"] is not None:
        status = require_enum(body, "status", {"ACTIVE", "SUSPENDED"})
        rec["status"] = status
        changed = True
    if "gas_certified" in body and body["gas_certified"] is not None:
        rec["gas_certified"] = opt_bool(body, "gas_certified")
        changed = True
    if changed:
        db.touch(rec)
    return success(out(rec), status=200)


# ---- Generator models ------------------------------------------------------
@bp.route("/models", methods=["POST"])
def create_model():
    principal = get_principal()
    require_roles(principal, {"ServiceManager"})
    body = get_body()
    sku = require_str(body, "sku")
    rated_kw = require_number(body, "rated_kw", gt=0)
    fuel_types = body.get("fuel_types")
    if not isinstance(fuel_types, list) or not fuel_types:
        raise err("ERR_INVALID_REQUEST", "fuel_types must be a non-empty array")
    for f in fuel_types:
        if f not in ("NG", "PROPANE"):
            raise err("ERR_INVALID_REQUEST", "fuel_types must be a subset of {NG, PROPANE}")
    unit_price_cents = require_number(body, "unit_price_cents", ge=0)
    if isinstance(unit_price_cents, bool) or not isinstance(unit_price_cents, int):
        raise err("ERR_INVALID_REQUEST", "unit_price_cents must be an integer")
    warranty_months = body.get("warranty_months")
    if isinstance(warranty_months, bool) or not isinstance(warranty_months, int) or warranty_months < 0:
        raise err("ERR_INVALID_REQUEST", "warranty_months must be an integer >= 0")
    active = opt_bool(body, "active", default=True)

    for m in db.models.values():
        if m["sku"] == sku:
            raise err("ERR_DUPLICATE_SKU", "SKU already exists")

    rec = db.base_record(full_common=False)
    rec.update({
        "sku": sku,
        "rated_kw": rated_kw,
        "fuel_types": list(fuel_types),
        "unit_price_cents": unit_price_cents,
        "warranty_months": warranty_months,
        "active": active,
    })
    db.models[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/models/<model_id>", methods=["GET"])
def get_model(model_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "Technician", "ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.models, model_id)
    return success(out(rec), status=200)


@bp.route("/models/<model_id>/recall-campaigns", methods=["GET"])
def list_model_recalls(model_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager", "ComplianceOfficer"})
    find_or_404(db.models, model_id)
    records = [c for c in db.recall_campaigns.values() if c["model_id"] == model_id]
    return render_list(records)
