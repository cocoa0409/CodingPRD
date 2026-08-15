"""Customers, sites, equipment units, accessory kits."""
from decimal import Decimal

from flask import Blueprint, request

from auth import auth, body, check_customer_owns, customer_scope_filter, get_or_404, require_roles
from calc import emissions_screening, fuel_burn_projection
from db import DB, customer_out, kit_out, site_out, unit_out
from errors import (
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_NOT_OWNER,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
    raise_err,
)
from response import success_object
from routes.common import paginate
from util import as_decimal, as_int, new_id, now

bp = Blueprint("core", __name__)

CREDIT_STATUSES = {"GOOD", "WATCH", "HOLD"}
UNIT_TYPES = {"GENERATOR", "CHILLER"}
FUEL_TYPES = {"DIESEL", "NATURAL_GAS"}
EMISSIONS_TIERS = {"TIER_2", "TIER_4F"}


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@bp.post("/power-rental/customers")
def create_customer():
    uid, role = auth()
    require_roles(role, ["SalesEngineer"])
    b = body()
    name = b.get("name")
    billing_email = b.get("billing_email")
    credit_status = b.get("credit_status", "GOOD")
    standby = b.get("standby_contract", False)
    sla = b.get("sla_response_minutes", 240)
    loyalty = b.get("loyalty_discount_pct", 0)
    if not isinstance(name, str) or not name:
        raise_err(ERR_VALIDATION, "name is required.")
    if not isinstance(billing_email, str) or not billing_email:
        raise_err(ERR_VALIDATION, "billing_email is required.")
    if credit_status not in CREDIT_STATUSES:
        raise_err(ERR_VALIDATION, "credit_status must be GOOD, WATCH, or HOLD.")
    if not isinstance(standby, bool):
        raise_err(ERR_VALIDATION, "standby_contract must be a boolean.")
    if as_int(sla) is None or as_int(sla) <= 0:
        raise_err(ERR_VALIDATION, "sla_response_minutes must be a positive integer.")
    loyalty_d = as_decimal(loyalty)
    if loyalty_d is None or loyalty_d < 0 or loyalty_d >= 1:
        raise_err(ERR_VALIDATION, "loyalty_discount_pct must satisfy 0 <= x < 1.")
    ts = now()
    rec = {
        "id": new_id(),
        "name": name,
        "billing_email": billing_email,
        "credit_status": credit_status,
        "standby_contract": standby,
        "sla_response_minutes": as_int(sla),
        "loyalty_discount_pct": loyalty_d,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.customers[rec["id"]] = rec
    return success_object(customer_out(rec), status=201)


@bp.get("/power-rental/customers/<cid>")
def get_customer(cid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "DepotManager", "Customer", "FleetDispatcher", "ClaimsAssessor"])
    if role == "Customer" and cid != uid:
        raise_err(ERR_NOT_OWNER, "Customers may only read their own record.")
    rec = get_or_404(DB.customers, cid, "customer")
    return success_object(customer_out(rec))


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

@bp.post("/power-rental/sites")
def create_site():
    uid, role = auth()
    require_roles(role, ["SalesEngineer"])
    b = body()
    customer_id = b.get("customer_id")
    # Tier 3: body FK existence (only for provided values).
    if customer_id is not None and customer_id not in DB.customers:
        raise_err(ERR_REFERENCE_NOT_FOUND, "customer_id references a non-existent customer.")
    name = b.get("name")
    jurisdiction = b.get("jurisdiction_code")
    capacity = b.get("fuel_tank_capacity_liters")
    if customer_id is None:
        raise_err(ERR_VALIDATION, "customer_id is required.")
    if not isinstance(name, str) or not name:
        raise_err(ERR_VALIDATION, "name is required.")
    if not isinstance(jurisdiction, str) or not jurisdiction:
        raise_err(ERR_VALIDATION, "jurisdiction_code is required.")
    if as_int(capacity) is None or as_int(capacity) <= 0:
        raise_err(ERR_VALIDATION, "fuel_tank_capacity_liters must be a positive integer.")
    ts = now()
    rec = {
        "id": new_id(),
        "customer_id": customer_id,
        "name": name,
        "jurisdiction_code": jurisdiction,
        "fuel_tank_capacity_liters": as_int(capacity),
        "tank_level_liters": Decimal(0),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.sites[rec["id"]] = rec
    return success_object(site_out(rec), status=201)


@bp.get("/power-rental/sites/<sid>")
def get_site(sid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "DepotManager", "Customer", "FleetDispatcher", "FieldTechnician"])
    rec = DB.sites.get(sid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "No site exists with id %s." % sid)
    if role == "Customer":
        check_customer_owns(rec["customer_id"], uid)
    return success_object(site_out(rec))


