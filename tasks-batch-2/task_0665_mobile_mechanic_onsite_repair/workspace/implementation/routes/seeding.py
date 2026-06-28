"""System / seeding endpoints: clock, catalog parts, fleet accounts, customers, mechanics."""
from flask import Blueprint

import db
import errors
import response
from middleware import authenticate, require_role, parse_pagination, paginate
from services import models, validate

bp = Blueprint("seeding", __name__)


def _sorted(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


# ---- logical clock ----
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = validate.get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise errors.invalid_request("Missing required field: to_iso8601")
    db.store.clock = validate.parse_dt(body["to_iso8601"])
    return response.success({}, 200)


# ---- catalog parts ----
@bp.route("/catalog-parts", methods=["POST"])
def create_catalog_part():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = validate.get_body()
    sku = validate.require_str(body, "sku")
    name = validate.require_str(body, "name")
    wholesale = validate.require_int(body, "wholesale_cost_cents", exclusive_min=0)
    # sku uniqueness
    for p in db.store.catalog_parts.values():
        if p["sku"] == sku:
            raise errors.invalid_request("sku must be unique.")
    rec = models.make_catalog_part(db.store, sku, name, wholesale)
    db.store.catalog_parts[rec["id"]] = rec
    return response.success(models.serialize(rec), 201)


@bp.route("/catalog-parts/<cid>", methods=["GET"])
def get_catalog_part(cid):
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Mechanic", "Dispatcher"})
    rec = db.store.catalog_parts.get(cid)
    if rec is None:
        raise errors.not_found("Catalog part not found.")
    return response.success(models.serialize(rec), 200)


# ---- fleet accounts ----
@bp.route("/fleet-accounts", methods=["POST"])
def create_fleet_account():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = validate.get_body()
    company_name = validate.require_str(body, "company_name")
    credit_limit = validate.require_int(body, "credit_limit_cents", minimum=0)
    discount = validate.require_number(body, "labor_discount_pct", minimum=0)
    if discount > 0.40:
        raise errors.invalid_request("labor_discount_pct must be between 0 and 0.40.")
    rec = models.make_fleet_account(db.store, company_name, credit_limit, discount)
    db.store.fleet_accounts[rec["id"]] = rec
    return response.success(models.serialize(rec), 201)


@bp.route("/fleet-accounts/<fid>", methods=["GET"])
def get_fleet_account(fid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "FleetManager"})
    rec = db.store.fleet_accounts.get(fid)
    if rec is None:
        raise errors.not_found("Fleet account not found.")
    if role == "FleetManager" and uid != fid:
        raise errors.not_owner("FleetManager may only read its own fleet account.")
    return response.success(models.serialize(rec), 200)


@bp.route("/fleet-accounts/<fid>/suspend", methods=["POST"])
def suspend_fleet_account(fid):
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    rec = db.store.fleet_accounts.get(fid)
    if rec is None:
        raise errors.not_found("Fleet account not found.")
    rec["status"] = "SUSPENDED"
    models.touch(rec, db.store)
    return response.success(models.serialize(rec), 200)


@bp.route("/fleet-accounts/<fid>/payments", methods=["GET"])
def list_fleet_payments(fid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "FleetManager"})
    rec = db.store.fleet_accounts.get(fid)
    if rec is None:
        raise errors.not_found("Fleet account not found.")
    if role == "FleetManager" and uid != fid:
        raise errors.not_owner("FleetManager may only read its own fleet payments.")
    limit, offset = parse_pagination()
    items = [p for p in db.store.payments.values() if p.get("fleet_account_id") == fid]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(p) for p in page], limit, offset, total)


# ---- customers ----
@bp.route("/customers", methods=["POST"])
def create_customer():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = validate.get_body()
    email = validate.require_str(body, "email")
    full_name = validate.require_str(body, "full_name")
    home_zone = validate.require_str(body, "home_zone_code")
    if home_zone not in db.ZONE_CODES:
        raise errors.invalid_request("home_zone_code must be one of the declared zones.")
    fleet_id = body.get("fleet_account_id")
    # existence check for body FK (priority 3)
    if fleet_id is not None:
        if not isinstance(fleet_id, str) or db.store.fleet_accounts.get(fleet_id) is None:
            raise errors.not_found("fleet_account_id does not resolve.")
    email_l = email.lower()
    for c in db.store.customers.values():
        if c["email"] == email_l:
            raise errors.invalid_request("email must be unique (case-insensitive).")
    rec = models.make_customer(db.store, email_l, full_name, home_zone, fleet_id)
    db.store.customers[rec["id"]] = rec
    return response.success(models.serialize(rec), 201)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer"})
    rec = db.store.customers.get(cid)
    if rec is None:
        raise errors.not_found("Customer not found.")
    if role == "Customer" and uid != cid:
        raise errors.not_owner("Customer may only read its own record.")
    return response.success(models.serialize(rec), 200)


@bp.route("/customers/<cid>/service-requests", methods=["GET"])
def list_customer_service_requests(cid):
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Customer"})
    rec = db.store.customers.get(cid)
    if rec is None:
        raise errors.not_found("Customer not found.")
    if role == "Customer" and uid != cid:
        raise errors.not_owner("Customer may only read its own service requests.")
    limit, offset = parse_pagination()
    items = [s for s in db.store.service_requests.values() if s["customer_id"] == cid]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(s) for s in page], limit, offset, total)


@bp.route("/customers", methods=["GET"])
def list_customers():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "FleetManager"})
    limit, offset = parse_pagination()
    from flask import request
    fleet_filter = request.args.get("fleet_account_id")
    items = list(db.store.customers.values())
    if fleet_filter is not None:
        items = [c for c in items if c.get("fleet_account_id") == fleet_filter]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(c) for c in page], limit, offset, total)


# ---- mechanics ----
@bp.route("/mechanics", methods=["POST"])
def create_mechanic():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    body = validate.get_body()
    full_name = validate.require_str(body, "full_name")
    zone = validate.require_str(body, "zone_code")
    if zone not in db.ZONE_CODES:
        raise errors.invalid_request("zone_code must be one of the declared zones.")
    skill = validate.require_enum(body, "skill_tier", {"TIER1", "TIER2", "TIER3"})
    rate = validate.require_int(body, "labor_rate_cents_per_hour", exclusive_min=0)
    rec = models.make_mechanic(db.store, full_name, zone, skill, rate)
    db.store.mechanics[rec["id"]] = rec
    return response.success(models.serialize(rec), 201)


@bp.route("/mechanics/<mid>", methods=["GET"])
def get_mechanic(mid):
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Mechanic"})
    rec = db.store.mechanics.get(mid)
    if rec is None:
        raise errors.not_found("Mechanic not found.")
    return response.success(models.serialize(rec), 200)


@bp.route("/mechanics/<mid>/job-visits", methods=["GET"])
def list_mechanic_job_visits(mid):
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Mechanic"})
    rec = db.store.mechanics.get(mid)
    if rec is None:
        raise errors.not_found("Mechanic not found.")
    limit, offset = parse_pagination()
    items = [v for v in db.store.job_visits.values() if v["mechanic_id"] == mid]
    items = _sorted(items)
    page, total = paginate(items, limit, offset)
    return response.success_list([models.serialize(v) for v in page], limit, offset, total)