@bp.get("/power-rental/sites")
def list_sites():
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "DepotManager", "Customer"])
    records = list(DB.sites.values())
    scoped = customer_scope_filter(role, uid)
    if scoped is not None:
        records = [r for r in records if r["customer_id"] == scoped]
    elif request.args.get("customer_id") is not None:
        records = [r for r in records if r["customer_id"] == request.args.get("customer_id")]
    return paginate(records, site_out)


@bp.get("/power-rental/sites/<sid>/emissions-screening")
def site_emissions_screening(sid):
    uid, role = auth()
    require_roles(role, ["SalesEngineer", "DepotManager"])
    rec = get_or_404(DB.sites, sid, "site")
    return success_object(emissions_screening(rec))


# ---------------------------------------------------------------------------
# Equipment units
# ---------------------------------------------------------------------------

@bp.post("/power-rental/equipment-units")
def create_unit():
    uid, role = auth()
    require_roles(role, ["DepotManager"])
    b = body()
    required = ["unit_type", "capacity_kw", "fuel_type", "emissions_tier",
                "nox_g_per_kwh", "day_rate_cents", "week_rate_cents",
                "month_rate_cents", "demob_fee_cents", "home_depot_code"]
    for field in required:
        if b.get(field) is None:
            raise_err(ERR_VALIDATION, "%s is required." % field)
    if b["unit_type"] not in UNIT_TYPES:
        raise_err(ERR_VALIDATION, "unit_type must be GENERATOR or CHILLER.")
    if as_int(b["capacity_kw"]) is None or as_int(b["capacity_kw"]) <= 0:
        raise_err(ERR_VALIDATION, "capacity_kw must be a positive integer.")
    if b["fuel_type"] not in FUEL_TYPES:
        raise_err(ERR_VALIDATION, "fuel_type must be DIESEL or NATURAL_GAS.")
    if b["emissions_tier"] not in EMISSIONS_TIERS:
        raise_err(ERR_VALIDATION, "emissions_tier must be TIER_2 or TIER_4F.")
    nox = as_decimal(b["nox_g_per_kwh"])
    if nox is None or nox <= 0:
        raise_err(ERR_VALIDATION, "nox_g_per_kwh must be a positive number.")
    for field in ("day_rate_cents", "week_rate_cents", "month_rate_cents"):
        if as_int(b[field]) is None or as_int(b[field]) <= 0:
            raise_err(ERR_VALIDATION, "%s must be a positive integer." % field)
    if as_int(b["demob_fee_cents"]) is None or as_int(b["demob_fee_cents"]) < 0:
        raise_err(ERR_VALIDATION, "demob_fee_cents must be a non-negative integer.")
    if not isinstance(b["home_depot_code"], str) or not b["home_depot_code"]:
        raise_err(ERR_VALIDATION, "home_depot_code is required.")
    ts = now()
    rec = {
        "id": new_id(),
        "unit_type": b["unit_type"],
        "capacity_kw": as_int(b["capacity_kw"]),
        "fuel_type": b["fuel_type"],
        "emissions_tier": b["emissions_tier"],
        "nox_g_per_kwh": nox,
        "day_rate_cents": as_int(b["day_rate_cents"]),
        "week_rate_cents": as_int(b["week_rate_cents"]),
        "month_rate_cents": as_int(b["month_rate_cents"]),
        "demob_fee_cents": as_int(b["demob_fee_cents"]),
        "home_depot_code": b["home_depot_code"],
        "status": "AVAILABLE",
        "current_site_id": None,
        "runtime_hours_total": Decimal(0),
        "fuel_consumed_liters_total": Decimal(0),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }
    DB.units[rec["id"]] = rec
    return success_object(unit_out(rec), status=201)


@bp.get("/power-rental/equipment-units/<uid_>")
def get_unit(uid_):
    uid, role = auth()
    require_roles(role, ["DepotManager", "SalesEngineer", "FleetDispatcher", "FieldTechnician"])
    rec = get_or_404(DB.units, uid_, "equipment unit")
    return success_object(unit_out(rec))


@bp.get("/power-rental/equipment-units")
def list_units():
    uid, role = auth()
    require_roles(role, ["DepotManager", "SalesEngineer", "FleetDispatcher"])
    records = list(DB.units.values())
    if request.args.get("status") is not None:
        records = [r for r in records if r["status"] == request.args.get("status")]
    if request.args.get("current_site_id") is not None:
        records = [r for r in records if r["current_site_id"] == request.args.get("current_site_id")]
    return paginate(records, unit_out)


@bp.post("/power-rental/equipment-units/<uid_>/complete-maintenance")
def complete_maintenance(uid_):
    uid, role = auth()
    require_roles(role, ["DepotManager"])
    rec = get_or_404(DB.units, uid_, "equipment unit")
    if rec["status"] != "MAINTENANCE":
        raise_err(ERR_INVALID_STATE, "Unit must be in MAINTENANCE to complete maintenance.")
    rec["status"] = "AVAILABLE"
    rec["updated_at"] = now()
    rec["version"] += 1
    return success_object(unit_out(rec))


@bp.get("/power-rental/equipment-units/<uid_>/fuel-projection")
def fuel_projection(uid_):
    uid, role = auth()
    require_roles(role, ["DepotManager", "SalesEngineer", "FleetDispatcher", "FieldTechnician"])
    rec = get_or_404(DB.units, uid_, "equipment unit")
    method = request.args.get("method", "METERED_AVG")
    if method not in ("RATED_CURVE", "METERED_AVG"):
        raise_err(ERR_VALIDATION, "method must be RATED_CURVE or METERED_AVG.")
    return success_object(fuel_burn_projection(rec, method))


# ---------------------------------------------------------------------------
# Accessory kits (immutable catalog: id + created_at only)
# ---------------------------------------------------------------------------

@bp.post("/power-rental/accessory-kits")
def create_kit():
    uid, role = auth()
    require_roles(role, ["DepotManager"])
    b = body()
    kit_code = b.get("kit_code")
    description = b.get("description")
    max_amp = b.get("max_ampacity_a")
    if not isinstance(kit_code, str) or not kit_code:
        raise_err(ERR_VALIDATION, "kit_code is required.")
    if any(k["kit_code"] == kit_code for k in DB.kits.values()):
        raise_err(ERR_VALIDATION, "kit_code %s already exists." % kit_code)
    if not isinstance(description, str) or not description:
        raise_err(ERR_VALIDATION, "description is required.")
    if as_int(max_amp) is None or as_int(max_amp) <= 0:
        raise_err(ERR_VALIDATION, "max_ampacity_a must be a positive integer.")
    rates = {}
    for field in ("day_rate_cents", "week_rate_cents", "month_rate_cents"):
        if as_int(b.get(field)) is None or as_int(b.get(field)) <= 0:
            raise_err(ERR_VALIDATION, "%s must be a positive integer." % field)
        rates[field] = as_int(b[field])
    rec = {
        "id": new_id(),
        "kit_code": kit_code,
        "description": description,
        "max_ampacity_a": as_int(max_amp),
        "day_rate_cents": rates["day_rate_cents"],
        "week_rate_cents": rates["week_rate_cents"],
        "month_rate_cents": rates["month_rate_cents"],
        "created_at": now(),
        "_seq": DB.next_seq(),
    }
    DB.kits[rec["id"]] = rec
    return success_object(kit_out(rec), status=201)


@bp.get("/power-rental/accessory-kits/<kid>")
def get_kit(kid):
    uid, role = auth()
    require_roles(role, ["DepotManager", "SalesEngineer"])
    rec = get_or_404(DB.kits, kid, "accessory kit")
    return success_object(kit_out(rec))
